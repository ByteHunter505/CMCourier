"""AS400 NIARVILOG coordination adapter (034 phase 2).

Owns the distributed-idempotency layer on top of the existing
``SQLiteTrackingStore``. NOT an :class:`ITrackingStore` — this is a
separate coordination surface used by :class:`IdempotencyCoordinator`
when ``tracking.as400_sync.enabled=true``.

Constitution Principle VI applies: the AS400 server is never mocked,
but the ``pyodbc`` driver bindings ARE faked at the cursor / connection
level for tests (mirror of :class:`As400DataSource`).

Field mapping (locked in spec 034):

    SISCOD  ← trigger.system_id           (CHAR(1))
    TRNNUM  ← document.txn_num             (CHAR(7), = ABAANB)
    DOCFRM  ← document.index7              (CHAR(30), = ABAHCD)
    IMGARC  ← document.file_name           (CHAR(12), first page)
    IMGTIP  ← document.image_type          (CHAR(1))
    CTECIF  ← trigger.shortname            (VARCHAR(30))
    CTENUM  ← int(trigger.cif or 0)        (DECIMAL(9,0))
    STSCOD  ← derived: N/I/O/F
    IDNBAC  ← mapping.id_corto (== IDCM)   (VARCHAR(10))
    TIPIDN  ← mapping.cmis_type            (VARCHAR(128), '' until 035)
    OBJIDN  ← record.cm_object_id          (VARCHAR(128), post-S5)
    NUMREI  ← record.retry_count           (INTEGER)
    PMRREI  ← record.started_at or NOW()   (TIMESTAMP)
    FINREI  ← DB2 auto-update              (TIMESTAMP)
    EERRMSG ← record.error_message         (VARCHAR(1024))
"""

from __future__ import annotations

__all__ = [
    "As400CoordinationError",
    "As400NiarvilogStore",
    "NiarvilogRow",
]

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cmcourier.config.schema import As400ConnectionConfig
from cmcourier.domain.models import (
    CMMapping,
    MigrationRecord,
    RVABREPDocument,
    TriggerRecord,
)

_network_log = logging.getLogger("cmcourier.metrics.network")
_log = logging.getLogger(__name__)

# Lazy import — same pattern as As400DataSource.
pyodbc: Any = None


class As400CoordinationError(Exception):
    """Raised when an NIARVILOG operation fails irrecoverably.

    Wraps the underlying pyodbc.Error. Phase 5 will introduce retry /
    backoff so transient errors don't propagate as this exception.
    """


@dataclass(frozen=True, slots=True)
class NiarvilogRow:
    """One row of RVILIB.NIARVILOG (read shape)."""

    siscod: str
    trnnum: str
    docfrm: str
    imgarc: str
    imgtip: str
    ctecif: str
    ctenum: int
    stscod: str  # 'N' / 'I' / 'O' / 'F'
    idnbac: str
    tipidn: str
    objidn: str
    numrei: int
    pmrrei: datetime
    finrei: datetime
    eerrmsg: str


_SELECT_COLUMNS = (
    "SISCOD, TRNNUM, DOCFRM, IMGARC, IMGTIP, CTECIF, CTENUM, "
    "STSCOD, IDNBAC, TIPIDN, OBJIDN, NUMREI, PMRREI, FINREI, EERRMSG"
)


class As400NiarvilogStore:
    """Distributed-idempotency store over RVILIB.NIARVILOG.

    Operations:

    * :meth:`try_claim` — atomic ``UPDATE STSCOD='I' WHERE STSCOD='N'``
      with INSERT fallback for first-time rows. Returns True if we
      now own the row.
    * :meth:`mark_uploaded` — ``UPDATE STSCOD='O', OBJIDN=...`` once S5
      completes. Logs WARNING on rowcount != 1 (the row changed
      under us between claim and complete; investigate but don't
      fail the pipeline).
    * :meth:`mark_failed` — ``UPDATE STSCOD='F', EERRMSG=...,
      NUMREI=NUMREI+1`` on any stage failure.
    * :meth:`read_state` — SELECT one row by PK.
    * :meth:`cleanup_stale_in_progress` — reset rows stuck at
      ``STSCOD='I'`` for too long (a previous run crashed mid-claim).

    DB2 for i note: ``FINREI`` is declared ``ROW CHANGE TIMESTAMP`` so
    DB2 updates it implicitly on every UPDATE — our SQL never
    references it.
    """

    def __init__(
        self,
        *,
        connection: As400ConnectionConfig,
        username: str,
        password: str,
        library: str = "RVILIB",
        table: str = "NIARVILOG",
        stale_in_progress_minutes: int = 30,
    ) -> None:
        self._cfg = connection
        self._username = username
        self._password = password
        self._library = library
        self._table = table
        self._stale_minutes = stale_in_progress_minutes
        self._conn: Any = None
        self._closed = False

    # ----------------------------------------------------------- public API

    def try_claim(
        self,
        *,
        record: MigrationRecord,
        document: RVABREPDocument,
        mapping: CMMapping,
        trigger: TriggerRecord,
    ) -> bool:
        """Atomic claim. Returns True iff this process now owns the row."""
        pk = _pk_from(document=document, trigger=trigger)
        update_sql = (
            f"UPDATE {self._full_table()} "
            f"SET STSCOD = 'I', IDNBAC = ?, TIPIDN = ? "
            f"WHERE SISCOD = ? AND TRNNUM = ? AND DOCFRM = ? AND IMGARC = ? "
            f"AND STSCOD = 'N'"
        )
        params = [mapping.id_corto, mapping.cmis_type, *pk]
        rowcount = self._execute_write(update_sql, params, "niarvilog_claim_update")
        if rowcount >= 1:
            return True
        # Row doesn't exist (or already in non-N state). Try INSERT.
        try:
            self._insert_new_claim(
                document=document, mapping=mapping, trigger=trigger, record=record
            )
        except _pyodbc_integrity_error_type():
            # Race: another process inserted the row between our UPDATE
            # and INSERT. That means someone else owns it now → False.
            return False
        return True

    def mark_uploaded(
        self,
        *,
        record: MigrationRecord,  # noqa: ARG002 — kept for API symmetry
        document: RVABREPDocument,
        mapping: CMMapping,  # noqa: ARG002 — kept for API symmetry
        trigger: TriggerRecord,
        cm_object_id: str,
    ) -> None:
        pk = _pk_from(document=document, trigger=trigger)
        sql = (
            f"UPDATE {self._full_table()} "
            f"SET STSCOD = 'O', OBJIDN = ?, EERRMSG = '' "
            f"WHERE SISCOD = ? AND TRNNUM = ? AND DOCFRM = ? AND IMGARC = ?"
        )
        params = [cm_object_id, *pk]
        rowcount = self._execute_write(sql, params, "niarvilog_mark_uploaded")
        if rowcount != 1:
            _log.warning(
                "niarvilog_mark_uploaded: unexpected rowcount=%s for trnnum=%s",
                rowcount,
                pk[1],
            )

    def mark_failed(
        self,
        *,
        record: MigrationRecord,  # noqa: ARG002
        document: RVABREPDocument,
        mapping: CMMapping,  # noqa: ARG002
        trigger: TriggerRecord,
        error: str,
    ) -> None:
        pk = _pk_from(document=document, trigger=trigger)
        sql = (
            f"UPDATE {self._full_table()} "
            f"SET STSCOD = 'F', EERRMSG = ?, NUMREI = NUMREI + 1 "
            f"WHERE SISCOD = ? AND TRNNUM = ? AND DOCFRM = ? AND IMGARC = ?"
        )
        # AS400 VARCHAR(1024) — truncate defensively.
        params = [error[:1024], *pk]
        self._execute_write(sql, params, "niarvilog_mark_failed")

    def read_state(
        self,
        *,
        siscod: str,
        trnnum: str,
        docfrm: str,
        imgarc: str,
    ) -> NiarvilogRow | None:
        sql = (
            f"SELECT {_SELECT_COLUMNS} FROM {self._full_table()} "
            f"WHERE SISCOD = ? AND TRNNUM = ? AND DOCFRM = ? AND IMGARC = ?"
        )
        params = [siscod, trnnum, docfrm, imgarc]
        rows = self._execute_read(sql, params, "niarvilog_read_state")
        if not rows:
            return None
        row = rows[0]
        return NiarvilogRow(
            siscod=str(row["SISCOD"]).strip(),
            trnnum=str(row["TRNNUM"]).strip(),
            docfrm=str(row["DOCFRM"]).strip(),
            imgarc=str(row["IMGARC"]).strip(),
            imgtip=str(row["IMGTIP"]).strip(),
            ctecif=str(row["CTECIF"]).strip(),
            ctenum=int(row["CTENUM"] or 0),
            stscod=str(row["STSCOD"]).strip(),
            idnbac=str(row["IDNBAC"]).strip(),
            tipidn=str(row["TIPIDN"]).strip(),
            objidn=str(row["OBJIDN"]).strip(),
            numrei=int(row["NUMREI"] or 0),
            pmrrei=row["PMRREI"],
            finrei=row["FINREI"],
            eerrmsg=str(row["EERRMSG"]).strip(),
        )

    def cleanup_stale_in_progress(self) -> int:
        """Reset STSCOD='I' rows whose FINREI is older than threshold.

        Returns the row count. Useful when a previous claim crashed
        between UPDATE 'I' and the eventual 'O' / 'F' write.
        """
        sql = (
            f"UPDATE {self._full_table()} "
            f"SET STSCOD = 'N' "
            f"WHERE STSCOD = 'I' AND FINREI < (CURRENT_TIMESTAMP - ? MINUTES)"
        )
        return self._execute_write(sql, [self._stale_minutes], "niarvilog_cleanup_stale")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                _log.exception("AS400 close failed")
            self._conn = None

    # ----------------------------------------------------------- internals

    def _full_table(self) -> str:
        return f"{self._library}.{self._table}"

    def _insert_new_claim(
        self,
        *,
        record: MigrationRecord,  # noqa: ARG002 — kept for future fields
        document: RVABREPDocument,
        mapping: CMMapping,
        trigger: TriggerRecord,
    ) -> None:
        sql = (
            f"INSERT INTO {self._full_table()} "
            f"(SISCOD, TRNNUM, DOCFRM, IMGARC, IMGTIP, CTECIF, CTENUM, "
            f"STSCOD, IDNBAC, TIPIDN, OBJIDN, NUMREI, EERRMSG) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, 'I', ?, ?, '', 0, '')"
        )
        params: list[Any] = [
            trigger.system_id,
            document.txn_num,
            document.index7,
            document.file_name,
            document.image_type,
            trigger.shortname,
            int(trigger.cif or "0") if (trigger.cif or "").isdigit() else 0,
            mapping.id_corto,
            mapping.cmis_type,
        ]
        self._execute_write(sql, params, "niarvilog_insert_claim")

    def _execute_write(self, sql: str, params: list[Any], kind: str) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        t0 = time.monotonic()
        try:
            cursor.execute(sql, params)
            rowcount = int(cursor.rowcount)
            conn.commit()
            _network_log.info(
                kind,
                extra={
                    "kind": kind,
                    "duration_ms": round((time.monotonic() - t0) * 1000.0, 3),
                    "row_count": rowcount,
                    "sql_prefix": sql[:80],
                },
            )
            return rowcount
        except _pyodbc_integrity_error_type():
            # Caller (try_claim) handles this. Re-raise unwrapped.
            raise
        except _pyodbc_error_type() as exc:
            raise As400CoordinationError(f"NIARVILOG {kind} failed: {exc}") from exc
        finally:
            cursor.close()

    def _execute_read(self, sql: str, params: list[Any], kind: str) -> list[dict[str, Any]]:
        conn = self._connect()
        cursor = conn.cursor()
        t0 = time.monotonic()
        try:
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description or []]
            rows = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
            _network_log.info(
                kind,
                extra={
                    "kind": kind,
                    "duration_ms": round((time.monotonic() - t0) * 1000.0, 3),
                    "row_count": len(rows),
                    "sql_prefix": sql[:80],
                },
            )
            return rows
        except _pyodbc_error_type() as exc:
            raise As400CoordinationError(f"NIARVILOG {kind} failed: {exc}") from exc
        finally:
            cursor.close()

    def _connect(self) -> Any:
        if self._conn is not None:
            return self._conn
        _import_pyodbc()
        try:
            self._conn = pyodbc.connect(self._build_connection_string())
        except _pyodbc_error_type() as exc:
            raise As400CoordinationError(f"NIARVILOG connect failed: {exc}") from exc
        return self._conn

    def _build_connection_string(self) -> str:
        return (
            f"DRIVER={{{self._cfg.driver}}};"
            f"SYSTEM={self._cfg.host};"
            f"PORT={self._cfg.port};"
            f"DATABASE={self._cfg.database};"
            f"UID={self._username};"
            f"PWD={self._password};"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pk_from(*, document: RVABREPDocument, trigger: TriggerRecord) -> tuple[str, str, str, str]:
    """Build the four PK columns (SISCOD, TRNNUM, DOCFRM, IMGARC)."""
    return (
        trigger.system_id,
        document.txn_num,
        document.index7,
        document.file_name,
    )


def _import_pyodbc() -> None:
    global pyodbc
    if pyodbc is not None:
        return
    import pyodbc as _pyodbc  # noqa: PLC0415

    pyodbc = _pyodbc


def _pyodbc_error_type() -> type[BaseException]:
    if pyodbc is None:
        return RuntimeError
    return pyodbc.Error  # type: ignore[no-any-return]


def _pyodbc_integrity_error_type() -> type[BaseException]:
    if pyodbc is None:
        return RuntimeError
    # pyodbc exposes IntegrityError as a subclass of Error.
    return getattr(pyodbc, "IntegrityError", pyodbc.Error)  # type: ignore[no-any-return]

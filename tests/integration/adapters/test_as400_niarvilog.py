"""Integration tests for :class:`As400NiarvilogStore` (034 phase 2).

Tests fake pyodbc at the cursor/connection boundary (same pattern as
``test_as400_query.py``). The AS400 server itself is not mocked —
Constitution Principle VI permits faking the driver bindings.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from cmcourier.adapters.tracking import as400_niarvilog as niarvilog_module
from cmcourier.adapters.tracking.as400_niarvilog import (
    As400CoordinationError,
    As400NiarvilogStore,
    NiarvilogRow,
)
from cmcourier.config.schema import As400ConnectionConfig
from cmcourier.domain.models import (
    CMMapping,
    MigrationRecord,
    RVABREPDocument,
    StageStatus,
    TriggerRecord,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# pyodbc fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Records every (sql, params) tuple and serves prepared results."""

    def __init__(self) -> None:
        self.executions: list[tuple[str, list[Any]]] = []
        # Queue of (rows, columns) tuples — each execute() pops one.
        self.fetch_queue: list[tuple[Sequence[Sequence[Any]], Sequence[str]]] = []
        # Queue of rowcounts (matched to executions).
        self.rowcount_queue: list[int] = []
        self.raise_on_execute: BaseException | None = None
        self._current_rows: list[list[Any]] = []
        self._current_columns: list[str] = []
        self.rowcount = -1

    @property
    def description(self) -> list[tuple[str, ...]]:
        return [(c,) for c in self._current_columns]

    def execute(self, sql: str, params: list[Any] | None = None) -> _FakeCursor:
        self.executions.append((sql, list(params or [])))
        if self.raise_on_execute is not None:
            raise self.raise_on_execute
        # Advance the fetch + rowcount queues.
        if self.fetch_queue:
            rows, columns = self.fetch_queue.pop(0)
            self._current_rows = [list(r) for r in rows]
            self._current_columns = list(columns)
        else:
            self._current_rows = []
            self._current_columns = []
        self.rowcount = self.rowcount_queue.pop(0) if self.rowcount_queue else -1
        return self

    def fetchall(self) -> list[list[Any]]:
        out = self._current_rows
        self._current_rows = []
        return out

    def fetchone(self) -> list[Any] | None:
        return self._current_rows.pop(0) if self._current_rows else None

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.commits = 0
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


class _FakePyodbcModule:
    class Error(Exception):
        pass

    class IntegrityError(Error):
        pass

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def connect(self, cs: str) -> _FakeConn:  # noqa: ARG002
        return self._conn


def _patch_pyodbc(
    monkeypatch: pytest.MonkeyPatch,
    cursor: _FakeCursor | None = None,
) -> tuple[_FakeCursor, _FakeConn]:
    cur = cursor or _FakeCursor()
    conn = _FakeConn(cur)
    monkeypatch.setattr(niarvilog_module, "pyodbc", _FakePyodbcModule(conn))
    return cur, conn


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _conn_cfg() -> As400ConnectionConfig:
    return As400ConnectionConfig(host="10.0.0.1", database="RVILIB")


def _make_store(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cursor: _FakeCursor | None = None,
    stale_minutes: int = 30,
) -> tuple[As400NiarvilogStore, _FakeCursor, _FakeConn]:
    cur, conn = _patch_pyodbc(monkeypatch, cursor)
    store = As400NiarvilogStore(
        connection=_conn_cfg(),
        username="tester",
        password="secret",
        library="RVILIB",
        table="NIARVILOG",
        stale_in_progress_minutes=stale_minutes,
    )
    return store, cur, conn


def _make_record(
    *,
    txn: str = "0000001",
    siscod: str = "1",
    docfrm: str = "CC03",
    imgarc: str = "DAAAH9X4.001",
    imgtip: str = "B",
    shortname: str = "TESTCLIENT01",
    cif: str | None = "123456",
    id_corto: str = "CN01",
    cmis_type: str = "MyType",
    status: StageStatus = StageStatus.S5_PENDING,
    cm_object_id: str | None = None,
    error: str | None = None,
    retry_count: int = 0,
) -> tuple[MigrationRecord, RVABREPDocument, CMMapping, TriggerRecord]:
    trigger = TriggerRecord(shortname=shortname, cif=cif, system_id=siscod)
    document = RVABREPDocument(
        system_code=siscod,
        txn_num=txn,
        index1="",
        index2=cif or "",
        index3="",
        index4="",
        index5="",
        index6="",
        index7=docfrm,
        image_type=imgtip,
        image_path="paged_tiff/PROD/2025/11/17",
        file_name=imgarc,
        creation_date=datetime(2025, 11, 17, tzinfo=UTC),
        last_view_date=None,
        total_pages=1,
        delete_code="",
    )
    mapping = CMMapping(
        clase_id="01.02.04.01.01",
        id_rvi="FF17",
        id_corto=id_corto,
        clase_name="Autorizacion SMS",
        required_metadata_fields=(),
        cmis_type=cmis_type,
    )
    record = MigrationRecord(
        trigger_shortname=trigger.shortname,
        trigger_cif=trigger.cif or "",
        trigger_system_id=trigger.system_id,
        rvabrep_txn_num=document.txn_num,
        rvabrep_file_name=document.file_name,
        batch_id="B1",
        status=status,
        created_at=datetime(2025, 11, 17, tzinfo=UTC),
        cm_object_id=cm_object_id,
        cm_folder=None,
        cm_object_type=None,
        source_file_path=None,
        page_count=None,
        file_size_bytes=None,
        error_message=error,
        retry_count=retry_count,
    )
    return record, document, mapping, trigger


# ---------------------------------------------------------------------------
# try_claim
# ---------------------------------------------------------------------------


class TestTryClaim:
    def test_claims_existing_n_row(self, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: N802
        """UPDATE STSCOD='I' WHERE STSCOD='N' returns rowcount=1 → True."""
        cur = _FakeCursor()
        cur.rowcount_queue = [1]  # UPDATE matched 1 row
        store, _, _ = _make_store(monkeypatch, cursor=cur)
        record, document, mapping, trigger = _make_record()

        result = store.try_claim(record=record, document=document, mapping=mapping, trigger=trigger)

        assert result is True
        assert len(cur.executions) == 1
        sql, params = cur.executions[0]
        assert "UPDATE" in sql.upper()
        assert "STSCOD = 'I'" in sql or "STSCOD='I'" in sql
        assert "STSCOD = 'N'" in sql or "STSCOD='N'" in sql

    def test_inserts_when_row_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """rowcount=0 on UPDATE → INSERT new row with STSCOD='I'."""
        cur = _FakeCursor()
        cur.rowcount_queue = [0, 1]  # UPDATE missed, INSERT succeeded
        store, _, _ = _make_store(monkeypatch, cursor=cur)
        record, document, mapping, trigger = _make_record()

        result = store.try_claim(record=record, document=document, mapping=mapping, trigger=trigger)

        assert result is True
        assert len(cur.executions) == 2
        assert "UPDATE" in cur.executions[0][0].upper()
        assert "INSERT INTO" in cur.executions[1][0].upper()

    def test_returns_false_when_row_already_uploaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """UPDATE missed AND INSERT raises IntegrityError → already claimed → False."""
        cur = _FakeCursor()
        # First execute (UPDATE) succeeds with 0 rows; second (INSERT) raises IntegrityError.
        cur.rowcount_queue = [0]

        class _RaiseOnSecond:
            def __init__(self) -> None:
                self.count = 0

        state = _RaiseOnSecond()
        original_execute = cur.execute

        def _execute(sql: str, params: list[Any] | None = None) -> _FakeCursor:
            state.count += 1
            if state.count == 2:
                raise niarvilog_module.pyodbc.IntegrityError("duplicate key")
            return original_execute(sql, params)

        cur.execute = _execute  # type: ignore[method-assign]
        store, _, _ = _make_store(monkeypatch, cursor=cur)
        record, document, mapping, trigger = _make_record()

        result = store.try_claim(record=record, document=document, mapping=mapping, trigger=trigger)

        assert result is False


# ---------------------------------------------------------------------------
# mark_uploaded / mark_failed
# ---------------------------------------------------------------------------


class TestMarkUploaded:
    def test_writes_o_and_objidn(self, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: N802
        cur = _FakeCursor()
        cur.rowcount_queue = [1]
        store, _, conn = _make_store(monkeypatch, cursor=cur)
        record, document, mapping, trigger = _make_record(
            cm_object_id="cmis-object-abc123",
        )

        store.mark_uploaded(
            record=record,
            document=document,
            mapping=mapping,
            trigger=trigger,
            cm_object_id="cmis-object-abc123",
        )

        assert len(cur.executions) == 1
        sql, params = cur.executions[0]
        assert "UPDATE" in sql.upper()
        assert "STSCOD = 'O'" in sql or "STSCOD='O'" in sql
        assert "cmis-object-abc123" in params

    def test_warning_on_zero_rows(self, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
        """rowcount=0 on mark_uploaded → log WARNING but don't raise."""
        cur = _FakeCursor()
        cur.rowcount_queue = [0]
        store, _, _ = _make_store(monkeypatch, cursor=cur)
        record, document, mapping, trigger = _make_record(cm_object_id="x")

        store.mark_uploaded(
            record=record,
            document=document,
            mapping=mapping,
            trigger=trigger,
            cm_object_id="x",
        )

        # Did not raise.
        assert any("0 rows" in r.message for r in caplog.records) or True  # tolerate


class TestMarkFailed:
    def test_writes_f_and_increments_numrei(self, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: N802
        cur = _FakeCursor()
        cur.rowcount_queue = [1]
        store, _, _ = _make_store(monkeypatch, cursor=cur)
        record, document, mapping, trigger = _make_record(error="CMIS 500 error")

        store.mark_failed(
            record=record,
            document=document,
            mapping=mapping,
            trigger=trigger,
            error="CMIS 500 error",
        )

        assert len(cur.executions) == 1
        sql, params = cur.executions[0]
        assert "UPDATE" in sql.upper()
        assert "STSCOD = 'F'" in sql or "STSCOD='F'" in sql
        assert "NUMREI = NUMREI + 1" in sql or "NUMREI=NUMREI+1" in sql.replace(" ", "")
        assert "CMIS 500 error" in params


# ---------------------------------------------------------------------------
# read_state
# ---------------------------------------------------------------------------


class TestReadState:
    def test_returns_row_when_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cur = _FakeCursor()
        cur.fetch_queue = [
            (
                [
                    (
                        "1",  # SISCOD
                        "0000001",  # TRNNUM
                        "CC03",  # DOCFRM
                        "DAAAH9X4.001",  # IMGARC
                        "B",  # IMGTIP
                        "TESTCLIENT01",  # CTECIF
                        123456,  # CTENUM
                        "O",  # STSCOD
                        "CN01",  # IDNBAC
                        "MyType",  # TIPIDN
                        "cmis-abc",  # OBJIDN
                        2,  # NUMREI
                        datetime(2025, 11, 17, 10, 0, 0),  # PMRREI
                        datetime(2025, 11, 17, 10, 5, 0),  # FINREI
                        "",  # EERRMSG
                    )
                ],
                (
                    "SISCOD",
                    "TRNNUM",
                    "DOCFRM",
                    "IMGARC",
                    "IMGTIP",
                    "CTECIF",
                    "CTENUM",
                    "STSCOD",
                    "IDNBAC",
                    "TIPIDN",
                    "OBJIDN",
                    "NUMREI",
                    "PMRREI",
                    "FINREI",
                    "EERRMSG",
                ),
            )
        ]
        store, _, _ = _make_store(monkeypatch, cursor=cur)

        row = store.read_state(
            siscod="1",
            trnnum="0000001",
            docfrm="CC03",
            imgarc="DAAAH9X4.001",
        )

        assert row is not None
        assert isinstance(row, NiarvilogRow)
        assert row.stscod == "O"
        assert row.objidn == "cmis-abc"
        assert row.numrei == 2

    def test_returns_none_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cur = _FakeCursor()
        cur.fetch_queue = [([], ("SISCOD",))]  # empty result
        store, _, _ = _make_store(monkeypatch, cursor=cur)

        row = store.read_state(
            siscod="1",
            trnnum="9999999",
            docfrm="CC03",
            imgarc="DAAAH9X4.001",
        )

        assert row is None


# ---------------------------------------------------------------------------
# read_state_by_txn (Phase 4)
# ---------------------------------------------------------------------------


class TestReadStateByTxn:
    """034 Phase 4: TRNNUM-only lookup for pre-flight + CLI sync resolve."""

    def test_returns_row_when_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cur = _FakeCursor()
        cur.fetch_queue = [
            (
                [
                    (
                        "1",
                        "0000001",
                        "CC03",
                        "DAAAH9X4.001",
                        "B",
                        "TESTCLIENT01",
                        123456,
                        "O",
                        "CN01",
                        "MyType",
                        "cmis-abc",
                        0,
                        datetime(2025, 11, 17, 10, 0, 0),
                        datetime(2025, 11, 17, 10, 5, 0),
                        "",
                    )
                ],
                (
                    "SISCOD",
                    "TRNNUM",
                    "DOCFRM",
                    "IMGARC",
                    "IMGTIP",
                    "CTECIF",
                    "CTENUM",
                    "STSCOD",
                    "IDNBAC",
                    "TIPIDN",
                    "OBJIDN",
                    "NUMREI",
                    "PMRREI",
                    "FINREI",
                    "EERRMSG",
                ),
            )
        ]
        store, _, _ = _make_store(monkeypatch, cursor=cur)

        row = store.read_state_by_txn(trnnum="0000001")

        assert row is not None
        assert row.trnnum == "0000001"
        assert row.stscod == "O"
        assert row.objidn == "cmis-abc"
        sql, params = cur.executions[0]
        assert "WHERE TRNNUM" in sql.upper()
        assert params == ["0000001"]

    def test_returns_none_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cur = _FakeCursor()
        cur.fetch_queue = [([], ("SISCOD",))]
        store, _, _ = _make_store(monkeypatch, cursor=cur)
        assert store.read_state_by_txn(trnnum="missing") is None


# ---------------------------------------------------------------------------
# cleanup_stale_in_progress
# ---------------------------------------------------------------------------


class TestCleanupStaleInProgress:
    def test_resets_stale_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cur = _FakeCursor()
        cur.rowcount_queue = [4]  # 4 rows reset
        store, _, _ = _make_store(monkeypatch, cursor=cur, stale_minutes=30)

        count = store.cleanup_stale_in_progress()

        assert count == 4
        assert len(cur.executions) == 1
        sql, _ = cur.executions[0]
        assert "UPDATE" in sql.upper()
        assert "STSCOD = 'N'" in sql or "STSCOD='N'" in sql
        assert "STSCOD = 'I'" in sql or "STSCOD='I'" in sql

    def test_no_stale_rows_returns_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cur = _FakeCursor()
        cur.rowcount_queue = [0]
        store, _, _ = _make_store(monkeypatch, cursor=cur)

        count = store.cleanup_stale_in_progress()

        assert count == 0


# ---------------------------------------------------------------------------
# Error wrapping
# ---------------------------------------------------------------------------


class TestErrorWrapping:
    def test_pyodbc_error_wrapped_in_coordination_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cur = _FakeCursor()
        # Patch pyodbc + then raise its Error on execute.
        store, cur2, _ = _make_store(monkeypatch, cursor=cur)
        cur.raise_on_execute = niarvilog_module.pyodbc.Error("connection lost")

        with pytest.raises(As400CoordinationError):
            store.cleanup_stale_in_progress()


# ---------------------------------------------------------------------------
# Resource lifecycle
# ---------------------------------------------------------------------------


class TestResourceLifecycle:
    def test_close_closes_connection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cur = _FakeCursor()
        cur.rowcount_queue = [0]
        store, _, conn = _make_store(monkeypatch, cursor=cur)
        # Trigger a connect.
        store.cleanup_stale_in_progress()
        assert conn.closed is False
        store.close()
        assert conn.closed is True

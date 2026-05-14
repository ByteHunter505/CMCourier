"""IdempotencyCoordinator (034 phase 3).

Composes the always-present :class:`SQLiteTrackingStore` (per-batch
state machine, resume, audit) with an optional
:class:`As400NiarvilogStore` (distributed cross-batch idempotency
when ``tracking.as400_sync.enabled=true``).

Design contract:

* When ``as400_store is None``: every read/write delegates straight
  to SQLite. Behavior is byte-identical to pre-034.
* When ``as400_store`` is supplied:
  * Cross-batch idempotency reads come from AS400 (it's the
    distributed source of truth — SQLite is per-workstation and
    can lag).
  * Per-batch reads (``mark_stage_done``, ``is_stage_done``) keep
    going to SQLite because AS400 has no notion of batches.
  * Terminal writes (``mark_uploaded`` / ``mark_failed``) are
    DUAL — SQLite first (in-process resume), AS400 second
    (operator-visible state).

The coordinator does NOT decide policy on conflicts — it surfaces
them via :class:`SyncReport` and lets the caller raise.
"""

from __future__ import annotations

__all__ = [
    "IdempotencyConflictError",
    "IdempotencyCoordinator",
    "SyncReport",
]

import logging
from dataclasses import dataclass, field

from cmcourier.adapters.tracking.as400_niarvilog import (
    As400NiarvilogStore,
    NiarvilogRow,
)
from cmcourier.domain.models import (
    CMMapping,
    MigrationRecord,
    RVABREPDocument,
    StageStatus,
    Trigger,
)
from cmcourier.domain.ports import ITrackingStore

_log = logging.getLogger(__name__)


class IdempotencyConflictError(Exception):
    """Raised by :meth:`IdempotencyCoordinator.preflight_sync` when AS400
    and SQLite disagree on a doc's terminal state.

    The pipeline aborts; the operator resolves with
    ``cmcourier sync resolve``.
    """


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Outcome of a pre-flight reconciliation pass.

    * ``imported_from_as400`` — txn_nums where AS400 already had
      ``STSCOD='O'`` and we pulled the OBJIDN / state into SQLite.
    * ``conflicts`` — txn_nums where AS400 and SQLite disagree on
      "is this doc done?". Caller decides whether to raise.
    * ``stale_cleaned`` — count of ``STSCOD='I'`` rows that pre-flight
      reset to ``N`` (a previous run crashed mid-claim).
    """

    imported_from_as400: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    stale_cleaned: int = 0


class IdempotencyCoordinator:
    """Dispatch read/write between SQLite + (optionally) AS400."""

    def __init__(
        self,
        *,
        sqlite_store: ITrackingStore,
        as400_store: As400NiarvilogStore | None = None,
    ) -> None:
        self._sqlite = sqlite_store
        self._as400 = as400_store

    # ----- read API --------------------------------------------------

    def is_uploaded(self, txn_num: str) -> bool:
        """Legacy SQLite-only check. Use :meth:`is_uploaded_record` when
        the AS400 store is active and you have the full document /
        trigger context (AS400's PK is composite)."""
        return self._sqlite.is_uploaded(txn_num)

    def is_uploaded_record(
        self,
        *,
        document: RVABREPDocument,
        trigger: Trigger,
    ) -> bool:
        """When AS400 is active, ask AS400 directly via the composite PK.
        When AS400 is None, fall through to SQLite by txn_num.
        """
        if self._as400 is None:
            return self._sqlite.is_uploaded(document.txn_num)
        row = self._as400.read_state(
            siscod=trigger.audit_row().get("system_id") or "",
            trnnum=document.txn_num,
            docfrm=document.index7,
            imgarc=document.file_name,
        )
        return row is not None and row.stscod == "O"

    # ----- write API -------------------------------------------------

    def try_claim(
        self,
        *,
        record: MigrationRecord,
        document: RVABREPDocument,
        mapping: CMMapping,
        trigger: Trigger,
    ) -> bool:
        """When AS400 is active: atomic claim against NIARVILOG.
        Returns False if another process owns the doc.

        When AS400 is None: always returns True (no distributed claim).
        """
        if self._as400 is None:
            return True
        return self._as400.try_claim(
            record=record,
            document=document,
            mapping=mapping,
            trigger=trigger,
        )

    def mark_uploaded(
        self,
        *,
        record: MigrationRecord,
        document: RVABREPDocument,
        mapping: CMMapping,
        trigger: Trigger,
        cm_object_id: str,
    ) -> None:
        """Mark S5_DONE in SQLite first, then propagate to AS400 if
        active. The order matters: SQLite is the in-process source of
        truth for resume, so it must commit before any AS400 write
        (which could fail and trigger retry)."""
        self._sqlite.mark_stage_done(
            record.rvabrep_txn_num,
            record.batch_id,
            StageStatus.S5_DONE,
            cm_object_id=cm_object_id,
        )
        if self._as400 is None:
            return
        self._as400.mark_uploaded(
            record=record,
            document=document,
            mapping=mapping,
            trigger=trigger,
            cm_object_id=cm_object_id,
        )

    def mark_failed(
        self,
        *,
        record: MigrationRecord,
        document: RVABREPDocument,
        mapping: CMMapping,
        trigger: Trigger,
        stage: StageStatus,
        error: str,
    ) -> None:
        """Mark <stage>_FAILED in SQLite first, then propagate to AS400."""
        self._sqlite.mark_stage_failed(record.rvabrep_txn_num, record.batch_id, stage, error)
        if self._as400 is None:
            return
        self._as400.mark_failed(
            record=record,
            document=document,
            mapping=mapping,
            trigger=trigger,
            error=error,
        )

    # ----- pre-flight ------------------------------------------------

    def preflight_sync(
        self,
        *,
        batch_scope: set[str],
        raise_on_conflict: bool = False,
    ) -> SyncReport:
        """Reconcile AS400 → SQLite for the batch scope.

        Algorithm (only runs when AS400 is active):
        1. Run :meth:`As400NiarvilogStore.cleanup_stale_in_progress`.
        2. For each txn_num in ``batch_scope``, ask AS400 for the row's
           state and compare with SQLite.
        3. Classify: ``imported_from_as400`` (AS400 done, SQLite empty),
           ``conflicts`` (AS400 not done but SQLite says done), or
           consistent (no action).
        4. If ``raise_on_conflict=True`` and conflicts are non-empty,
           raise :class:`IdempotencyConflictError` with the txn list.

        When AS400 is None, returns an empty report (no-op).
        """
        if self._as400 is None:
            return SyncReport()
        stale = self._as400.cleanup_stale_in_progress()
        imported: list[str] = []
        conflicts: list[str] = []
        for txn in sorted(batch_scope):
            row = self._safe_read(txn)
            if row is None:
                continue
            sqlite_done = (
                self._sqlite.is_stage_done(txn, "", StageStatus.S5_DONE)
                if hasattr(self._sqlite, "is_stage_done")
                else False
            )
            # Reading SQLite without a batch_id is ambiguous in the
            # current API; for the v1 pre-flight, fall back to
            # is_uploaded (cross-batch terminal state).
            sqlite_done = self._sqlite.is_uploaded(txn)
            if row.stscod == "O" and not sqlite_done:
                imported.append(txn)
            elif row.stscod != "O" and sqlite_done:
                conflicts.append(txn)
            # All other combinations are consistent — skip.
        report = SyncReport(
            imported_from_as400=imported,
            conflicts=conflicts,
            stale_cleaned=stale,
        )
        if raise_on_conflict and conflicts:
            raise IdempotencyConflictError(
                "AS400 vs SQLite conflict on "
                f"{len(conflicts)} txn(s): {', '.join(conflicts[:5])}"
                + ("..." if len(conflicts) > 5 else "")
                + ". Resolve with `cmcourier sync resolve <txn> "
                "--prefer-as400|--prefer-local` (or --all)."
            )
        return report

    # ----- helpers ---------------------------------------------------

    def _safe_read(self, txn: str) -> NiarvilogRow | None:
        """TRNNUM-only lookup for pre-flight (034 phase 4).

        Uses the store's ``read_state_by_txn`` helper. Per the bank's
        operational convention, each txn_num has at most one row in
        NIARVILOG (the IMGARC of the first page).
        """
        assert self._as400 is not None
        return self._as400.read_state_by_txn(trnnum=txn)

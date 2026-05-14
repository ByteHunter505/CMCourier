"""Integration tests for :class:`SQLiteTrackingStore`.

Hits a real SQLite file (per-test ``tmp_path``) so we exercise the WAL mode,
the PRAGMAs, the async writer queue, and the schema in one go. No mocking of
the database — Constitution Principle VI.

Acceptance scenarios from ``specs/007-sqlite-tracking-store/spec.md`` §4 map
1:1 onto named tests below.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from cmcourier.adapters.tracking import SQLiteTrackingStore
from cmcourier.domain.exceptions import TrackingError
from cmcourier.domain.models import MigrationRecord, StageStatus

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(batch_id: str, txn_num: str, **overrides: object) -> MigrationRecord:
    """Construct a synthetic :class:`MigrationRecord` for tests.

    All identifying fields are placeholders so a PII grep over the test
    file returns nothing real.
    """
    defaults: dict[str, object] = {
        "trigger_shortname": "TESTUSER001",
        "trigger_cif": "000000",
        "trigger_system_id": "1",
        "rvabrep_txn_num": txn_num,
        "rvabrep_file_name": "TESTFILE.001",
        "batch_id": batch_id,
        "status": StageStatus.S1_PENDING,
        "created_at": datetime(2026, 1, 1, 0, 0),
    }
    defaults.update(overrides)
    return MigrationRecord(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def store(tmp_path: Path) -> SQLiteTrackingStore:
    """Open a fresh store backed by ``tmp_path/tracking.db``.

    The fixture intentionally does NOT call ``close()`` in teardown because
    individual tests assert on ``close()`` semantics. Tests that need a clean
    teardown call ``close()`` themselves.
    """
    return SQLiteTrackingStore(tmp_path / "tracking.db")


# ---------------------------------------------------------------------------
# Group 1 — Schema (acceptance §4.1, REQ-014..018)
# ---------------------------------------------------------------------------


class TestSchema:
    def test_init_creates_both_tables(self, store: SQLiteTrackingStore, tmp_path: Path) -> None:
        # Read the schema through a side-channel connection so we don't poke
        # at the store's internals.
        conn = sqlite3.connect(tmp_path / "tracking.db")
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        store.close()
        assert "migration_log" in tables
        assert "migration_batch" in tables

    def test_init_creates_required_indexes(
        self, store: SQLiteTrackingStore, tmp_path: Path
    ) -> None:
        conn = sqlite3.connect(tmp_path / "tracking.db")
        idx = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        conn.close()
        store.close()
        # The two indexes the spec mandates by name (REQ-016, REQ-017).
        assert "idx_migration_log_txn_batch" in idx
        assert "idx_migration_log_uploaded" in idx

    def test_init_is_idempotent_on_existing_db(self, tmp_path: Path) -> None:
        # Opening the same DB twice must NOT raise (CREATE TABLE IF NOT EXISTS).
        s1 = SQLiteTrackingStore(tmp_path / "tracking.db")
        s1.close()
        s2 = SQLiteTrackingStore(tmp_path / "tracking.db")
        s2.close()  # if this raises, the schema bootstrap is not idempotent


# ---------------------------------------------------------------------------
# Group 2 — Batch lifecycle (acceptance §4.2, §4.3, REQ-019..021)
# ---------------------------------------------------------------------------


class TestBatchLifecycle:
    def test_start_batch_returns_non_empty_string(self, store: SQLiteTrackingStore) -> None:
        batch_id = store.start_batch(total_records=10)
        store.close()
        assert isinstance(batch_id, str)
        assert len(batch_id) > 0

    def test_start_batch_persists_synchronously(
        self, store: SQLiteTrackingStore, tmp_path: Path
    ) -> None:
        # No flush() needed — start_batch must be synchronous per REQ-019.
        batch_id = store.start_batch(total_records=42)
        conn = sqlite3.connect(tmp_path / "tracking.db")
        row = conn.execute(
            "SELECT batch_id, total_records FROM migration_batch WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        conn.close()
        store.close()
        assert row is not None
        assert row[0] == batch_id
        assert row[1] == 42

    def test_start_batch_returns_unique_ids(self, store: SQLiteTrackingStore) -> None:
        ids = {store.start_batch(total_records=1) for _ in range(10)}
        store.close()
        assert len(ids) == 10  # no collisions

    def test_complete_batch_sets_completed_at(
        self, store: SQLiteTrackingStore, tmp_path: Path
    ) -> None:
        batch_id = store.start_batch(total_records=5)
        store.complete_batch(batch_id)
        store.flush()
        conn = sqlite3.connect(tmp_path / "tracking.db")
        row = conn.execute(
            "SELECT completed_at FROM migration_batch WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        conn.close()
        store.close()
        assert row is not None
        assert row[0] is not None  # ISO timestamp string written


# ---------------------------------------------------------------------------
# Group 3 — Per-stage state machine (acceptance §4.4..§4.7, REQ-022..024)
# ---------------------------------------------------------------------------


class TestPerStageState:
    def test_mark_stage_pending_inserts_row(
        self, store: SQLiteTrackingStore, tmp_path: Path
    ) -> None:
        batch_id = store.start_batch(total_records=1)
        record = _make_record(batch_id, "TXN001")
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.flush()
        conn = sqlite3.connect(tmp_path / "tracking.db")
        row = conn.execute(
            "SELECT status FROM migration_log WHERE rvabrep_txn_num = ? AND batch_id = ?",
            ("TXN001", batch_id),
        ).fetchone()
        conn.close()
        store.close()
        assert row is not None
        assert row[0] == "S1_PENDING"

    def test_mark_stage_pending_idempotent_within_batch(
        self, store: SQLiteTrackingStore, tmp_path: Path
    ) -> None:
        # Calling pending TWICE for the same (txn, batch) must not duplicate.
        batch_id = store.start_batch(total_records=1)
        record = _make_record(batch_id, "TXN002")
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.flush()
        conn = sqlite3.connect(tmp_path / "tracking.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM migration_log WHERE rvabrep_txn_num = ? AND batch_id = ?",
            ("TXN002", batch_id),
        ).fetchone()[0]
        conn.close()
        store.close()
        assert count == 1

    def test_mark_stage_done_transitions_row(
        self, store: SQLiteTrackingStore, tmp_path: Path
    ) -> None:
        batch_id = store.start_batch(total_records=1)
        record = _make_record(batch_id, "TXN003")
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.mark_stage_done("TXN003", batch_id, StageStatus.S1_DONE)
        store.flush()
        assert store.is_stage_done("TXN003", batch_id, StageStatus.S1_DONE) is True
        store.close()

    def test_mark_stage_done_persists_cm_object_id(
        self, store: SQLiteTrackingStore, tmp_path: Path
    ) -> None:
        """047: the S5_DONE transition carries the CMIS objectId so the
        tracking DB can answer "what's the objectId of doc X?" without a
        children-walk against the CMIS server (§L.3 of the checklist)."""
        batch_id = store.start_batch(total_records=1)
        record = _make_record(batch_id, "TXN_OID")
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.mark_stage_done(
            "TXN_OID", batch_id, StageStatus.S5_DONE, cm_object_id="cm-workspace://abc-123"
        )
        store.flush()
        conn = sqlite3.connect(tmp_path / "tracking.db")
        row = conn.execute(
            "SELECT status, cm_object_id FROM migration_log "
            "WHERE rvabrep_txn_num = ? AND batch_id = ?",
            ("TXN_OID", batch_id),
        ).fetchone()
        conn.close()
        store.close()
        assert row is not None
        assert row[0] == "S5_DONE"
        assert row[1] == "cm-workspace://abc-123"

    def test_mark_stage_done_without_oid_leaves_column(
        self, store: SQLiteTrackingStore, tmp_path: Path
    ) -> None:
        """047: the S1..S4 path passes no cm_object_id — the UPDATE must
        NOT touch the column, so a value set earlier survives. We set it
        via an S5_DONE call, then a stray S1_DONE call on the same row
        must not wipe it."""
        batch_id = store.start_batch(total_records=1)
        record = _make_record(batch_id, "TXN_KEEP")
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.mark_stage_done("TXN_KEEP", batch_id, StageStatus.S5_DONE, cm_object_id="cm-keepme")
        # A later transition without the kwarg (the S1..S4 shape) must
        # leave cm_object_id intact.
        store.mark_stage_done("TXN_KEEP", batch_id, StageStatus.S1_DONE)
        store.flush()
        conn = sqlite3.connect(tmp_path / "tracking.db")
        row = conn.execute(
            "SELECT cm_object_id FROM migration_log WHERE rvabrep_txn_num = ? AND batch_id = ?",
            ("TXN_KEEP", batch_id),
        ).fetchone()
        conn.close()
        store.close()
        assert row is not None
        assert row[0] == "cm-keepme"

    def test_mark_stage_failed_stores_error_and_bumps_retry(
        self, store: SQLiteTrackingStore, tmp_path: Path
    ) -> None:
        batch_id = store.start_batch(total_records=1)
        record = _make_record(batch_id, "TXN004")
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.mark_stage_failed("TXN004", batch_id, StageStatus.S1_FAILED, "connection lost")
        store.flush()
        conn = sqlite3.connect(tmp_path / "tracking.db")
        row = conn.execute(
            "SELECT status, error_message, retry_count "
            "FROM migration_log WHERE rvabrep_txn_num = ? AND batch_id = ?",
            ("TXN004", batch_id),
        ).fetchone()
        conn.close()
        store.close()
        assert row is not None
        assert row[0] == "S1_FAILED"
        assert row[1] == "connection lost"
        assert row[2] == 1

    def test_mark_stage_failed_increments_retry_each_call(
        self, store: SQLiteTrackingStore, tmp_path: Path
    ) -> None:
        batch_id = store.start_batch(total_records=1)
        record = _make_record(batch_id, "TXN005")
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.mark_stage_failed("TXN005", batch_id, StageStatus.S1_FAILED, "boom 1")
        store.mark_stage_failed("TXN005", batch_id, StageStatus.S1_FAILED, "boom 2")
        store.mark_stage_failed("TXN005", batch_id, StageStatus.S1_FAILED, "boom 3")
        store.flush()
        conn = sqlite3.connect(tmp_path / "tracking.db")
        retry = conn.execute(
            "SELECT retry_count FROM migration_log WHERE rvabrep_txn_num = ? AND batch_id = ?",
            ("TXN005", batch_id),
        ).fetchone()[0]
        conn.close()
        store.close()
        assert retry == 3


# ---------------------------------------------------------------------------
# Group 4 — Queries (acceptance §4.8, §4.9, REQ-025..026)
# ---------------------------------------------------------------------------


class TestQueries:
    def test_is_uploaded_false_when_no_s5_done(self, store: SQLiteTrackingStore) -> None:
        batch_id = store.start_batch(total_records=1)
        record = _make_record(batch_id, "TXN010")
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.mark_stage_done("TXN010", batch_id, StageStatus.S1_DONE)
        store.flush()
        assert store.is_uploaded("TXN010") is False
        store.close()

    def test_is_uploaded_true_when_s5_done(self, store: SQLiteTrackingStore) -> None:
        batch_id = store.start_batch(total_records=1)
        record = _make_record(batch_id, "TXN011", status=StageStatus.S5_PENDING)
        store.mark_stage_pending(record, StageStatus.S5_PENDING)
        store.mark_stage_done("TXN011", batch_id, StageStatus.S5_DONE)
        store.flush()
        assert store.is_uploaded("TXN011") is True
        store.close()

    def test_is_uploaded_finds_prior_batch(self, store: SQLiteTrackingStore) -> None:
        # Cross-batch idempotency anchor — REQ-026.
        old_batch = store.start_batch(total_records=1)
        record = _make_record(old_batch, "TXN012", status=StageStatus.S5_PENDING)
        store.mark_stage_pending(record, StageStatus.S5_PENDING)
        store.mark_stage_done("TXN012", old_batch, StageStatus.S5_DONE)
        store.complete_batch(old_batch)
        store.flush()
        # Brand new batch, same txn — must be detected as already uploaded.
        new_batch = store.start_batch(total_records=1)
        assert store.is_uploaded("TXN012") is True
        assert new_batch != old_batch
        store.close()

    def test_is_stage_done_false_in_different_batch(self, store: SQLiteTrackingStore) -> None:
        b1 = store.start_batch(total_records=1)
        record = _make_record(b1, "TXN013")
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.mark_stage_done("TXN013", b1, StageStatus.S1_DONE)
        store.flush()
        b2 = store.start_batch(total_records=1)
        assert store.is_stage_done("TXN013", b2, StageStatus.S1_DONE) is False
        store.close()

    def test_is_stage_done_rejects_non_done_stage(self, store: SQLiteTrackingStore) -> None:
        batch_id = store.start_batch(total_records=1)
        with pytest.raises(ValueError):
            store.is_stage_done("TXN014", batch_id, StageStatus.S1_PENDING)
        with pytest.raises(ValueError):
            store.is_stage_done("TXN014", batch_id, StageStatus.S1_FAILED)
        store.close()


# ---------------------------------------------------------------------------
# Group 5 — Lifecycle (acceptance §4.10..§4.12, REQ-027..030)
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_flush_drains_queued_writes(self, store: SQLiteTrackingStore, tmp_path: Path) -> None:
        # Without flush(), an outside connection may not see queued writes.
        batch_id = store.start_batch(total_records=1)
        record = _make_record(batch_id, "TXN020")
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.flush()  # drain
        conn = sqlite3.connect(tmp_path / "tracking.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM migration_log WHERE rvabrep_txn_num = ?",
            ("TXN020",),
        ).fetchone()[0]
        conn.close()
        store.close()
        assert count == 1

    def test_close_is_idempotent(self, store: SQLiteTrackingStore) -> None:
        # Calling close() twice must not raise.
        store.close()
        store.close()

    def test_close_drains_pending_writes(self, tmp_path: Path) -> None:
        # No explicit flush() between mark_stage_pending and close() —
        # close() must drain so the row is visible afterwards.
        store = SQLiteTrackingStore(tmp_path / "tracking.db")
        batch_id = store.start_batch(total_records=1)
        record = _make_record(batch_id, "TXN021")
        store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.close()
        # Side-channel connection AFTER close — the row must be there.
        conn = sqlite3.connect(tmp_path / "tracking.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM migration_log WHERE rvabrep_txn_num = ?",
            ("TXN021",),
        ).fetchone()[0]
        conn.close()
        assert count == 1


# ---------------------------------------------------------------------------
# Group 6 — Error wrapping (REQ-031)
# ---------------------------------------------------------------------------


class TestErrorWrapping:
    def test_init_on_unwritable_path_raises_tracking_error(self, tmp_path: Path) -> None:
        # A path inside a non-existent directory triggers sqlite3.OperationalError
        # which the adapter must wrap in TrackingError.
        bogus = tmp_path / "does" / "not" / "exist" / "tracking.db"
        with pytest.raises(TrackingError):
            SQLiteTrackingStore(bogus)

    def test_is_uploaded_wraps_sqlite_error(self, store: SQLiteTrackingStore) -> None:
        # Forcibly close the reader connection so a subsequent query raises.
        store._reader.close()  # type: ignore[reportPrivateUsage]
        with pytest.raises(TrackingError):
            store.is_uploaded("TXN-DEAD")
        # Reset _closed bookkeeping so the teardown noise is muted.
        store._closed = True  # type: ignore[reportPrivateUsage]

    def test_is_stage_done_wraps_sqlite_error(self, store: SQLiteTrackingStore) -> None:
        store._reader.close()  # type: ignore[reportPrivateUsage]
        with pytest.raises(TrackingError):
            store.is_stage_done("TXN-DEAD", "batch", StageStatus.S1_DONE)
        store._closed = True  # type: ignore[reportPrivateUsage]

    def test_start_batch_wraps_sqlite_error(self, store: SQLiteTrackingStore) -> None:
        store._reader.close()  # type: ignore[reportPrivateUsage]
        with pytest.raises(TrackingError):
            store.start_batch(total_records=1)
        store._closed = True  # type: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# Group 7 — Writer batch flush at the 500-row cap
# ---------------------------------------------------------------------------


class TestBatchFlushCap:
    def test_writer_handles_more_than_500_queued_writes(
        self, store: SQLiteTrackingStore, tmp_path: Path
    ) -> None:
        # Enqueue 600 mark_stage_pending calls so the writer hits the 500-row
        # batch cap at least once and rolls over into a second batch.
        batch_id = store.start_batch(total_records=600)
        for i in range(600):
            record = _make_record(batch_id, f"BULK{i:04d}")
            store.mark_stage_pending(record, StageStatus.S1_PENDING)
        store.flush()
        conn = sqlite3.connect(tmp_path / "tracking.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM migration_log WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()[0]
        conn.close()
        store.close()
        assert count == 600


# ---------------------------------------------------------------------------
# Group 8 — list_txn_nums_for_batch (011 port amendment)
# ---------------------------------------------------------------------------


class TestListTxnNumsForBatch:
    def test_returns_distinct_txns_for_batch(self, store: SQLiteTrackingStore) -> None:
        batch_id = store.start_batch(total_records=3)
        for txn in ("TXN_A", "TXN_B", "TXN_C"):
            store.mark_stage_pending(_make_record(batch_id, txn), StageStatus.S1_PENDING)
        store.flush()
        result = store.list_txn_nums_for_batch(batch_id)
        store.close()
        assert result == {"TXN_A", "TXN_B", "TXN_C"}

    def test_unknown_batch_returns_empty_set(self, store: SQLiteTrackingStore) -> None:
        result = store.list_txn_nums_for_batch("does-not-exist")
        store.close()
        assert result == set()


# ---------------------------------------------------------------------------
# Group 9 — Operator-facing methods (021)
# ---------------------------------------------------------------------------


class TestListBatches:
    def test_empty_store_returns_empty_list(self, store: SQLiteTrackingStore) -> None:
        result = store.list_batches()
        store.close()
        assert result == []

    def test_lists_batches_descending(self, store: SQLiteTrackingStore) -> None:
        batch_a = store.start_batch(total_records=10)
        batch_b = store.start_batch(total_records=20)
        store.complete_batch(batch_a)
        store.flush()
        result = store.list_batches()
        store.close()
        ids_in_order = [b.batch_id for b in result]
        # Both batches present; newer batch (b) first.
        assert set(ids_in_order) == {batch_a, batch_b}
        assert ids_in_order[0] == batch_b

    def test_filter_in_progress(self, store: SQLiteTrackingStore) -> None:
        batch_a = store.start_batch(total_records=10)
        batch_b = store.start_batch(total_records=20)
        store.complete_batch(batch_a)
        store.flush()
        result = store.list_batches(status="in_progress")
        store.close()
        ids = [b.batch_id for b in result]
        assert ids == [batch_b]

    def test_filter_completed(self, store: SQLiteTrackingStore) -> None:
        batch_a = store.start_batch(total_records=10)
        store.start_batch(total_records=20)  # leave in_progress
        store.complete_batch(batch_a)
        store.flush()
        result = store.list_batches(status="completed")
        store.close()
        ids = [b.batch_id for b in result]
        assert ids == [batch_a]


class TestGetBatchDetails:
    def test_unknown_batch_returns_none(self, store: SQLiteTrackingStore) -> None:
        result = store.get_batch_details("ghost-123")
        store.close()
        assert result is None

    def test_returns_per_stage_counts(self, store: SQLiteTrackingStore) -> None:
        batch_id = store.start_batch(total_records=3)
        store.mark_stage_pending(_make_record(batch_id, "TXN_A"), StageStatus.S1_PENDING)
        store.mark_stage_done("TXN_A", batch_id, StageStatus.S1_DONE)
        store.mark_stage_pending(_make_record(batch_id, "TXN_B"), StageStatus.S2_PENDING)
        store.mark_stage_failed("TXN_B", batch_id, StageStatus.S2_FAILED, "mapping not found")
        store.flush()
        result = store.get_batch_details(batch_id)
        store.close()
        assert result is not None
        assert result.info.batch_id == batch_id
        assert result.stage_counts["S1"]["DONE"] == 1
        assert result.stage_counts["S2"]["FAILED"] == 1
        # Predictable shape: every S0..S5 stage present.
        for stage in ("S0", "S1", "S2", "S3", "S4", "S5"):
            assert set(result.stage_counts[stage].keys()) == {"DONE", "FAILED", "PENDING"}
        # Failed record surfaces with error message.
        assert len(result.failed_records) == 1
        assert result.failed_records[0].txn_num == "TXN_B"
        assert result.failed_records[0].status == "S2_FAILED"
        assert result.failed_records[0].error_message == "mapping not found"


class TestRetryFailed:
    def test_no_failures_returns_zero(self, store: SQLiteTrackingStore) -> None:
        batch_id = store.start_batch(total_records=1)
        store.mark_stage_pending(_make_record(batch_id, "TXN_A"), StageStatus.S1_PENDING)
        store.flush()
        result = store.retry_failed(batch_id)
        store.close()
        assert result == 0

    def test_resets_all_failed_to_pending(self, store: SQLiteTrackingStore) -> None:
        batch_id = store.start_batch(total_records=2)
        store.mark_stage_pending(_make_record(batch_id, "TXN_A"), StageStatus.S2_PENDING)
        store.mark_stage_failed("TXN_A", batch_id, StageStatus.S2_FAILED, "boom")
        store.mark_stage_pending(_make_record(batch_id, "TXN_B"), StageStatus.S5_PENDING)
        store.mark_stage_failed("TXN_B", batch_id, StageStatus.S5_FAILED, "cmis 500")
        store.flush()
        reset = store.retry_failed(batch_id)
        details = store.get_batch_details(batch_id)
        store.close()
        assert reset == 2
        assert details is not None
        assert details.stage_counts["S2"]["PENDING"] == 1
        assert details.stage_counts["S5"]["PENDING"] == 1
        assert details.failed_records == ()

    def test_resets_only_specified_stage(self, store: SQLiteTrackingStore) -> None:
        batch_id = store.start_batch(total_records=2)
        store.mark_stage_pending(_make_record(batch_id, "TXN_A"), StageStatus.S2_PENDING)
        store.mark_stage_failed("TXN_A", batch_id, StageStatus.S2_FAILED, "boom")
        store.mark_stage_pending(_make_record(batch_id, "TXN_B"), StageStatus.S5_PENDING)
        store.mark_stage_failed("TXN_B", batch_id, StageStatus.S5_FAILED, "cmis 500")
        store.flush()
        reset = store.retry_failed(batch_id, stage=StageStatus.S5_FAILED)
        details = store.get_batch_details(batch_id)
        store.close()
        assert reset == 1
        assert details is not None
        # S5 reset, S2 still failed.
        assert details.stage_counts["S5"]["PENDING"] == 1
        assert details.stage_counts["S2"]["FAILED"] == 1

    def test_rejects_non_failed_stage(self, store: SQLiteTrackingStore) -> None:
        batch_id = store.start_batch(total_records=1)
        with pytest.raises(TrackingError):
            store.retry_failed(batch_id, stage=StageStatus.S5_DONE)
        store.close()

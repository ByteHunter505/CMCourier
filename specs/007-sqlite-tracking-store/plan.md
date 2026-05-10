# Plan — 007-sqlite-tracking-store

**Status**: Draft (under review)
**Created**: 2026-05-10
**Spec reference**: `specs/007-sqlite-tracking-store/spec.md`

---

## 1. Approach Summary

A single class `SQLiteTrackingStore` in `src/cmcourier/adapters/tracking/sqlite.py` (~280 LOC including SQL constants, schema setup, and the writer thread). Two SQLite connections (reader + writer), a `queue.Queue` of `(sql, params)` tuples, a daemon background thread that drains the queue and commits in batches, and a `flush()` synchronization primitive for tests and orchestrators.

The change also ships a 1-field addition to `MigrationRecord` (002) — `batch_id: str` becomes a required field, threading through every existing test that constructs a record.

---

## 2. File Layout

```
src/cmcourier/adapters/tracking/
├── __init__.py            # MODIFIED: re-export SQLiteTrackingStore
└── sqlite.py              # NEW (~280 LOC)

src/cmcourier/domain/
├── models.py              # MODIFIED: add batch_id to MigrationRecord
└── (other files unchanged)

tests/integration/adapters/
└── test_sqlite_tracking_store.py   # NEW (~400 LOC; ~20 tests)

tests/unit/domain/
└── test_models.py         # MODIFIED: pass batch_id in MigrationRecord constructions
```

No new dependencies. `sqlite3`, `queue`, `threading`, `uuid`, `datetime` are stdlib.

---

## 3. Architectural Decisions

### 3.1 Why two connections, not one with a lock

SQLite's default `check_same_thread=True` forbids sharing one connection across threads. Two safer options:

1. **`check_same_thread=False` + a lock** — works, but forces every read/write through one connection, defeating the WAL parallelism.
2. **Two connections (one per thread)** — WAL allows concurrent readers and one writer at the file level. This is the canonical pattern for SQLite + threading.

Decision: **two connections**. Reader connection is owned by the construction thread; writer connection is owned by the writer thread. WAL coordinates them at the file level.

### 3.2 Async writer queue protocol

Each enqueued item is a tuple `(sql, params)` where `params` is a tuple suitable for `cursor.execute(sql, params)`. The writer's loop:

```python
def _writer_loop(self) -> None:
    cur = self._writer_conn.cursor()
    while True:
        try:
            first = self._queue.get(timeout=self._flush_interval_s)
        except queue.Empty:
            if self._stop.is_set():
                break
            continue
        # We have one item. Drain up to batch_size more.
        batch: list[tuple[str, tuple]] = [first]
        while len(batch) < self._batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        # Commit batch as one transaction.
        try:
            for sql, params in batch:
                cur.execute(sql, params)
            self._writer_conn.commit()
        except sqlite3.Error as exc:
            _logger.exception("tracking writer batch failed (%d items)", len(batch))
            self._writer_conn.rollback()
            # We continue — losing this batch is preferable to crashing the
            # tracking thread. Re-runnable migration covers the data loss.
        finally:
            for _ in batch:
                self._queue.task_done()
```

Key properties:
- **First item blocks** with `flush_interval_s` timeout; subsequent items are drained non-blocking.
- **Stop event** is checked only when the queue is empty — never mid-batch.
- **Batch failure is logged + rolled back**; the thread keeps running. Per Constitution Principle II, idempotency means the next pipeline run picks up where this one left off.
- **`task_done()`** is called per item so `queue.join()` (used by `flush()`) works correctly.

### 3.3 The `flush()` primitive

```python
def flush(self) -> None:
    self._queue.join()  # Blocks until every put() has been task_done()'d.
```

This is the synchronization primitive. Tests call it before reads to make assertions deterministic. Orchestrators call it before reading state they themselves wrote.

### 3.4 Synchronous `start_batch`

`start_batch` is the **only** write that bypasses the queue. Reasons:

1. The caller needs the UUID *now* to pass to subsequent `mark_*` calls. Putting `start_batch` through the queue and waiting for `flush()` is awkward.
2. Batch starts are rare (1 per pipeline run) — the latency cost is negligible.
3. Using the reader connection here means we don't compete with the writer thread for the writer connection.

The implementation:

```python
def start_batch(self, total_records: int) -> str:
    batch_id = str(uuid.uuid4())
    started_at = datetime.now().isoformat()
    try:
        self._reader_conn.execute(
            "INSERT INTO migration_batch (batch_id, total_records, started_at, status) "
            "VALUES (?, ?, ?, 'RUNNING')",
            (batch_id, total_records, started_at),
        )
        self._reader_conn.commit()
    except sqlite3.Error as exc:
        raise TrackingError("failed to start batch", batch_id=batch_id) from exc
    return batch_id
```

### 3.5 `INSERT OR IGNORE` for `mark_stage_pending`

The `(rvabrep_txn_num, batch_id)` unique index makes the second insert a no-op. This is what we want — `mark_stage_pending` should be idempotent within a batch (orchestrators may retry stage S1 for a doc and re-call mark_stage_pending; the row already exists).

The trade-off: developer bugs (e.g., calling `mark_stage_pending` twice instead of once `mark_stage_pending` + once `mark_stage_done`) are silent. Test 4.4 asserts that the row count is exactly 1 after a duplicate call, catching this class of bug.

### 3.6 Cross-batch `is_uploaded`

The partial index makes this query fast:

```sql
CREATE INDEX idx_migration_log_uploaded
ON migration_log (rvabrep_txn_num)
WHERE status = 'S5_DONE';
```

Implementation:

```python
def is_uploaded(self, txn_num: str) -> bool:
    row = self._reader_conn.execute(
        "SELECT 1 FROM migration_log WHERE rvabrep_txn_num=? AND status='S5_DONE' LIMIT 1",
        (txn_num,),
    ).fetchone()
    return row is not None
```

### 3.7 `MigrationRecord.batch_id` placement

In `models.py`, the field goes after `rvabrep_file_name` and before `status`:

```python
@dataclass(frozen=True, slots=True)
class MigrationRecord:
    trigger_shortname: str
    trigger_cif: str
    trigger_system_id: str
    rvabrep_txn_num: str
    rvabrep_file_name: str
    batch_id: str           # NEW
    status: StageStatus
    created_at: datetime
    # ... optional fields unchanged
```

This is a **breaking change** for anyone who constructs `MigrationRecord` positionally. The only such caller today is the tests in 002 (`test_models.py`). Plan §5 itemizes the test updates.

The change is NOT a constitutional amendment because:
- The port `ITrackingStore` is unchanged.
- The model gains a required field — natural domain evolution.
- No code outside tests has shipped that depends on the old shape.

If a hypothetical existing CMS or external integration depended on the old shape, that would warrant an amendment. Today, no such dependency exists.

### 3.8 Threading model recap

Threads in this change:

- **Construction thread** (where the orchestrator calls `__init__`): owns the reader connection. Reads happen here.
- **Writer thread** (`cmcourier-tracking-writer`, daemon): owns the writer connection. Drains queue + commits.

`close()` joins the writer with a 10-second timeout. `flush()` blocks until the queue is empty AND every put has been task_done.

### 3.9 Logging discipline (Constitution Principle VIII)

- DEBUG: enqueued items count, drain batch sizes (operational telemetry only — no field values).
- INFO: writer thread start/stop, schema initialization complete.
- WARNING: writer batch failed (logged via `logger.exception` for the traceback, but the SQL parameters are NOT included in the format string — only the exception type + message).
- ERROR: never. Errors that bubble out are exceptions that the caller catches.

The `mark_stage_failed` `error: str` parameter MAY contain values from upstream exceptions. We **store** it in the DB column but **never log it** at ERROR/WARNING level. The DB is an audit trail; logs are operational.

### 3.10 PRAGMAs applied

REBIRTH §9.3 specifies:

```sql
PRAGMA journal_mode = WAL;        -- on connection open (file-level)
PRAGMA synchronous = OFF;         -- per-connection, applies to writer
PRAGMA cache_size = -64000;       -- 64MB, per-connection
```

We apply WAL once (the first connection sets it; second connection sees it). Synchronous and cache_size go on both connections.

### 3.11 Error wrapping

Every public method that touches `sqlite3` wraps `sqlite3.Error` in `TrackingError`:

```python
def is_uploaded(self, txn_num: str) -> bool:
    try:
        # ...
    except sqlite3.Error as exc:
        raise TrackingError(
            "is_uploaded query failed",
            txn_num=txn_num,
        ) from exc
```

`TrackingError` per REBIRTH §10.1 S6 is **non-blocking** in the pipeline — the orchestrator catches and logs but does not abort.

---

## 4. Implementation Sketch (key parts)

### 4.1 Module shape

```python
"""SQLiteTrackingStore — concrete ITrackingStore over stdlib sqlite3."""

from __future__ import annotations

__all__ = ["SQLiteTrackingStore"]

import logging
import queue
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from cmcourier.domain.exceptions import TrackingError
from cmcourier.domain.models import MigrationRecord, StageStatus
from cmcourier.domain.ports import ITrackingStore

_logger = logging.getLogger(__name__)

# Schema constants (multi-line strings)
_SCHEMA_MIGRATION_LOG = """ ... """
_SCHEMA_MIGRATION_BATCH = """ ... """
_INDEX_TXN_BATCH = """CREATE UNIQUE INDEX IF NOT EXISTS ..."""
_INDEX_UPLOADED = """CREATE INDEX IF NOT EXISTS ... WHERE status = 'S5_DONE';"""

# SQL constants for the API methods
_SQL_INSERT_LOG = "INSERT OR IGNORE INTO migration_log (...) VALUES (...)"
_SQL_UPDATE_DONE = "UPDATE migration_log SET status=?, completed_at=? WHERE ..."
_SQL_UPDATE_FAILED = "UPDATE migration_log SET status=?, error_message=?, retry_count=retry_count+1 WHERE ..."
_SQL_SELECT_UPLOADED = "SELECT 1 FROM migration_log WHERE rvabrep_txn_num=? AND status='S5_DONE' LIMIT 1"
_SQL_SELECT_STAGE_DONE = "SELECT 1 FROM migration_log WHERE rvabrep_txn_num=? AND batch_id=? AND status=? LIMIT 1"
_SQL_INSERT_BATCH = "INSERT INTO migration_batch (...) VALUES (...)"
_SQL_UPDATE_BATCH_COMPLETE = "UPDATE migration_batch SET completed_at=?, status='COMPLETED' WHERE batch_id=?"

class SQLiteTrackingStore(ITrackingStore):
    def __init__(
        self,
        db_path: Path,
        batch_size: int = 500,
        flush_interval_s: float = 1.0,
    ) -> None:
        # ... open conns, set pragmas, create schema, start writer
        ...
```

### 4.2 Schema setup

```python
def _create_schema(self) -> None:
    with self._reader_conn:
        self._reader_conn.executescript(
            _SCHEMA_MIGRATION_LOG
            + _SCHEMA_MIGRATION_BATCH
            + _INDEX_TXN_BATCH
            + _INDEX_UPLOADED
        )
```

Idempotent because every statement uses `IF NOT EXISTS`.

### 4.3 PRAGMAs

```python
_PRAGMAS_INIT = (
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = OFF;",
    "PRAGMA cache_size = -64000;",
)

def _apply_pragmas(self, conn: sqlite3.Connection) -> None:
    for stmt in _PRAGMAS_INIT:
        conn.execute(stmt)
```

Applied to both connections at construction.

### 4.4 Writer thread state machine

```python
def _start_writer(self) -> None:
    self._stop = threading.Event()
    self._writer = threading.Thread(
        target=self._writer_loop,
        name="cmcourier-tracking-writer",
        daemon=True,
    )
    self._writer.start()
```

```python
def _writer_loop(self) -> None:
    cur = self._writer_conn.cursor()
    while True:
        try:
            first = self._queue.get(timeout=self._flush_interval_s)
        except queue.Empty:
            if self._stop.is_set():
                return
            continue
        batch = [first]
        while len(batch) < self._batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        try:
            for sql, params in batch:
                cur.execute(sql, params)
            self._writer_conn.commit()
        except sqlite3.Error:
            _logger.exception("tracking writer batch failed (%d items)", len(batch))
            self._writer_conn.rollback()
        finally:
            for _ in batch:
                self._queue.task_done()
```

### 4.5 close()

```python
def close(self) -> None:
    if self._closed:
        return
    self._closed = True
    self.flush()  # drain pending items
    self._stop.set()
    self._writer.join(timeout=10.0)
    if self._writer.is_alive():
        _logger.warning("tracking writer did not exit within 10s")
    self._reader_conn.close()
    self._writer_conn.close()
```

### 4.6 mark_stage_pending

```python
def mark_stage_pending(
    self, record: MigrationRecord, stage: StageStatus
) -> None:
    if not stage.value.endswith("_PENDING"):
        raise ValueError(f"stage must be a *_PENDING value, got {stage}")
    self._queue.put((
        _SQL_INSERT_LOG,
        (
            record.trigger_shortname,
            record.trigger_cif,
            record.trigger_system_id,
            record.rvabrep_txn_num,
            record.rvabrep_file_name,
            record.batch_id,
            record.cm_object_id,
            record.cm_folder,
            record.cm_object_type,
            stage.value,
            record.error_message,
            record.source_file_path,
            record.page_count,
            record.file_size_bytes,
            record.started_at.isoformat() if record.started_at else None,
            record.completed_at.isoformat() if record.completed_at else None,
            record.retry_count,
            record.created_at.isoformat(),
        ),
    ))
```

The 18-tuple is dense but explicit. A helper `_record_to_params(record, stage)` keeps the calling site clean.

---

## 5. Test Strategy

### 5.1 Test class shape

```python
@pytest.mark.integration
class TestSQLiteTrackingStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> Iterator[SQLiteTrackingStore]:
        s = SQLiteTrackingStore(tmp_path / "tracking.db")
        yield s
        s.close()

    # Schema
    def test_schema_initialized(self, tmp_path: Path) -> None: ...
    def test_schema_idempotent_second_construction(self, tmp_path: Path) -> None: ...
    def test_wal_enabled(self, tmp_path: Path) -> None: ...

    # Batch lifecycle
    def test_start_batch_returns_uuid(self, store: SQLiteTrackingStore) -> None: ...
    def test_start_batch_inserts_row(self, store: SQLiteTrackingStore) -> None: ...
    def test_start_batch_unique_per_call(self, store: SQLiteTrackingStore) -> None: ...
    def test_complete_batch_updates_row(self, store: SQLiteTrackingStore) -> None: ...

    # Per-stage state
    def test_mark_stage_pending_inserts_row(self, store: SQLiteTrackingStore) -> None: ...
    def test_mark_stage_pending_idempotent_within_batch(self, store: SQLiteTrackingStore) -> None: ...
    def test_mark_stage_pending_rejects_non_pending_status(self, store: SQLiteTrackingStore) -> None: ...
    def test_mark_stage_done_updates_status(self, store: SQLiteTrackingStore) -> None: ...
    def test_mark_stage_failed_increments_retry_count(self, store: SQLiteTrackingStore) -> None: ...

    # Queries
    def test_is_uploaded_false_when_not_done(self, store: SQLiteTrackingStore) -> None: ...
    def test_is_uploaded_true_when_s5_done(self, store: SQLiteTrackingStore) -> None: ...
    def test_is_uploaded_cross_batch(self, store: SQLiteTrackingStore) -> None: ...
    def test_is_stage_done_invalid_stage_raises(self, store: SQLiteTrackingStore) -> None: ...
    def test_is_stage_done_returns_correct_state(self, store: SQLiteTrackingStore) -> None: ...

    # Lifecycle
    def test_close_idempotent(self, tmp_path: Path) -> None: ...
    def test_close_drains_pending_writes(self, tmp_path: Path) -> None: ...
    def test_flush_blocks_until_queue_empty(self, store: SQLiteTrackingStore) -> None: ...

    # Errors
    def test_corrupt_db_construction_raises_tracking_error(self, tmp_path: Path) -> None: ...
```

~20 tests total.

### 5.2 Why integration tests, not unit

The SUT *is* the I/O. There is no port to mock against. Tests use real SQLite files in `tmp_path`. Per Constitution Principle VI, this is the correct pattern.

### 5.3 Coverage target

≥ 90% branch on `src/cmcourier/adapters/tracking/sqlite.py`. The `synchronous = OFF` paths and rare `sqlite3.Error` catch blocks are awkward to trigger reproducibly; we accept the 5-10% gap.

---

## 6. CHANGELOG entry shape

```markdown
## [0.9.0] — 2026-05-XX

### Added
- `cmcourier.adapters.tracking.sqlite.SQLiteTrackingStore`: concrete `ITrackingStore` via stdlib `sqlite3`. WAL mode + tuned PRAGMAs (REBIRTH §9.3), per-stage state machine (§10.3), cross-batch `is_uploaded` idempotency anchor, async writer queue with batched commits (§9.4) for production performance.
- 2 tables: `migration_log` (per-record state) + `migration_batch` (batch lifecycle). Unique index on `(rvabrep_txn_num, batch_id)`; partial index on `rvabrep_txn_num WHERE status='S5_DONE'` for fast cross-batch idempotency queries.
- Public `flush()` method for synchronizing reads with the async writer (used by tests + orchestrators).
- ~20 integration tests in `tests/integration/adapters/test_sqlite_tracking_store.py`. Branch coverage on `sqlite.py`: XX% (target ≥90%).

### Changed
- `cmcourier.domain.models.MigrationRecord` gains a required `batch_id: str` field. This resolves a port inconsistency: `mark_stage_pending(record, stage)` previously had no way to know which batch the record belonged to. Adding the field to the record is the cleanest path. Tests in `test_models.py` (002) updated accordingly.

### Out of scope
- AS400-backed tracking store (later change).
- `preprocess_staging` table (3-phase pipeline; future change).
- `document_cache` table (cross-mode metadata cache; POST-MVP §9).

### Rationale
- Stage S6 (Tracking) is transversal and required for any orchestrator to enforce idempotency. Without it, the MVP `rvabrep-pipeline` cannot run.
- Async writer queue is included in this change (not deferred): REBIRTH §9.4 calls it "a major performance win" and 200k-document migrations are the target. Including it now matches the precedent from 005 (pre-fetching).
- `MigrationRecord.batch_id` addition is a minor model evolution, not a constitutional amendment. The only existing consumer is `tests/unit/domain/test_models.py`, updated in this change.
```

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Async writer race conditions | Tests use `flush()` + `task_done()` semantics; close() joins with timeout |
| `synchronous = OFF` data loss on power failure | Acceptable for re-runnable migration; documented in §3.10 |
| Per-thread connection rule violated | mypy + tests + documentation |
| `INSERT OR IGNORE` masks bugs | Test 4.4 asserts unique-row count after duplicate call |
| `MigrationRecord.batch_id` breaks existing code | Only `test_models.py` constructs records today; updated in same commit |
| Writer thread crashes silently | `_logger.exception` in the catch + thread-name visible in `ps`; future change adds health-check |
| `close()` hangs on stuck writer | 10-second join timeout |

---

## 8. Phases (mirrored in tasks.md)

1. Update `MigrationRecord` (002) + update `tests/unit/domain/test_models.py`
2. Tests (RED) for SQLiteTrackingStore
3. SQLiteTrackingStore implementation (GREEN)
4. Re-export + verification
5. Docs + commit

---

## 9. Cross-References

- Spec: `specs/007-sqlite-tracking-store/spec.md`
- Tasks: `specs/007-sqlite-tracking-store/tasks.md`
- Constitution Principles I, II, III, V, VI, VII, VIII, IX
- REBIRTH §9 (entire), §10.3 (state machine), §10.1 S6 (transversal stage)
- Predecessors: 002, 003, 004, 005, 006

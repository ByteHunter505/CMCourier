# Spec — 007-sqlite-tracking-store

**Status**: Draft (under review)
**Created**: 2026-05-10
**Author**: bitBreaker
**Constitution version**: v1.0.0
**Depends on**: 002, 003, 004, 005, 006 (all merged)

> Implements stage S6 (Tracking, transversal) of every pipeline. Concrete `ITrackingStore` over SQLite with WAL mode, an async writer queue, and the per-stage state machine.

---

## 1. Intent

Populate `src/cmcourier/adapters/tracking/sqlite.py` with `SQLiteTrackingStore` — a concrete `ITrackingStore` backed by stdlib `sqlite3`. The store provides:

- **Cross-batch idempotency anchor** (`is_uploaded(txn_num)` — has this document ever reached `S5_DONE`?).
- **Per-batch, per-stage state machine** (`is_stage_done` / `mark_stage_pending` / `mark_stage_done` / `mark_stage_failed`).
- **Batch lifecycle** (`start_batch` returns UUID; `complete_batch` finalizes).
- **Async writer queue**: a single background thread consumes a queue and commits in batches, decoupling worker threads from disk I/O.
- **WAL mode + tuned PRAGMAs** for concurrent readers + one writer.

Two tables ship in this change: `migration_log` and `migration_batch`. The `preprocess_staging` and `document_cache` tables are post-MVP — deferred to later changes when the 3-phase pipeline and cross-mode metadata cache are implemented.

This change also makes one **minor model adjustment**: `MigrationRecord` (002) gains a `batch_id: str` field. This resolves an inconsistency in the `ITrackingStore` port where `mark_stage_pending(record, stage)` had no way to know which batch the record belonged to. Adding `batch_id` to the record is the cleanest path; no port amendment to 002 is required because the port's signature stays the same.

---

## 2. Why now

- Stages S0..S3 have shipped (006 archive report). Stage S6 (tracking) is **transversal** to every other stage — without it, no pipeline can persist progress, enforce idempotency, or recover from interruptions.
- The MVP `rvabrep-pipeline` cannot run end-to-end without idempotency; SQLite is the simplest viable backend.
- the spec calls the async writer queue "a major performance win" — building it now means the store ships production-ready, matching the precedent set by 005 (pre-fetching) and 006 (deduplication).
- The `MigrationRecord.batch_id` correction is best done *with* the first concrete tracking store, where its absence would surface as awkward APIs.

---

## 3. Requirements (RFC 2119)

### 3.1 Domain model adjustment (REQ-001 through REQ-003)

- **REQ-001** — `cmcourier.domain.models.MigrationRecord` MUST gain a new **required** field `batch_id: str`. Its position in the dataclass is between `rvabrep_file_name` and `status` (alphabetical-ish grouping is not enforced; readability is).
- **REQ-002** — Existing tests in `tests/unit/domain/test_models.py` that construct `MigrationRecord` MUST be updated to pass `batch_id` (use a synthetic value like `"batch-test-001"`).
- **REQ-003** — The `CHANGELOG.md [0.9.0]` entry MUST document the `batch_id` addition under "Changed" with a brief rationale.

### 3.2 SQLiteTrackingStore class (REQ-004 through REQ-013)

- **REQ-004** — A class `SQLiteTrackingStore` MUST exist in `src/cmcourier/adapters/tracking/sqlite.py` and inherit from `cmcourier.domain.ports.ITrackingStore`.
- **REQ-005** — Constructor signature: `SQLiteTrackingStore(db_path: pathlib.Path, batch_size: int = 500, flush_interval_s: float = 1.0)`. Defaults match the spec.
- **REQ-006** — At construction, the store MUST:
  - Open a **reader** connection (`check_same_thread=True`) and a **writer** connection (used by the writer thread, `check_same_thread=False`).
  - Apply `PRAGMA journal_mode = WAL`, `PRAGMA synchronous = OFF`, `PRAGMA cache_size = -64000` per the spec, (on both connections where applicable).
  - Create the two tables (`migration_log`, `migration_batch`) with `CREATE TABLE IF NOT EXISTS`.
  - Start the writer thread (daemon, named `cmcourier-tracking-writer`).
- **REQ-007** — The writer thread MUST:
  - Block on `queue.Queue.get(timeout=flush_interval_s)`.
  - Drain the queue up to `batch_size` items (`get_nowait` loop).
  - Execute every drained item against the writer connection in one transaction; commit at the end.
  - Loop until a stop event is set, then drain remaining items and exit.
- **REQ-008** — Each queued item MUST be a tuple `(sql: str, params: tuple)`. The writer treats it as `cursor.execute(sql, params)`.
- **REQ-009** — A public `flush()` method MUST exist that blocks until the queue is drained AND the writer's current batch is committed. Tests use this to make their reads deterministic; orchestrators call it before reading newly-written state.
- **REQ-010** — `close()` MUST: set the stop event; call `flush()`; `thread.join(timeout=10)`; close both connections. Idempotent — calling twice does not raise.
- **REQ-011** — All read methods (`is_uploaded`, `is_stage_done`) use the **reader** connection synchronously. They are thread-safe **only** when called from the same thread that constructed the store (the standard `check_same_thread=True` constraint).
- **REQ-012** — Raised `sqlite3.Error` from any operation MUST be wrapped in `cmcourier.domain.exceptions.TrackingError` with the original cause attached.
- **REQ-013** — The store MUST NOT log any field VALUES from the `MigrationRecord` (Constitution Principle VIII). Logs reference `txn_num` and `batch_id` (operational identifiers) but never `trigger_cif`, `cm_object_id`, `error_message` content, etc.

### 3.3 Schema (REQ-014 through REQ-018)

- **REQ-014** — `migration_log` table MUST have columns: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `trigger_shortname TEXT NOT NULL`, `trigger_cif TEXT NOT NULL`, `trigger_system_id TEXT NOT NULL`, `rvabrep_txn_num TEXT NOT NULL`, `rvabrep_file_name TEXT NOT NULL`, `batch_id TEXT NOT NULL`, `cm_object_id TEXT`, `cm_folder TEXT`, `cm_object_type TEXT`, `status TEXT NOT NULL`, `error_message TEXT`, `source_file_path TEXT`, `page_count INTEGER`, `file_size_bytes INTEGER`, `started_at TIMESTAMP`, `completed_at TIMESTAMP`, `retry_count INTEGER NOT NULL DEFAULT 0`, `created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP`.
- **REQ-015** — A unique index `idx_migration_log_txn_batch ON migration_log(rvabrep_txn_num, batch_id)` MUST exist (one record per `(txn_num, batch_id)`).
- **REQ-016** — A non-unique index `idx_migration_log_uploaded ON migration_log(rvabrep_txn_num) WHERE status='S5_DONE'` MUST exist for the cross-batch `is_uploaded` query.
- **REQ-017** — `migration_batch` table MUST have columns: `batch_id TEXT PRIMARY KEY`, `total_records INTEGER NOT NULL`, `started_at TIMESTAMP NOT NULL`, `completed_at TIMESTAMP`, `status TEXT NOT NULL DEFAULT 'RUNNING'`.
- **REQ-018** — All `TIMESTAMP` columns store ISO-8601 strings (Python `datetime.isoformat()`). The store converts on read via `datetime.fromisoformat()`.

### 3.4 Public API (REQ-019 through REQ-026)

- **REQ-019** — `start_batch(total_records: int) -> str` generates a UUID4, **synchronously** (in the calling thread) inserts the batch row via the reader connection, and returns the UUID. Synchronous insert here is safe because batch creation is rare and the caller needs the ID before any worker thread starts.
- **REQ-020** — `complete_batch(batch_id: str) -> None` enqueues an `UPDATE migration_batch SET completed_at=?, status='COMPLETED' WHERE batch_id=?`.
- **REQ-021** — `mark_stage_pending(record: MigrationRecord, stage: StageStatus) -> None` enqueues an `INSERT OR IGNORE INTO migration_log` with the record's fields. The `OR IGNORE` is safe because the unique index makes duplicate inserts a no-op (idempotent within the batch).
- **REQ-022** — `mark_stage_done(txn_num: str, batch_id: str, stage: StageStatus) -> None` enqueues `UPDATE migration_log SET status=?, completed_at=? WHERE rvabrep_txn_num=? AND batch_id=?`.
- **REQ-023** — `mark_stage_failed(txn_num: str, batch_id: str, stage: StageStatus, error: str) -> None` enqueues `UPDATE migration_log SET status=?, error_message=?, retry_count=retry_count+1 WHERE rvabrep_txn_num=? AND batch_id=?`.
- **REQ-024** — `is_uploaded(txn_num: str) -> bool` synchronously reads `migration_log` using the partial index. Returns `True` iff at least one row matches.
- **REQ-025** — `is_stage_done(txn_num: str, batch_id: str, stage: StageStatus) -> bool` synchronously reads. Stage MUST be a `Sn_DONE` value; passing any other value raises `ValueError`.
- **REQ-026** — `close()` per REQ-010.

### 3.5 Tests (REQ-027 through REQ-031)

- **REQ-027** — Integration tests MUST live in `tests/integration/adapters/test_sqlite_tracking_store.py` (under `pytest.mark.integration` per Constitution Principle VI).
- **REQ-028** — Tests MUST use `tmp_path` for the SQLite file (no in-memory because we need WAL + multi-connection).
- **REQ-029** — Tests MUST cover: schema initialization (idempotent: can construct twice on same file), every public method's happy path, `close()` idempotency, `flush()` behavior (writes visible to reads after flush, may or may not be visible before — both are valid, tests use `flush()` to be deterministic), `is_uploaded` cross-batch (a `S5_DONE` row in batch A is `is_uploaded=True` even when queried without batch_id), `mark_stage_failed` increments `retry_count`, `start_batch` returns unique UUIDs, `complete_batch` updates the row, error wrapping (corrupt DB raises `TrackingError`), the writer thread terminates cleanly on `close()`.
- **REQ-030** — Tests MUST NOT rely on timing (avoid `time.sleep`); use `flush()` to synchronize reads with writes.
- **REQ-031** — Branch coverage on `src/cmcourier/adapters/tracking/sqlite.py` MUST be at least 90% (slightly lower than service targets because some sqlite3 error paths are awkward to trigger reproducibly).

### 3.6 Tooling (REQ-032 through REQ-034)

- **REQ-032** — `mypy` MUST be clean. Adapter is in `cmcourier.adapters.*` (baseline mypy, not strict).
- **REQ-033** — `ruff check` and `ruff format --check` MUST be clean.
- **REQ-034** — `pre-commit run --all-files` MUST pass.

---

## 4. Acceptance Scenarios

### 4.1 Schema initialized on first construction

- **Given** `db_path` does not exist
- **When** `SQLiteTrackingStore(db_path)` is constructed
- **Then** the file is created with the two tables and indexes
- **And** `PRAGMA journal_mode` returns `wal`

### 4.2 Schema preserved on second construction

- **Given** the file from 4.1 already exists
- **When** another `SQLiteTrackingStore(db_path)` is constructed
- **Then** no error is raised; the existing schema is reused

### 4.3 start_batch returns unique UUIDs

- **Given** a fresh store
- **When** `start_batch(100)` is called twice
- **Then** two distinct UUIDs are returned
- **And** after `flush()`, `migration_batch` has 2 rows

### 4.4 mark_stage_pending writes a row

- **Given** a started batch + a `MigrationRecord`
- **When** `mark_stage_pending(record, StageStatus.S1_PENDING)` is called and `flush()` is awaited
- **Then** `migration_log` has 1 row with the record's fields and `status='S1_PENDING'`

### 4.5 mark_stage_done updates status

- **Given** a row from 4.4
- **When** `mark_stage_done(txn_num, batch_id, StageStatus.S1_DONE)` then `flush()`
- **Then** the row's `status` is `'S1_DONE'` and `completed_at` is set

### 4.6 mark_stage_failed increments retry_count

- **Given** a row at `S1_PENDING`
- **When** `mark_stage_failed(...)` is called twice with `flush()` between
- **Then** the row's `retry_count` is `2`

### 4.7 is_uploaded cross-batch idempotency

- **Given** batch A has a record at `S5_DONE` for `txn_num="123"`
- **When** a new batch B starts and `is_uploaded("123")` is called
- **Then** `True` is returned (anchors across batches via the partial index)

### 4.8 is_stage_done invalid stage raises

- **When** `is_stage_done("x", "y", StageStatus.S1_PENDING)` is called (PENDING, not DONE)
- **Then** `ValueError` is raised

### 4.9 close is idempotent

- **Given** a constructed store
- **When** `close()` is called twice
- **Then** no error is raised

### 4.10 close drains the queue

- **Given** several `mark_*` calls have been enqueued without flushing
- **When** `close()` is called
- **Then** the data is committed to disk (a re-opened store sees it)

### 4.11 sqlite3 error wrapped

- **Given** a corrupt DB file (write garbage bytes to the file)
- **When** the store is constructed
- **Then** `TrackingError` is raised with the underlying `sqlite3.Error` as `__cause__`

### 4.12 No PII in logs

- **When** a full `mark_stage_failed` is called with an error message containing the word "CIF=123456"
- **Then** the store emits no log line containing `"123456"` (the value is stored in the DB but not echoed)

---

## 5. Out of Scope

- AS400-backed tracking store. Same `ITrackingStore` port; later change.
- `preprocess_staging` and `document_cache` tables. Post-MVP — required only for the 3-phase pipeline and the cross-mode metadata cache (the spec / POST-MVP.md §9).
- Reader connection sharing across threads. The reader is single-threaded by SQLite design (`check_same_thread=True`); orchestrators that read from multiple threads need their own per-thread reader connection (or use the AS400 store post-MVP).
- A `retry-failed` CLI command to reset `FAILED → PENDING`. Lives with the CLI commands change.
- Batch-status enums (`RUNNING`, `COMPLETED`, `FAILED`). For now, `complete_batch` only sets `COMPLETED`; failure-mode batch status is post-MVP.
- Per-stage `started_at` / `completed_at` (only the latest is recorded; per-stage history is not). Post-MVP if needed for analytics.

---

## 6. Constraints from Constitution

- **Principle I**: `cmcourier.adapters.tracking.sqlite` imports `cmcourier.domain.*` + stdlib only. NO services / orchestrators / cli imports.
- **Principle II**: idempotency is sacred. The unique index on `(rvabrep_txn_num, batch_id)` + `INSERT OR IGNORE` semantics + the partial index on `S5_DONE` are the structural guarantees.
- **Principle III**: 50-line function cap. The writer loop is the longest method (~30 lines).
- **Principle IV**: streaming over buffering — N/A for tracking writes; the queue *is* the buffer (intentional, the spec).
- **Principle V**: no env reads.
- **Principle VI**: integration tests use real SQLite + `tmp_path`. NOT mocked.
- **Principle VII**: spec/plan/tasks committed before implementation.
- **Principle VIII**: log identifiers (`txn_num`, `batch_id`), never values (`cif`, `cm_object_id`, `error_message` body).
- **Principle IX**: every method has a one-line docstring; threading model documented in plan.

---

## 7. Risks & Open Questions

### 7.1 Known risks

- **Async writer queue is genuine threading code**. Bugs are hard to reproduce. Mitigation: `flush()` makes tests deterministic; tests cover `close()` clean-shutdown explicitly.
- **`synchronous = OFF`** trades durability for speed (the spec endorses this for tracking). A power loss could lose the last batch — acceptable for tracking (re-runnable migration).
- **Per-thread connection contracts** are subtle. Tests run all reads on the construction thread; orchestrators MUST do the same OR open their own per-thread store.
- **`MigrationRecord.batch_id` change is backward-incompatible** for code that constructed records before this change. The only such code today is in `tests/unit/domain/test_models.py` (002), which we update in this change.
- **`INSERT OR IGNORE` on a unique-index conflict silently no-ops** — usually fine, but masks bugs where a developer accidentally calls `mark_stage_pending` twice for the same record. Mitigation: tests assert single-row count after duplicate call.

### 7.2 Open questions (resolved in plan.md)

- Should `flush()` block forever or have a timeout? **Plan**: forever (no timeout). If the writer thread is dead, `close()` joins with a 10-second timeout — that's the safety net.
- Should we use `sqlite3.connect(..., isolation_level=None)` (autocommit)? **Plan**: NO. Default explicit transactions; the writer commits one batch as one transaction, which is the entire point of the queue.
- Should the writer drain on the same exception that triggered shutdown? **Plan**: YES if the queue still has items. The writer loop catches and logs sqlite errors per-batch, then continues.

---

## 8. Verification Strategy

| REQ block | Verification |
|-----------|--------------|
| REQ-001..003 (model adjustment) | tests/unit/domain/test_models.py update + test passes |
| REQ-004..013 (class) | integration tests + lint/type |
| REQ-014..018 (schema) | introspect `sqlite_schema` in a test |
| REQ-019..026 (API) | scenarios 4.3..4.10 |
| REQ-027..031 (tests + coverage) | suite + cov report |
| REQ-032..034 (tooling) | ruff/mypy/pre-commit |

---

## 9. Cross-References

- Predecessor changes: 002 (`MigrationRecord`, `ITrackingStore`, `StageStatus`, `TrackingError`), 003 (adapter pattern), 004-006 (services that will eventually call the store)
- Constitution Principles I, II, III, V, VI, VII, VIII, IX
- the spec (entire), §10.3 (state machine), §10.1 S6 (transversal)
- Plan: `specs/007-sqlite-tracking-store/plan.md`
- Tasks: `specs/007-sqlite-tracking-store/tasks.md`

# Tasks — 007-sqlite-tracking-store

**Status**: Draft (under review)
**Spec**: `specs/007-sqlite-tracking-store/spec.md`
**Plan**: `specs/007-sqlite-tracking-store/plan.md`

---

## Phase 1 — MigrationRecord adjustment

- [ ] **1.1** Edit `src/cmcourier/domain/models.py`: add `batch_id: str` field to `MigrationRecord` between `rvabrep_file_name` and `status`. Required field, no default.
- [ ] **1.2** Update `tests/unit/domain/test_models.py`: every test that constructs `MigrationRecord` MUST pass `batch_id` (use `"batch-test-001"` or similar synthetic value).
- [ ] **1.3** Run `pytest tests/unit/domain/test_models.py -v`. Confirm all green.
- [ ] **1.4** Run `mypy src/cmcourier/domain/`. Confirm clean.

---

## Phase 2 — Integration tests RED

- [ ] **2.1 (R)** Create `tests/integration/adapters/test_sqlite_tracking_store.py` with `TestSQLiteTrackingStore` class and the ~20 tests per plan §5.1. Group: schema (3), batch lifecycle (4), per-stage state (5), queries (5), lifecycle (3), errors (1).
- [ ] **2.2 (R)** Add a `_make_record(batch_id, txn_num, **overrides)` helper at module level for terse `MigrationRecord` construction in tests.
- [ ] **2.3 (R)** Run `pytest tests/integration/adapters/test_sqlite_tracking_store.py -v`. Confirm every test fails with `ImportError`.

---

## Phase 3 — SQLiteTrackingStore GREEN

- [ ] **3.1 (G)** Create `src/cmcourier/adapters/tracking/sqlite.py` with module docstring, `__all__`, imports, logger, SQL constants, and PRAGMA tuple per plan §4.1 + §4.3.
- [ ] **3.2 (G)** Implement `SQLiteTrackingStore.__init__`: open both connections, apply PRAGMAs, create schema, init queue + stop event, start writer thread.
- [ ] **3.3 (G)** Implement `_create_schema` (idempotent) and `_apply_pragmas` per plan §4.2 + §4.3.
- [ ] **3.4 (G)** Implement `_writer_loop` per plan §4.4. Test that writer thread exits cleanly on stop event.
- [ ] **3.5 (G)** Implement `flush()` (queue.join wrapper).
- [ ] **3.6 (G)** Implement `start_batch` (synchronous via reader connection per plan §3.4).
- [ ] **3.7 (G)** Implement `complete_batch` (enqueued).
- [ ] **3.8 (G)** Implement `mark_stage_pending` per plan §4.6 (with stage validation; uses `INSERT OR IGNORE`).
- [ ] **3.9 (G)** Implement `mark_stage_done`, `mark_stage_failed` (both enqueued; failed increments retry_count).
- [ ] **3.10 (G)** Implement `is_uploaded` (synchronous read, partial-index query).
- [ ] **3.11 (G)** Implement `is_stage_done` (synchronous read; raises `ValueError` for non-DONE stages).
- [ ] **3.12 (G)** Implement `close()` per plan §4.5 (idempotent, drains queue, joins writer with timeout).
- [ ] **3.13 (G)** Wrap every direct `sqlite3.Error` in `TrackingError` per plan §3.11.
- [ ] **3.14 (G)** Run pytest. Iterate until all ~20 tests green.
- [ ] **3.15 (Rf)** Refactor for clarity. Ensure 50-line function cap (longest is `_writer_loop` ~30 lines).

---

## Phase 4 — Re-exports + verification

- [ ] **4.1 (G)** Update `src/cmcourier/adapters/tracking/__init__.py` to re-export `SQLiteTrackingStore`.
- [ ] **4.2** `ruff check src/ tests/` — clean.
- [ ] **4.3** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **4.4** `mypy src/cmcourier/` — clean.
- [ ] **4.5** `pytest --cov=src/cmcourier --cov-report=term` — coverage on `adapters/tracking/sqlite.py` ≥ 90%, total ≥ 80%.
- [ ] **4.6** `pre-commit run --all-files` — clean.

---

## Phase 5 — Docs + commit

- [ ] **5.1** Update `CHANGELOG.md` `[0.9.0]` per plan §6.
- [ ] **5.2** Update `README.md` Status checklist: tick "Seventh change: SQLite tracking store".
- [ ] **5.3** PII grep on new files. Synthetic only.
- [ ] **5.4** Stage all files. Confirm git status matches:
  ```
  modified: CHANGELOG.md
  modified: README.md
  modified: src/cmcourier/domain/models.py        # batch_id added
  modified: src/cmcourier/adapters/tracking/__init__.py
  modified: tests/unit/domain/test_models.py      # constructions updated
  added: src/cmcourier/adapters/tracking/sqlite.py
  added: tests/integration/adapters/test_sqlite_tracking_store.py
  added: specs/007-sqlite-tracking-store/{spec,plan,tasks}.md
  ```
- [ ] **5.5** Commit:
  ```
  feat(adapters): add SQLiteTrackingStore with async writer queue

  Stage S6 (Tracking) for every CMCourier pipeline. Concrete
  ITrackingStore via stdlib sqlite3 with WAL mode + tuned PRAGMAs
  (REBIRTH §9.3), the per-stage state machine (§10.3), the cross-batch
  is_uploaded idempotency anchor, and the async writer queue with
  batched commits (§9.4) for production-scale workloads.

  Two tables ship: migration_log + migration_batch. Unique index on
  (rvabrep_txn_num, batch_id) makes mark_stage_pending idempotent
  within a batch via INSERT OR IGNORE; partial index on
  rvabrep_txn_num WHERE status='S5_DONE' makes the cross-batch
  is_uploaded query O(1).

  Threading model: two SQLite connections (reader + writer), one
  daemon writer thread, one queue. Writes go through the queue and
  commit in batches of up to 500 (or every 1s, whichever first).
  Reads are synchronous on the reader connection. flush() blocks
  until the queue is drained and the current batch is committed —
  used by tests and by orchestrators that need to read state they
  themselves wrote.

  start_batch is the only synchronous write (returns a UUID4 the
  caller needs immediately).

  MigrationRecord (002) gains a required batch_id: str field. This
  resolves a port inconsistency where mark_stage_pending(record,
  stage) had no way to know the record's batch. Adding the field is
  cleaner than amending the port signature. tests/unit/domain/
  test_models.py updated to pass batch_id in every construction.

  preprocess_staging and document_cache tables are NOT in scope
  here — the 3-phase pipeline and cross-mode metadata cache that
  use them are post-MVP.

  Verification:
  - pytest -v: all tests pass (~242 total = 222 + ~20 new)
  - coverage on adapters/tracking/sqlite.py: XX% branch (target ≥90%)
  - ruff / mypy: clean
  - pre-commit: clean

  Constitution Principle II (idempotency) is structural — the unique
  and partial indexes encode it in the schema. Principle VIII (PII
  discipline) — logs identify operational keys (txn_num, batch_id)
  but never field values; error_message bodies are stored in the DB
  but not echoed to logs.

  Closes specs/007-sqlite-tracking-store/.
  ```

---

## Verification mapping

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..003 (model) | 1.1, 1.2 |
| REQ-004..013 (class) | 3.x + tests in 2.1 |
| REQ-014..018 (schema) | 3.1, 3.3 + schema tests |
| REQ-019..026 (API) | 3.6..3.12 + corresponding tests |
| REQ-027..031 (tests + cov) | 2.1, 4.5 |
| REQ-032..034 (tooling) | 4.2..4.4, 4.6 |

Each acceptance scenario 4.1..4.12 maps to a specific test in 2.1.

---

## Estimated effort

- Phase 1 (MigrationRecord): 15 min
- Phase 2 (tests RED): 90 min
- Phase 3 (impl GREEN): 120 min
- Phase 4 (verification): 20 min
- Phase 5 (docs + commit): 15 min
- **Total**: ~4h 20min focused work.

The largest change so far. Phases 2 and 3 dominate (test breadth + threading complexity).

---

## Notes for the implementor

- Constitution Principle I: NO services / orchestrators imports in `adapters/tracking/sqlite.py`. Tests freely import `MigrationRecord`, `StageStatus` from domain.
- 50-line function cap: `_writer_loop` at ~30 lines is the longest method. `mark_stage_pending` with the 18-tuple is ~25 lines (use a helper if it grows).
- Use `datetime.isoformat()` for stored timestamps; parse with `datetime.fromisoformat()` on read. Never store a `datetime` object directly (sqlite3 has converters but they're surprising).
- `queue.task_done()` MUST be called per item in the writer loop (in the `finally` block), otherwise `flush()` (which calls `queue.join()`) hangs forever.
- `threading.Event.wait(timeout)` is fine but we use `queue.get(timeout=...)` because we want to be event-driven on items, not on time.
- The `daemon=True` on the writer thread means a hard process kill won't wait for it. `close()` is the graceful shutdown path.
- Test fixtures use `tmp_path` (pytest builtin) — automatic cleanup.
- `sqlite3.connect(path, isolation_level=None)` would enable autocommit; we do NOT use it. Default explicit transactions are correct here.
- After `INSERT INTO migration_batch` in `start_batch`, an explicit `commit()` is required because the reader connection has its own transaction.

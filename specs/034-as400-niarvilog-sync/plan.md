# 034 — Implementation Plan

Companion to `spec.md`. Six phases, ~12–15h total.

---

## Phase 1 — Schema + connection + doctor (~2h)

1. Add `As400SyncConfig` Pydantic model to
   `config/schema.py`. Composes `As400ConnectionConfig`.
2. Add `as400_sync: As400SyncConfig = ProcessingDefault()` to
   `TrackingConfig`.
3. Schema tests: defaults, custom values, range validation,
   missing connection when enabled raises.
4. Extend `cli/doctor.py` with an AS400-sync check:
   - SKIP when `enabled=false`.
   - CONNECT + SELECT 1 FROM NIARVILOG WHERE 1=0 when
     `enabled=true`.
   - PASS / FAIL.
5. Add `cmis_type: str = ""` to `CMMapping` (default empty,
   035 will fill it). Update mapping service to read the
   column when present, default `""` when not.

**Done when**: schema tests pass, doctor check runs with
faked pyodbc.

---

## Phase 2 — As400NiarvilogStore (~4h)

1. New file `cmcourier/adapters/tracking/as400_niarvilog.py`.
2. `NiarvilogRow` dataclass (one row of the table).
3. `As400NiarvilogStore` class:
   - `try_claim(record)` — `UPDATE … WHERE STSCOD='N'` with
     fallback `INSERT` on race.
   - `mark_uploaded(record, cm_object_id)`.
   - `mark_failed(record, error)`.
   - `read_state(siscod, trnnum, docfrm, imgarc)`.
   - `cleanup_stale_in_progress()`.
4. Unit tests with pyodbc faked at the cursor boundary
   (reuse `_FakeCursor` / `_FakeConn` pattern from
   `tests/integration/cli/test_pipeline_kinds.py`).
5. Tests cover all REQ-005..REQ-010 + retry / backoff.

**Risk**: DB2's `FOR EACH ROW ON UPDATE AS ROW CHANGE
TIMESTAMP` on `FINREI` is implicit. Our UPDATE statements
must NOT include `FINREI` in the SET clause — DB2 updates it
automatically. Tested via the fake cursor recording the SQL
text.

---

## Phase 3 — IdempotencyCoordinator + pre-flight sync (~3h)

1. New file `cmcourier/services/idempotency.py` with
   `IdempotencyCoordinator` + `SyncReport` dataclass.
2. Pre-flight sync algorithm:
   - Read every NIARVILOG row whose `TRNNUM` matches the
     batch scope.
   - For each row, compare with SQLite state.
   - Classify into `imported`, `conflicts`, `consistent`.
   - Apply `imported_from_as400` writes to SQLite.
   - If `conflicts` non-empty: raise `IdempotencyConflictError`
     with the txn list.
3. Integrate into `StagedPipeline.run()`:
   - When AS400 enabled, call `coordinator.preflight_sync()`
     before `_stage_s0_s1`.
   - Replace `tracking_store.is_uploaded(txn)` with
     `coordinator.is_uploaded(txn)`.
   - Replace S5 done/failed marking with coordinator calls.
4. Unit tests for the coordinator covering both
   AS400-enabled and AS400-disabled paths.

**Risk**: `StagedPipeline` is large and well-tested. Threading
the coordinator through requires careful refactor to avoid
breaking existing tests. Approach: keep `tracking_store`
parameter, add optional `coordinator` parameter that wraps
`tracking_store` if not provided.

---

## Phase 4 — CLI `sync resolve` (~2h)

1. New `cmcourier/cli/commands/sync.py` with click group:
   - `cmcourier sync resolve <txn> --prefer-as400|--prefer-local
     --config <path>`
   - `cmcourier sync resolve --all --prefer-as400 --config <path>`
   - `cmcourier sync status --config <path>` (list current
     conflicts without resolving).
2. Wire into `main` in `cli/app.py`.
3. Integration tests for each subcommand.

---

## Phase 5 — Retry / backoff + E2E (~2h)

1. Wrap every NIARVILOG write in a retry helper
   `_retry_on_operational_error(operation, attempts,
   base_delay)`.
2. Define `As400UnreachableError(pipeline.exit_2)` exception.
3. Integration test simulating a transient `pyodbc.OperationalError`
   on the first attempt; assert retry succeeds on attempt 2.
4. Integration test for 3 consecutive failures → exit 2.

---

## Phase 6 — Docs + verification + FF merge (~1h)

1. `docs/how-to/as400-sync.md`:
   - When to enable.
   - YAML snippet.
   - Field mapping table.
   - Conflict resolution playbook.
   - Operations: cleanup, push-local-to-as400 (manual).
2. CHANGELOG `[0.35.0]` entry.
3. README status checklist tick (34th change).
4. POST-MVP §4 marked SHIPPED.
5. Full gate (ruff + mypy + pytest).
6. Conventional commit per phase + FF merge into `main`.

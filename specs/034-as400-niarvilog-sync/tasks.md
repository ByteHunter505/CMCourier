# 034 — Tasks

## Phase 1 — Schema + connection + doctor
- [ ] T1.1 — Schema tests for `As400SyncConfig` (defaults, ranges, validation).
- [ ] T1.2 — Implement `As400SyncConfig` + attach to `TrackingConfig`.
- [ ] T1.3 — Add `cmis_type: str = ""` to `CMMapping` + mapping service reads optional column.
- [ ] T1.4 — Doctor check for AS400 sync (SKIP when disabled, validate connection + table when enabled).

## Phase 2 — As400NiarvilogStore
- [ ] T2.1 — Unit tests for `As400NiarvilogStore` (claim atomic, mark uploaded, mark failed, read state, cleanup stale).
- [ ] T2.2 — Implement `As400NiarvilogStore` with pyodbc.

## Phase 3 — IdempotencyCoordinator + pre-flight sync
- [ ] T3.1 — Coordinator unit tests (enabled + disabled paths).
- [ ] T3.2 — Implement `IdempotencyCoordinator` + `SyncReport`.
- [ ] T3.3 — Integrate into `StagedPipeline.run()` (pre-flight + claim + done/failed).

## Phase 4 — CLI sync resolve
- [ ] T4.1 — CLI integration tests for `sync resolve` (single, --all, status).
- [ ] T4.2 — Implement `cmcourier sync` group + commands.

## Phase 5 — Retry / backoff + E2E
- [ ] T5.1 — Wrap NIARVILOG writes in retry helper.
- [ ] T5.2 — Integration tests: transient failure → retry succeeds; 3 fails → exit 2.

## Phase 6 — Docs + verification
- [ ] T6.1 — `docs/how-to/as400-sync.md`.
- [ ] T6.2 — CHANGELOG `[0.35.0]` + README tick.
- [ ] T6.3 — POST-MVP §4 marked SHIPPED.
- [ ] T6.4 — Full gate (ruff + mypy + pytest).
- [ ] T6.5 — Conventional commit + FF merge.

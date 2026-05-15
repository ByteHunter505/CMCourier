# 064 — Tasks

Branch: `feat/064-tui-bucket-tab`.

## Phase 1

- [ ] T1. Orchestrator hooks
  - `_prep_in_flight` counter + lock; producer `_inc()` / `_dec()`
  - `bucket_level()`, `prep_in_flight()`, `streaming_throughput()`
  - Track timestamps for sliding-window throughput

- [ ] T2. `TUIDataProvider`
  - `mode` field
  - `bucket_provider` callable
  - `bucket_snapshot()` method

- [ ] T3. BUCKET Textual tab
  - New `BucketTab` widget
  - Conditional mount based on mode
  - 1s refresh tick

- [ ] T4. CLI wiring
  - `cli/app.py` passes `mode=` and `bucket_provider=` to the TUI

- [ ] T5. Tests
  - 3 streaming unit tests (in_flight, level, throughput)
  - 3 data-provider unit tests
  - 1 light TUI binding test (rendering shape)

- [ ] T6. Verify: pytest unit + integration, ruff, mypy.

- [ ] T7. Commit:
  - `feat(tui): BUCKET tab for streaming mode (064 Phase 1)`

## Phase 2

- [ ] T8. CHANGELOG `[0.66.0]`
- [ ] T9. pyproject 0.65.0 → 0.66.0
- [ ] T10. `.venv/bin/pip install -e . --no-deps` + version verify
- [ ] T11. README feature row tick
- [ ] T12. Commit: `docs(064): CHANGELOG 0.66.0 + version bump + bucket-tab docs (064 Phase 2)`
- [ ] T13. FF to main

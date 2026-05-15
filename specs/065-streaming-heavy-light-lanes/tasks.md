# 065 — Tasks

Branch: `feat/065-streaming-heavy-light-lanes`.

## Phase 1

- [ ] T1. Extend `streaming_upload_one(..., lane=None)` in
      `staged.py`
- [ ] T2. `StreamingOrchestrator`: optional `LaneController`,
      per-lane queues, dispatcher thread, per-lane consumer pools
- [ ] T3. `StreamingSnapshot.lane_snapshot` field; populate it
      in `streaming_snapshot()`
- [ ] T4. `cli/app.py`: drop the 063 WARN about streaming+lanes
- [ ] T5. BUCKET tab renders the LANES block when present
- [ ] T6. Tests:
  - dispatcher routes by size
  - clean shutdown with lanes
  - snapshot carries `lane_snapshot`
  - BUCKET tab renders the lane block
- [ ] T7. Verify pytest, ruff, mypy
- [ ] T8. Commit `feat(orchestrator): heavy/light lanes in streaming mode (065 Phase 1)`

## Phase 2

- [ ] T9. CHANGELOG `[0.67.0]`
- [ ] T10. pyproject 0.66.0 → 0.67.0
- [ ] T11. `pip install -e . --no-deps` + version verify
- [ ] T12. README feature row tick
- [ ] T13. Commit `docs(065): CHANGELOG 0.67.0 + version bump (065 Phase 2)`
- [ ] T14. FF to main

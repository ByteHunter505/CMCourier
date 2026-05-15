# 070 — Tasks

Branch: `feat/070-unify-lane-controller`.

## Phase 1

- [ ] T1. `streaming.py`: drop `LaneController(...)` construction
      in `__init__`. Replace `self._lane_controller` field with a
      property returning `self._pipeline.lane_controller`.
- [ ] T2. `_FakePipeline` in test_streaming exposes
      `lane_controller` attribute.
- [ ] T3. Test `test_streaming_reuses_pipeline_lane_controller`
      pinning the identity.
- [ ] T4. Verify pytest, ruff, mypy clean.
- [ ] T5. Commit `fix(streaming): unify LaneController with pipeline — UPLOAD-tab LANES live (070 Phase 1)`

## Phase 2

- [ ] T6. CHANGELOG `[0.72.0]`
- [ ] T7. pyproject 0.71.0 → 0.72.0
- [ ] T8. `pip install -e . --no-deps` + version verify
- [ ] T9. README feature row tick
- [ ] T10. Commit `docs(070): CHANGELOG 0.72.0 + version bump (070 Phase 2)`
- [ ] T11. FF to main

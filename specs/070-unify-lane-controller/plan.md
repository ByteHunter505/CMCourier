# 070 — Plan

Single-phase. Minimal-touch refactor.

## Phase 1 — code + tests

### `src/cmcourier/orchestrators/streaming.py`

* `__init__`: drop the `LaneController(...)` construction block.
  Keep `self._lanes_config = config.processing.heavy_light_lanes`
  (the dispatcher needs the threshold).
* Drop `self._lane_controller` field — use a property:

```python
@property
def lane_controller(self) -> LaneController | None:
    """070: single LaneController per run, owned by StagedPipeline."""
    return self._pipeline.lane_controller
```

* Every reference to `self._lane_controller` reads through the
  property (no rename needed at call sites since attribute access
  pattern matches).
* The `run()` block that calls `self._lane_controller.start()` /
  `.stop()` and the dispatcher / consumer code stay as-is; they
  just now hit the pipeline's instance.

### Tests

`tests/unit/orchestrators/test_streaming.py`:

* New test `test_streaming_reuses_pipeline_lane_controller`:
  - Build a `_FakePipeline` with a synthetic
    `_lane_controller` field (real `LaneController` instance).
  - Build the orchestrator with lanes_enabled=True.
  - Assert `orch.lane_controller is pipeline.lane_controller`.

* Update `_FakePipeline` to expose a `lane_controller` attribute
  matching the contract.

### Verify

`pytest tests/unit tests/integration -q` green. ruff + mypy clean.

### Commit

```
fix(streaming): unify LaneController with pipeline — UPLOAD-tab LANES live (070 Phase 1)
```

## Phase 2 — release

- CHANGELOG `[0.72.0]`
- pyproject 0.71.0 → 0.72.0
- `pip install -e . --no-deps` + version verify
- README feature row tick
- FF to main

Commit: `docs(070): CHANGELOG 0.72.0 + version bump (070 Phase 2)`.

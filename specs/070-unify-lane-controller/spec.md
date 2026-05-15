# 070 — Unify the LaneController across streaming + batched

## Why

Operator-reported in the post-067 streaming run: the UPLOAD tab's
LANES sub-block shows `queue 0` for both HEAVY and LIGHT — always,
never moves. The BUCKET tab's LANES block shows correct live
queue values for the same run.

Same data, two renderers, two different sources. Root cause:
**there are two independent `LaneController` instances in a
streaming run with `heavy_light_lanes.enabled: true`**.

### The dual-controller bug

`StagedPipeline.__init__` constructs its own `LaneController` when
`heavy_light_lanes.enabled=True` (this was 036's wiring, for the
batched S5 dual-pool path):

```python
self._lane_controller: LaneController | None = None
if heavy_light_lanes is not None and heavy_light_lanes.enabled:
    self._lane_controller = LaneController(...)
```

`StreamingOrchestrator.__init__` (065) constructs **another**
`LaneController` — its own — for the streaming dispatcher:

```python
self._lane_controller: LaneController | None = None
if self._lanes_config.enabled:
    self._lane_controller = LaneController(...)
```

Both instances exist concurrently in a streaming-mode run. The
**streaming** dispatcher and consumers call
`set_queue_depth(...)` on the **orchestrator's** controller. The
**batched** controller (sitting idle on the pipeline) never
receives any updates.

The TUI wiring (`cli/app.py` line 689):

```python
data_provider = TUIDataProvider(
    ...
    lane_controller=pipeline.lane_controller,
    ...
)
```

reads the pipeline's controller — the dead one in streaming. The
BUCKET tab (064) reads through a separate `bucket_provider`
callable that returns `orch.streaming_snapshot()` with
`lane_snapshot=self._lane_controller.snapshot()` of the
orchestrator's controller — that one is live.

Result: BUCKET tab correct, UPLOAD tab dead.

Beyond the visibility bug, this also means **AIMD can't talk to
the streaming-mode lane controller**. AIMD's `set_total_budget`
goes through `StagedPipeline._on_pool_resize`:

```python
def _on_pool_resize(self, new_total: int) -> None:
    if self._lane_controller is not None:
        self._lane_controller.set_total_budget(new_total)
    else:
        self._concurrency_limit.set_capacity(new_total)
```

That sets the budget on the **pipeline's** (idle) controller. The
streaming controller — the one actually gating per-lane
concurrency in the run — gets nothing. AIMD growth in streaming
+ heavy/light has been silently broken since 065.

## What

**One LaneController per run.** The `StagedPipeline` owns its
construction (as in 036). The `StreamingOrchestrator` reuses
`self._pipeline.lane_controller` instead of building its own.

### Changes in `StreamingOrchestrator`

* Drop the constructor block that builds
  `self._lane_controller = LaneController(...)`.
* Replace `self._lane_controller` reads with
  `self._pipeline.lane_controller` (the pipeline's instance).
* The `lane_controller` property already exposed for the TUI now
  forwards: `return self._pipeline.lane_controller`.
* Keep `self._lanes_config = config.processing.heavy_light_lanes`
  for the dispatcher's threshold lookup and the
  enabled / disabled branch.

### Why this is correct

* `StagedPipeline._lane_controller` exists only when
  `heavy_light_lanes.enabled=True`. The streaming orchestrator's
  same-config decision tree triggers on the same boolean, so the
  two are always in sync.
* The pipeline's controller is unused by the batched S5 path
  *because that path doesn't run in streaming mode*. We're not
  contending — we're occupying the previously-empty slot.
* AIMD's `_on_pool_resize → pipeline.lane_controller.set_total_budget`
  now correctly steers the streaming dispatcher's lane budgets.
* TUI wiring (`cli/app.py`) stays exactly the same. Both
  `pipeline.lane_controller` (UPLOAD tab) and
  `orch.streaming_snapshot().lane_snapshot` (BUCKET tab) read the
  same instance.

### What happens in `lane_controller.start()` / `stop()`

Both the batched path and the streaming path call `start()` /
`stop()` on the controller around the S5 work. With the unified
controller:

* In batched mode, `_stage_5_dual` already starts/stops it. No
  change.
* In streaming mode, `StreamingOrchestrator.run` already
  starts/stops `self._lane_controller` — which is now the same
  pipeline instance. No code change; just the target shifts.

`LaneController.start()` is idempotent (the existing
implementation guards on `self._thread is not None`), so even if
both paths called it accidentally, no harm.

## Out of scope

- Migrating the batched S5 path to share the streaming dispatcher
  shape. That's a unification spec — not in scope here.
- Adding a CLI flag to disable lanes per-mode. Operators can
  already do that with `heavy_light_lanes.enabled: false` in YAML.

## Acceptance criteria

- `StreamingOrchestrator` no longer constructs a `LaneController`
  in `__init__`. It reads from `self._pipeline.lane_controller`.
- `StreamingOrchestrator.lane_controller` property returns
  `self._pipeline.lane_controller`.
- UPLOAD-tab LANES sub-block shows live `queue`, `in-use`, etc.
  matching the BUCKET-tab LANES block (same data source).
- AIMD-triggered `set_total_budget` reaches the streaming
  dispatcher's per-lane semaphore split.
- All existing unit tests pass (including
  `test_streaming_snapshot_carries_lane_snapshot_when_enabled`
  and `test_lane_queue_depth_never_exceeds_bucket_size` from 067).
- New test pinning the unification: in streaming + lanes mode,
  `pipeline.lane_controller is orch.lane_controller`.
- mypy + ruff clean.
- CHANGELOG `[0.72.0]`; pyproject 0.71.0 → 0.72.0.

## Notes on impact

* No behaviour change for batched mode.
* No behaviour change for streaming single-lane (lanes disabled).
* In streaming + lanes mode:
  - UPLOAD-tab LANES block becomes live.
  - AIMD-driven lane rebalance becomes effective (was silently
    broken pre-070, see "Why" above).

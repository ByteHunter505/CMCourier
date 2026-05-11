# 036 — Plan

Phase rhythm matches prior multi-phase changes: RED → GREEN per
phase, commit per phase, FF on the last commit. Estimated total
~10-12h.

## Phase 1 — Schema + LaneSplitter (~2h)

### Files

- `src/cmcourier/config/schema.py`
  - New `HeavyLightLanesConfig` (frozen, extra=forbid).
  - `ProcessingConfig.heavy_light_lanes: HeavyLightLanesConfig =
    Field(default_factory=...)`.
  - Validators: `heavy_initial_ratio` in `[0.0, 1.0]`, all duration
    fields `gt=0`, threshold `> 0`, min_batch `>= 1`.

- `src/cmcourier/services/lane_splitter.py` (new)
  - `Lane = Literal["heavy", "light"]`
  - `@dataclass(frozen=True) class LaneAssignment: heavy: tuple[T,...]; light: tuple[T,...]; is_single_lane: bool`
  - `def split(items, threshold_bytes, min_batch, *, size_of) -> LaneAssignment`
  - Pure function (no logging, no I/O).

### Tests

- `tests/unit/config/test_schema.py::TestHeavyLightLanesConfig`
  - Defaults.
  - Validators reject negative / out-of-range values.
- `tests/unit/services/test_lane_splitter.py` (new)
  - Small batch → all light.
  - Bimodal batch → correct split.
  - All small → degenerate, single-lane.
  - All large → degenerate, single-lane.
  - Order preserved within each lane.
  - Custom `size_of` accessor for different item types.

### Commit

```
feat(config,services): HeavyLightLanesConfig + LaneSplitter (036 Phase 1)
```

## Phase 2 — LaneController + dual-pool S5 (~4h)

### Files

- `src/cmcourier/services/lane_controller.py` (new)
  - `class LaneController`:
    - Owns `heavy_sem: ResizableSemaphore`, `light_sem: ResizableSemaphore`.
    - Owns per-lane `WorkerPoolStats` (or a small wrapper that reuses
      the existing class twice).
    - `start(rebalance_interval_s, idle_threshold_s)` — launches the
      rebalance daemon thread.
    - `stop()` — stops + joins.
    - `set_total_budget(total: int)` — AIMD hook, redistributes
      proportionally.
    - `acquire(lane: Lane)` / `release(lane: Lane)`.
    - `mark_queue_depth(lane, n)` — splitter feeds this once.
    - Logs structured `lane_rebalance` events.

- `src/cmcourier/orchestrators/staged.py`
  - In `__init__`: when `heavy_light_lanes.enabled`, build a
    `LaneController` instead of (or alongside) the single
    `ResizableSemaphore`.
  - In `_stage_5`: when dual mode AND splitter says not-single-lane,
    submit each item with its lane tag; `_upload_one` acquires the
    lane sem instead of the global concurrency_limit.
  - AIMD `on_workers_change`: when dual mode is on, forward to
    `LaneController.set_total_budget(new)` instead of resizing the
    single semaphore.

### Tests

- `tests/unit/services/test_lane_controller.py` (new)
  - Initial allocation respects `heavy_initial_ratio`.
  - `set_total_budget` preserves ratio.
  - `set_total_budget` enforces `≥1` per lane when total ≥ 2.
  - Drain detection migrates workers (mock time).
  - `acquire`/`release` correctly cap concurrency per lane.
  - Logged rebalance events are structurally correct.
- `tests/integration/pipeline/test_dual_lane_s5.py` (new)
  - Bimodal batch + mock CMIS uploader. Verify all docs upload,
    splits respected, no deadlocks.
  - Regression: with `enabled=False`, identical outcomes to
    single-lane reference fixture.

### Commit

```
feat(pipeline): LaneController + dual-lane S5 (AIMD-coupled) (036 Phase 2)
```

## Phase 3 — TUI dual sub-panels + structured events (~2h)

### Files

- `src/cmcourier/tui/data_provider.py`
  - Expose `lane_controller: LaneController | None` snapshot —
    `LaneSnapshot(heavy=PoolSnapshot, light=PoolSnapshot)`.
- `src/cmcourier/tui/widgets/upload.py` (or current location)
  - When `LaneSnapshot is not None`: render HEAVY/LIGHT sub-panels
    side by side. Otherwise render the legacy single panel.
- Rebalance event → TUI notification (Textual `notify`).

### Tests

- `tests/integration/tui/test_dual_lane_panels.py` (new)
  - Drive a fake `LaneSnapshot` and snapshot the rendered widget.
  - Verify single-pane mode still renders unchanged.

### Commit

```
feat(tui): dual heavy/light UPLOAD sub-panels + rebalance notifications (036 Phase 3)
```

## Phase 4 — Throughput proof + bandwidth property test + docs + FF (~3h)

### Files

- `tests/integration/pipeline/test_dual_lane_throughput.py` (new)
  - 30 × 1 MB + 5 × 50 MB synthetic batch.
  - Mock uploader sleeps 0.05 s/MB.
  - Run single-lane → wall-clock T1.
  - Run dual-lane → wall-clock T2.
  - Assert `T2 ≤ T1 * 0.7`.
  - `@pytest.mark.slow` if needed.

- `tests/property/test_bandwidth_dual_lane.py` (new)
  - Hypothesis: random bimodal batches, random worker budgets.
  - Sum of bytes/sec recorded across both lanes ≤
    `cmis.max_bandwidth_mbps` over any 1-second window.

- `docs/how-to/heavy-light-lanes.md` (new)
  - When to enable, knob trade-offs, how to read the dual TUI panel,
    how to read `lane_rebalance` events in offline log analysis.

- `CHANGELOG.md` `[0.37.0]`, README tick, POST-MVP §1 mark SHIPPED.

### FF merge

```
git checkout main
git merge --ff-only feat/036-heavy-light-lanes
git branch -d feat/036-heavy-light-lanes
```

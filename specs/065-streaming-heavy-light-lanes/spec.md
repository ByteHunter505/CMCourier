# 065 — Heavy/light lanes in streaming mode

## Why

063 ships streaming mode with single-lane S5 — every prepared
doc goes to the same consumer pool. 036 already provides
**heavy/light lanes** (POST-MVP §1) for batched mode: split docs
by `file_size_bytes >= heavy_threshold_bytes` so a single 50 MB
PDF cannot starve the bandwidth a flock of 1 MB JPEGs would
share. In streaming mode the same starvation is *worse* — the
bucket lacks a notion of "this chunk", so a sequence of heavy
docs blocks the lighter ones behind them in a FIFO queue.

The split is per-item: every prepared doc carries a known
`staged_file.size_bytes` (added in 036). The lane decision must
happen at *consume time*, after the producer puts the item in
the bucket — because the bucket itself is FIFO.

## What

### 1. Lane decision at consume time

The streaming orchestrator's single consumer pool gets replaced
by **two pools** (heavy + light), each backed by a per-lane
`queue.Queue`. A new lightweight **dispatcher** thread pulls
from the main bucket and routes each item:

```
PREP producers ──▶ main bucket ──▶ dispatcher
                                      │
                       size ≥ threshold?
                       ┌──────────┴──────────┐
                       ▼                     ▼
                heavy lane queue       light lane queue
                       │                     │
                heavy consumer(s)     light consumer(s)
```

The total consumer budget stays at `_pool_ceiling()`; the
`LaneController` from 036 owns the heavy/light split (initial
ratio, drain-driven rebalance). Single-lane is preserved when
`heavy_light_lanes.enabled = false` (default).

### 2. Reuse existing infrastructure

* `LaneController` — already exists (036), single source of truth
  for per-lane semaphores + rebalance daemon.
* `LaneSplitter`-style per-item classification — but the
  function ships in 036 as a *batch* splitter. We add a
  per-item helper `classify_lane(item, heavy_threshold_bytes)`
  that returns `"heavy"` | `"light"`.
* `_upload_one(item, batch_id, recorder, lane)` already accepts
  a lane — used unchanged.

### 3. New orchestrator wiring

`StreamingOrchestrator` constructor:

* Reads `heavy_light_lanes` from config. When `enabled`, builds
  a `LaneController` exactly like `StagedPipeline` does.
* Spawns one dispatcher thread + heavy_count + light_count
  consumer threads. Producer logic unchanged.

Per-lane consumer count is derived from
`_lane_controller.snapshot().heavy_budget` /
`light_budget` at start; the rebalance daemon adjusts the
semaphores. Both pools share the same `_pool_ceiling()` size so
when AIMD scales up, both lanes can grow.

### 4. Wiring layer

`cli/app.py` removes the WARN that 063 added. When
`mode=="streaming" AND heavy_light_lanes.enabled=true`, the
streaming orchestrator just works.

### 5. TUI

The BUCKET tab (064) gains an optional "LANES" sub-block when a
`LaneController` is present — shows per-lane budget / busy / idle
and the running rebalance counter, reusing the existing
`LaneSnapshot` data shape.

## Out of scope

- Reordering items within the bucket to interleave heavy/light.
  The dispatcher's split-at-consume is sufficient.
- Cross-lane rebalance heuristics beyond what 036 already ships.

## Acceptance criteria

- `processing.mode=="streaming"` with
  `heavy_light_lanes.enabled=true` runs cleanly — heavy items
  land in the heavy lane, light items in the light lane.
- The startup WARN added in 063 (`heavy/light deferred to spec
  065`) is removed.
- Dispatcher exits cleanly on `_POISON` from the main bucket.
- BUCKET tab shows the per-lane block when dual mode is active.
- All existing tests pass. New tests cover lane classification +
  dispatcher fan-out + clean shutdown.
- CHANGELOG `[0.67.0]`; pyproject 0.66.0 → 0.67.0.

## Notes

- The dispatcher is a single thread — it cannot become the
  bottleneck for any realistic workload (one comparison +
  `queue.put` per item).
- We keep the **main bucket** size = configured `bucket_size`.
  Per-lane queues use `maxsize=bucket_size` too — so total
  in-flight is ~`3 × bucket_size` worst-case. The operator's
  knob remains `bucket_size`.

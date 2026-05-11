# 036 — Adaptive heavy / light upload lanes (POST-MVP §1)

## Why

Today S5 uses a single `ThreadPoolExecutor` shared across all
documents in a batch. On heterogeneous batches (a few 50 MB PDFs +
many 200 KB JPEGs), the large docs **hog workers** while the small
docs starve — classic head-of-line blocking.

REBIRTH §10.7 + POST-MVP §1 describe a two-lane upload model that
splits the batch by file size, runs each lane in its own slice of
the worker budget, and rebalances as one lane drains.

## What

### Configuration

New schema block under `ProcessingConfig`:

```python
class HeavyLightLanesConfig(BaseModel):
    enabled: bool = False
    heavy_threshold_bytes: int = 10 * 1024 * 1024  # 10 MB
    heavy_lane_min_batch: int = 50
    heavy_initial_ratio: float = 0.2  # 20% of total workers to heavy
    rebalance_interval_s: float = 10.0
    idle_threshold_s: float = 15.0
```

Default `enabled = False` — single-lane (pre-036) behavior unchanged.

### Splitter

Pure-function service `LaneSplitter.split(items, threshold_bytes,
min_batch) -> (heavy, light)`. Rules:

1. If `len(items) < min_batch` → all light, no heavy. Returns
   `(heavy=[], light=items)` and the caller falls back to single-lane.
2. Otherwise: partition by `item.file_size_bytes >= threshold_bytes`.
3. **Degenerate fallback**: if either partition ends up empty,
   collapse back to single-lane (`(heavy=[], light=items)` or
   `(heavy=items, light=[])` is normalized to single-lane downstream).

### LaneController

Owns two `ResizableSemaphore`s — `heavy_sem`, `light_sem` — plus a
total-budget AIMD coupling.

* **Initial allocation**: `heavy_workers = ceil(total * heavy_initial_ratio)`,
  `light_workers = total - heavy_workers`. Each lane gets at least 1
  if total ≥ 2.
* **AIMD integration** (user-locked: AIMD owns global budget,
  rebalance owns split): when AIMD changes the total budget, the
  controller redistributes proportionally to the current split
  (preserves the current heavy:light ratio).
* **Rebalance loop** runs in a daemon thread every
  `rebalance_interval_s`. Two trigger rules:
  - If heavy queue has been empty for ≥ `idle_threshold_s`: migrate
    all heavy workers to light (heavy gets 0, light gets total).
  - If light queue has been empty for ≥ `idle_threshold_s`: migrate
    all light workers to heavy (vice versa).
  - Otherwise: maintain the current split.
* **Rebalance is non-preemptive**: in-flight uploads keep running
  on whichever worker they're on. The semaphore caps determine
  which queue future workers pull from.
* **Structured rebalance events**: every migration emits a JSON line
  via the standard pipeline logger with
  `{"event": "lane_rebalance", "from": "heavy", "to": "light",
   "previous_heavy": N, "previous_light": M, "new_heavy": 0,
   "new_light": N + M}`. Picked up by `cmcourier analyze` (027).

### S5 dispatch

`StagedPipeline._stage_5` extended:

* If `heavy_light_lanes.enabled` is False **OR** the splitter falls
  back to single-lane → existing single-pool path (zero behavior
  change).
* Otherwise → split + dispatch to a SINGLE
  `ThreadPoolExecutor(max_workers=total)`; each `_upload_one` carries
  its lane and acquires the lane's semaphore. Two `WorkerPoolStats`
  instances (one per lane) feed the TUI.

### TUI

UPLOAD tab gains conditional dual sub-panels (only when dual mode is
active for the current batch):

* HEAVY panel: active workers, queue depth, bytes/sec, docs/sec, p95,
  current operation per worker.
* LIGHT panel: same layout.
* Single-panel layout stays exactly as-is for single-lane runs.

Rebalance events surface as TUI notifications
(`pipeline.notify("lane rebalance: 4→light")`).

### Bandwidth limiter

Already shared globally since 029. Both lanes use the same
`BandwidthLimiter`. A new property test asserts total bytes/sec stays
under `cmis.max_bandwidth_mbps` even under heavy dual-lane load.

### Acceptance — synthetic throughput proof

POST-MVP §1 demands ≥ 30% throughput improvement vs single-lane on a
bimodal batch. Achievable via synthetic test:

* 30 light docs (1 MB each) + 5 heavy docs (50 MB each) = 280 MB total.
* Mocked CMIS uploader: `time.sleep(file_size_mb * 0.05s)` (50 ms/MB).
  Predictable; head-of-line blocking IS the bottleneck.
* Single-lane wall-clock: ~17.5 s (serialized through small worker
  pool).
* Dual-lane wall-clock: ~12 s.
* Assert: `dual_lane_time ≤ single_lane_time * 0.7` (30% gain).

If the assertion is flaky in CI, gate the proof behind a
`@pytest.mark.slow` decorator + run nightly.

## Backwards compatibility

`heavy_light_lanes.enabled` defaults False → byte-identical S5 path
to pre-036. A regression test runs the same single-lane fixture
twice (once with `enabled=False`, once without the config block
entirely) and asserts identical outcomes.

## Out of scope

- Production tuning of `heavy_threshold_bytes`, `idle_threshold_s`,
  etc. Those are operator-tuned after the real-data dry run.
- Per-lane retry budgets — both lanes share the existing CMIS retry
  policy (Tenacity).
- Per-lane bandwidth quota — that is POST-MVP §8, separate change.

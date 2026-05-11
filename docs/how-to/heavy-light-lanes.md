# How-to: Heavy / Light upload lanes (036, POST-MVP §1)

Enable two adaptive upload lanes when an operator-known portion of
your batch is **substantially larger** than the rest, and you can
afford the small extra coordination cost in exchange for predictable
per-doc latency.

**Default is OFF** (`processing.heavy_light_lanes.enabled = false`).
Single-lane behavior is byte-identical to pre-036.

## When to turn this on

Turn it ON when:

- Batches are bimodal — a tail of large documents (multi-page PDFs,
  high-res TIFFs) mixed with many small ones.
- Operators care about light-doc latency, not just total wall clock.
  Light docs ship in **milliseconds** instead of queueing behind a
  heavy upload slot.
- You can pick a `heavy_threshold_bytes` value that cleanly separates
  the two populations.

Leave it OFF when:

- Document sizes are uniform.
- The batch is small (under `heavy_lane_min_batch`, default 50 — the
  splitter falls back to single-lane automatically).
- Total throughput is the only thing that matters and the heavy tail
  dominates anyway.

## What you actually gain

Be realistic about the win:

- **Latency for light docs**: significant. They stop queueing behind
  heavies.
- **Total wall clock**: modest. Synthetic benchmarks show **~5-10%**
  on heavy-dominated bimodal batches with `N=4` workers. The tail
  is still the tail.

The original POST-MVP §1 acceptance criterion wrote ≥ 30 %
throughput — that was aspirational. Production heuristics will be
tuned in the real-data dry-run phase.

## Configuration

`config.yaml`:

```yaml
processing:
  heavy_light_lanes:
    enabled: true                         # default: false
    heavy_threshold_bytes: 10485760       # default: 10 MB
    heavy_lane_min_batch: 50              # default: 50
    heavy_initial_ratio: 0.2              # default: 0.2 (20 % heavy)
    rebalance_interval_s: 10.0            # default: 10 s
    idle_threshold_s: 15.0                # default: 15 s
```

### Knob reference

| Field                  | What it does                                          | Tuning hint                                 |
| ---------------------- | ----------------------------------------------------- | ------------------------------------------- |
| `heavy_threshold_bytes` | A staged file ≥ this size goes to the heavy lane.    | Pick the inflection point in your size histogram. 10 MB is a safe default for mixed PDF/TIFF migrations. |
| `heavy_lane_min_batch`  | Batches smaller than this skip the split entirely.   | Default 50. Below that, coordination cost > parallelism gain. |
| `heavy_initial_ratio`   | Share of `cmis.workers` reserved for heavies on start. | 0.2 means 20 % of workers begin on heavies. Higher when most of the wall-clock is heavies; lower when lights are >90 % of the batch. |
| `rebalance_interval_s`  | Daemon thread tick period.                            | Keep at 10 s default. Smaller = more responsive but more CPU. |
| `idle_threshold_s`      | Time a lane must stay empty before migrating workers. | Default 15 s avoids flapping on short pauses. Drop to 1-2 s for very-fast batches; bump up for large heavies whose lane should stay reserved. |

## How rebalancing works

The `LaneController` tracks when each lane's queue first reaches
zero (`*_first_empty_at`). On every `rebalance_interval_s` tick, if
the elapsed time since that stamp exceeds `idle_threshold_s` for one
lane and the other lane still has work, the controller migrates the
drained lane's capacity to the active one. The drained side keeps a
floor of 1 (the `ResizableSemaphore` minimum) but no items remain to
acquire it, so the slot is effectively dormant.

**AIMD coupling**: when `cmis.auto_tune.enabled = true`, AIMD steers
the TOTAL worker budget; the controller redistributes between lanes
preserving the current heavy/light ratio. The two controllers do not
fight each other.

## Reading the TUI

When dual-lane mode is active for a batch, the UPLOAD tab swaps the
single WORKERS panel for two stacked HEAVY / LIGHT sub-panels:

```
 WORKERS (heavy/light · total budget 8)
  HEAVY  capacity   2   in-use   2   idle   0   queue    3
         done    17   failed    1
  LIGHT  capacity   6   in-use   5   idle   1   queue   42
         done   134   failed    0
```

The NETWORK + bandwidth chart + slow-ops sections are unchanged.

## Reading the logs

Each rebalance emits a structured log line with
`event=lane_rebalance`:

```json
{
  "event": "lane_rebalance",
  "from": "light",
  "to": "heavy",
  "previous_heavy": 2,
  "previous_light": 6,
  "new_heavy": 8,
  "new_light": 1
}
```

`cmcourier analyze batch <id>` surfaces these in its rebalance count.

## Disabling at runtime

Set `enabled: false` (or remove the block entirely) and restart.
Single-lane mode runs byte-identically to pre-036; existing batches
in-flight on the new code path will already have finished by the
restart.

## Bandwidth limiter

The shared `TokenBucket` from change 029 (`cmis.max_bandwidth_mbps`)
caps the **combined** transfer rate across both lanes. Dual-mode
does **not** double your bandwidth budget — both lanes draw from the
same global ceiling. The 029 unit test
`test_throttles_via_shared_bucket` already covers the property.

## Cross-references

- Spec: `specs/036-heavy-light-lanes/`.
- POST-MVP entry: `docs/roadmap/POST-MVP.md §1`.
- Related: change 025 (S5 worker pool + AIMD), change 029 (shared
  bandwidth limiter), change 030 (TUI multi-batch view).

# 068 — AIMD aggressive growth + soft halve for heavy-file workloads

## Why

Operator-reported during a streaming run with `mockfiles-mixed`
(50 KB → 30 MB) against Alfresco staging: bandwidth peak `<20 MB/s`
against a 300 Mbps internet link (= 37.5 MB/s theoretical max). The
UPLOAD tab showed `pool capacity 4-8` for the whole run despite
`max_threads: 50` in YAML. AIMD never reached its ceiling.

Math of the existing AIMD (`services/auto_tune.decide`):

| Tick result | Action |
|---|---|
| `p95 < 0.8 × target` | `workers + 1` |
| `p95 > 1.2 × target` | `workers // 2` |
| else | noop |

With `adjustment_interval_s: 15` and `target_p95_ms: 30000`:

* Growth: `+1` per 15 s tick → 6 → 50 workers takes 44 ticks = **11
  minutes** of uninterrupted "in slack" observations.
* Halve trigger: any tick where `p95 > 36 s`. With 30 MB files
  whose per-upload time has natural variance (server commit, TLS
  re-handshake on a dropped connection, GC pause), `p95 > 36 s`
  with N=20 samples is **easy to hit**. A single bad tick halves
  workers → loses ~6 min of growth.
* Halve floor is `min_threads` (default 2). The operator can
  bound the bottom, but the *oscillation* keeps capacity stuck at
  ~4-8 the whole run.

Per-upload throughput against Alfresco is ~2-5 MB/s for 30 MB
files (TLS + multipart + server commit). With 4-8 workers ×
~3 MB/s each = 12-24 MB/s aggregate. Matches the observed peak.

The AIMD shape is correct for **small, latency-sensitive** uploads
(its design comes from the spec, before 030 introduced batched
heavy-file workloads). For 30 MB files, growth is too slow and
halve is too aggressive.

## What

Three tunable knobs on `cmis.auto_tune` change AIMD from "additive
+1 / multiplicative ÷2" to "multiplicative-per-tick / soft halve",
with operator-tunable thresholds.

### New `AutoTuneConfig` fields

```python
class AutoTuneConfig(BaseModel):
    ...
    # 068: growth and halve become tunable. Pre-068 was hardcoded
    # to additive +1 growth, divide-by-2 halve, halve threshold at
    # 1.2 × target_p95_ms.
    growth_factor: float = Field(default=1.25, ge=1.0, le=4.0)
    halve_factor: float = Field(default=0.75, ge=0.05, le=1.0)
    halve_threshold_ratio: float = Field(default=1.5, ge=1.05, le=10.0)
```

* `growth_factor` ≥ 1.0. Each "grow" tick increases workers by
  `max(current + 1, ceil(current * growth_factor))`. The `+1`
  floor guarantees progress even at small `current`. With default
  1.25: 6 → 8 → 10 → 13 → 17 → 22 → 28 → 35 → 44 → 50 in **10
  ticks (~2.5 min at 15s/tick)**.
* `halve_factor` ≤ 1.0. Each "halve" tick reduces workers by
  `max(min_threads, ceil(current * halve_factor))`. With default
  0.75: 50 → 38, not 50 → 25. Recovery from a false-positive halve
  is much cheaper.
* `halve_threshold_ratio` is the upper bound multiplier. Halve
  fires when `p95 > halve_threshold_ratio × target_p95_ms`. With
  default 1.5 and `target_p95_ms: 30000`: halve at 45 s, not at
  36 s. More tolerance for natural variance with heavy files.

### Updated `decide()` logic

```python
upper = config.halve_threshold_ratio * config.target_p95_ms
lower = 0.8 * config.target_p95_ms  # growth threshold unchanged

if observed_p95_ms > upper:
    halved = math.ceil(current_workers * config.halve_factor)
    new_workers = max(halved, config.min_threads)
    return Decision(action="halve", workers=new_workers, ...)

if observed_p95_ms < lower:
    grown = math.ceil(current_workers * config.growth_factor)
    new_workers = min(max(current_workers + 1, grown), config.max_threads)
    return Decision(action="+N", workers=new_workers, ...)
return Decision(action="noop", ...)
```

The action label changes from `"+1"` to `"+N"` to reflect that the
step is no longer always 1. Existing diagnostics + tests must update.

### Backwards compatibility

Defaults are chosen so a YAML with `auto_tune.enabled: true` and
none of the new knobs **does** see the new behaviour. Operators
who explicitly want the pre-068 shape can set:

```yaml
auto_tune:
  growth_factor: 1.0           # additive only (degenerate to +1)
  halve_factor: 0.5            # /2
  halve_threshold_ratio: 1.2   # original threshold
```

This is documented in the CHANGELOG. The default is the new shape
because the pre-068 shape was empirically wrong for the production
workload of large files.

## Out of scope

- Reactive halve based on **error rates** (5xx counts, retries).
  Out of scope here; AIMD only looks at p95 latency.
- Per-lane AIMD (heavy lane vs light lane independent growth).
  The lane controller's drain rebalance already does this for
  per-lane *capacity* once the total budget exists. AIMD owns the
  total budget — single set of knobs.
- File-size-aware target_p95_ms (scale target with average file
  size). A future spec can plumb this if the operator's mix of
  file sizes varies significantly per run.

## Acceptance criteria

- `cmis.auto_tune.growth_factor` defaults to 1.25, range [1.0, 4.0].
- `cmis.auto_tune.halve_factor` defaults to 0.75, range [0.05, 1.0].
- `cmis.auto_tune.halve_threshold_ratio` defaults to 1.5, range
  [1.05, 10.0].
- `decide()`:
  * Grow step uses `max(current + 1, ceil(current * growth_factor))`.
  * Halve step uses `max(min_threads, ceil(current * halve_factor))`.
  * Halve fires when `p95 > halve_threshold_ratio × target_p95_ms`.
- All pre-068 unit tests of AIMD still pass after updating expected
  values to the new defaults.
- New tests cover: default growth reaches max in expected tick
  count; halve preserves more than 50% of capacity; halve threshold
  honors `halve_threshold_ratio`.
- Existing TUI display of `auto_tune_last_action` ("+1") works
  with the new `"+N"` action label.
- mypy + ruff clean.
- CHANGELOG `[0.70.0]`; pyproject 0.69.0 → 0.70.0.

## Expected operator impact

* From 6 → 50 workers in ~2.5 min (10 ticks) vs pre-068 11 min.
* A single 45+ s p95 outlier costs `ceil(current × 0.25)` workers
  instead of half. Recovery is `+25%/tick`.
* For your `mockfiles-mixed` 30 MB workload: capacity should reach
  the 50-thread ceiling within the first 3 minutes and stay there.
  Bandwidth aggregate should rise from `<20 MB/s` peak toward
  whatever Alfresco + your 300 Mbps router can sustain — typically
  somewhere in the 30-150 MB/s range depending on Alfresco's
  per-request commit time.

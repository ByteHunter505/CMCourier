# 061 — AIMD min-samples guard: stop halving on outlier-with-few-samples

## Why

The operator reported that the AIMD controller **always** issues
`halve` shortly after the first chunk's S5 upload begins. Repro
verified — and it is deterministic.

### The cause

The S5 stage records per-doc durations into a per-chunk
`MetricsRecorder`. `current_stage_p95("S5")` returns the nearest-rank
p95 of whatever samples it has. The AIMD compares that p95 against
`1.2 × target_p95_ms` and halves the worker count when it crosses.

With a **few samples** and an **outlier**, the nearest-rank p95
**becomes the outlier**. Empirical verification (target=6000, halve at
p95 > 7200):

```
6 uploads (5 normal 1.5s, 1 handshake 12s) → p95 = 12000ms  → HALVE
3 uploads (2 normal 1.5s, 1 handshake  8s) → p95 =  8000ms  → HALVE
1 sample alone of 10s                        → p95 = 10000ms  → HALVE
```

The first chunk reliably produces such an outlier:

1. `warm_connection_pool(cmis.workers)` warms only the initial worker
   count's worth of HTTP connections.
2. AIMD warmup ends at 60 s; first post-warmup tick fires.
3. By then only a handful of uploads have completed; at least one of
   the first uploads paid the TCP+TLS+JSESSIONID handshake (cold
   connection, race, or the server's first connection of the day).
4. Nearest-rank p95 with a tiny N and one big spike = the spike.
5. AIMD reads "p95 = 12000 ms", thinks the server is on fire, and
   halves the pool to `current_workers // 2`.

Subsequent chunks don't suffer — the connections stay warm in the pool,
all samples are uniform, no outlier, p95 ≈ p50 ≈ 1.5 s.

The bug is not in any specific commit — it is a property of the AIMD
algorithm interacting with a small-sample regime. Standard AIMD
implementations gate decisions on a minimum sample count for exactly
this reason.

## What

### 1. Configuration — `min_samples`

`AutoTuneConfig` gains a new field:

```python
min_samples: int = Field(default=20, ge=1)
```

Default `20` is enough that a single 30-second outlier among
~20 normal 1.5-second samples cannot dominate the p95 — and small
enough that the AIMD still reacts quickly to genuine sustained load.

### 2. `decide()` — new short-circuit branch

`decide()` takes a new keyword argument `sample_count: int` and
returns `Decision(action="insufficient_data", workers=current, timeout_s=current)`
**before** the band comparison when `sample_count < config.min_samples`.

The new action sits next to `"warmup"` semantically: it represents "we
heard the question but don't have enough data to answer responsibly".
Like `"warmup"`, it does NOT update `last_decision` on the controller,
so the TUI's "last move" line shows the most recent **real** decision,
not the temporary stall.

### 3. Provider signature — tuple

`p95_provider: Callable[[], float]` becomes
`p95_provider: Callable[[], tuple[float, int]]` — returns `(p95_ms,
sample_count)`. Both the constructor-time provider in
`StagedPipeline.__init__` and the `MultiBatchOrchestrator
._upload_p95_observer` swap-target return the tuple.

`MetricsRecorder` gains `current_stage_p95_with_count(stage) -> tuple[float, int]`
that reads the `_StageBucket.summary()` dict and returns
`(p95_ms, count)` — the lock is already held inside `summary()` so it
is atomic for both fields.

### 4. The 3 staging YAMLs

`sample/config-staging-rvabrep.yaml`,
`sample/config-staging-rvabrep-mega-heavy.yaml`,
`sample/config-staging-rvabrep-frequent-heavy-lanes.yaml` —
add `min_samples: 20` under `cmis.auto_tune` with a comment pointing
at this spec.

## Out of scope

- Changing `_percentile` (the nearest-rank algorithm). The percentile
  itself is correct; the bug is using it on too-few samples.
- Trimmed/winsorized p95 in the analyzer (`analyze batch`). The
  reported p95 stays pure; only AIMD gates on min_samples.
- Removing or shortening the existing `warmup_seconds` guard. The
  two guards layer: warmup gates on elapsed time, min_samples gates
  on sample count. Both are needed.

## Acceptance criteria

- `AutoTuneConfig.min_samples` defaults to 20, rejects `< 1`.
- `decide(..., sample_count=0, ...)` → `Decision(action="insufficient_data", ...)`
  regardless of `observed_p95_ms`. Test pins this.
- `decide(..., sample_count=5, observed_p95_ms=12000, ...)` with
  `min_samples=20` → `"insufficient_data"`, NOT `"halve"`. **Named
  regression test for the bug**.
- `decide(..., sample_count=20, observed_p95_ms=12000, ...)` with
  `min_samples=20` → `"halve"`. The guard is a floor, not a ceiling.
- `AutoTuneController._tick` treats the new action like `"warmup"` —
  no `last_decision` mutation, no `on_pool_resize` / `on_timeout_change`
  call (workers/timeout stay the same).
- `MetricsRecorder.current_stage_p95_with_count("S5")` returns
  `(0.0, 0)` for an empty stage; the right tuple for a populated one.
- The 3 staging YAMLs carry `min_samples: 20` under `auto_tune`.
- Full unit + integration suite green; mypy + ruff clean.
- `CHANGELOG.md [0.63.0]`; `pyproject.toml` 0.62.0 → 0.63.0;
  `config-reference.yaml` documents the field.

## Notes on test strategy

The regression test is the keystone: `decide` with `sample_count=5` +
high `observed_p95_ms` must NOT halve under default `min_samples=20`.
This is the test that would have caught the bug. Existing AIMD tests
get a small constant `sample_count=100` (well above default min) so
their assertions about `"halve" / "+1" / "noop"` keep holding.

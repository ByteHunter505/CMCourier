# 026 — System Metrics (Tier 5, `psutil` sampling)

> Status: **Proposed** — 2026-05-11
> Author: bitBreaker
> Predecessor: 020 (observability tiers 1–4), 025 (S5 worker pool + AIMD)
> POST-MVP roadmap reference: `docs/roadmap/POST-MVP.md §2`

---

## 1. Summary

Add the fifth observability tier promised by REBIRTH §17.4 — a
background thread that samples host- and process-level system
metrics via `psutil` at a configurable interval and emits one
JSON line per sample to `./logs/system-{date}.jsonl`. Includes
the number of *active S5 workers* (from the existing
`WorkerPoolStats`) so the AIMD auto-tune controller's behavior
can be correlated with bottleneck class (CPU / RAM / disk /
network / worker saturation).

This is the last piece of the §17.4 surface and the only one
gated by a runtime cost (psutil samples are not free at high
frequency). It does **not** ship the analysis tooling — that's
POST-MVP §3 (`cmcourier analyze`), which depends on this.

---

## 2. Motivation

- **Bottleneck attribution today is by-guess.** When a batch is
  slow we have p95 latency per stage (tier 2) and per-network
  call (tier 3), but no view of CPU saturation, RAM pressure,
  disk IO, or NIC saturation. Operators can't say *why* p95 is
  high without SSHing to the host and running `top` / `iostat`
  by hand.
- **AIMD validation is blocked without this.** 025's auto-tune
  controller defaults `target_p95_ms = 5000` — an educated
  guess. Validating that target requires knowing whether p95
  drift is upload-bound or compute-bound. Tier 5 is the
  measurement we need.
- **§3 (offline log analyzer) depends on it.** The roadmap
  explicitly notes "§3 has zero value until §2 ships".

---

## 3. Scope

### In scope

- New nested `SystemMetricsConfig` Pydantic model under
  `ObservabilityConfig.system_metrics`.
- Background sampler thread (daemon) that runs every
  `sample_interval_s`.
- JSONL output at `{log_dir}/system-{date}.jsonl`, rotated daily
  by date (not size — samples are tiny; daily rotation matches
  the existing app/metrics/network log naming).
- Sampler is wired into the existing
  `cmcourier.observability.setup.configure(...)` lifecycle so
  it starts when observability is configured and stops cleanly
  when the pipeline run ends.
- `active_workers` field on each sample, pulled from
  `WorkerPoolStats.snapshot().busy` when a pool reference has
  been registered with the sampler (`null` for runs that don't
  involve the upload pool, e.g. `doctor`).
- ≥6 unit tests + ≥1 integration test covering: defaults,
  on/off toggle, sampler start/stop, sample format, file
  rotation by date, `active_workers` propagation from
  `WorkerPoolStats`.

### Out of scope

- The `cmcourier analyze` subcommand suite (POST-MVP §3).
- A TUI panel showing live system metrics. Tier 5 is for
  *post-hoc* analysis; the TUI already shows what's needed for
  live decisions (workers busy, bandwidth, p95).
- Heuristic bottleneck classification (CPU-bound vs IO-bound
  labels). That's §3.
- Sampling at sub-second intervals. Min interval is 1.0s; the
  doc value of "1 Hz costs measurable CPU" already says this
  is the lower bound we'd ever want.

---

## 4. Requirements

### Configuration

- **REQ-001**: New `SystemMetricsConfig` Pydantic model with
  these fields:
  - `enabled: bool` — default **`True`** (always-on
    observability for production runs; opt-out for low-overhead
    environments).
  - `sample_interval_s: float` — default `5.0`; range
    `1.0 ≤ x ≤ 60.0`.
- **REQ-002**: `ObservabilityConfig.system_metrics` MUST accept
  both the structured form (`{"enabled": false, ...}`) **and**
  the legacy boolean form (`false` / `true`) via a
  `field_validator(mode="before")` that coerces the bool into
  `{"enabled": <bool>}`. Existing YAMLs that wrote
  `observability.system_metrics: false` (defensive setting per
  020's rejection) MUST keep loading.
- **REQ-003**: The pre-025 `_reject_system_metrics` validator
  is removed.
- **REQ-004**: ≥4 schema tests cover: structured form loads,
  bool-`false` legacy form coerces correctly, bool-`true` coerces
  to `enabled=True`, interval out-of-range rejected.

### Sampler implementation

- **REQ-005**: New module `cmcourier/observability/system_metrics.py`
  exporting `SystemMetricsSampler` and `SystemSample` (frozen
  dataclass).
- **REQ-006**: `SystemMetricsSampler.__init__` parameters
  (kw-only):
  - `cfg: SystemMetricsConfig`
  - `output_dir: Path`
  - `pool_stats: WorkerPoolStats | None = None`
- **REQ-007**: `start()` is idempotent (no-op when already
  running or `cfg.enabled=False`). Spawns a daemon thread named
  `cmcourier-syssampler`. `stop()` sets a `threading.Event` and
  joins with a 2.0s timeout. Both are safe to call from any
  thread.
- **REQ-008**: Each sample is a `SystemSample` dataclass with
  these fields:
  - `ts_iso: str` — ISO 8601 UTC, second precision.
  - `cpu_pct: float` — system-wide CPU% (psutil rolling delta).
  - `ram_used_mb: int` / `ram_total_mb: int`.
  - `disk_read_mbps: float` / `disk_write_mbps: float` —
    delta-based, computed against the previous sample's
    counters.
  - `net_in_mbps: float` / `net_out_mbps: float` — same
    delta-based computation as disk.
  - `process_pid: int`.
  - `process_threads: int` — `psutil.Process().num_threads()`.
  - `process_cpu_pct: float` — this process only.
  - `process_rss_mb: int` — RSS of this process.
  - `active_workers: int | None` —
    `pool_stats.snapshot().busy` when `pool_stats` is set;
    `None` otherwise.
- **REQ-009**: The first sample's delta-based fields
  (`disk_*_mbps`, `net_*_mbps`) are `0.0` (no baseline yet),
  not `null`. Subsequent samples compute deltas against the
  previous sample's counters. This avoids "first sample is
  garbage" noise.
- **REQ-010**: Each sample is appended to
  `{output_dir}/system-{YYYY-MM-DD}.jsonl` (UTF-8, newline at
  end). The date rolls at local midnight — the sampler
  re-resolves the filename on every write to support long-
  running batches that cross midnight.
- **REQ-011**: The sampler MUST NOT raise on transient
  `psutil` errors (e.g. process disappeared mid-sample). Errors
  are logged at WARNING via `cmcourier.observability.system_metrics`
  and the sample is skipped. The thread continues.
- **REQ-012**: Sampling cost MUST be measurable and bounded.
  Spec target: <1% CPU at default interval (5s). Documented
  in the change's verification step.

### Lifecycle integration

- **REQ-013**: New function
  `cmcourier.observability.system_metrics.build_sampler(config,
  log_dir) -> SystemMetricsSampler | None` that returns
  `None` when `cfg.enabled=False`, or a constructed (not yet
  started) sampler otherwise.
- **REQ-014**: `StagedPipeline` registers the sampler with its
  `WorkerPoolStats` via a setter
  `sampler.attach_pool_stats(stats)` before calling
  `sampler.start()`. The pipeline owns start/stop. The sampler
  is **not** started from `configure_observability` — it's
  tied to the *pipeline run* lifecycle, not the *logging
  setup* lifecycle (logging may be configured by `doctor`
  too).
- **REQ-015**: When `pipeline.run(...)` finishes (success or
  exception), the sampler is stopped before `run()` returns.
  A guard `finally:` block ensures `stop()` always runs.
- **REQ-016**: A new public accessor `StagedPipeline.sampler`
  (None when disabled) so the CLI / TUI integration tests can
  inspect.

### Tests

- **REQ-017**: ≥6 unit tests for `SystemMetricsSampler`:
  - start/stop is idempotent
  - thread terminates within 2s of stop
  - disabled config → start is no-op, no file created
  - first sample has 0.0 deltas
  - delta computation is correct after two samples
    (mocked psutil counters)
  - `active_workers` is `None` when no pool_stats, else
    propagates from `WorkerPoolStats.snapshot().busy`
- **REQ-018**: ≥1 integration test runs a full
  `csv-trigger-pipeline` and asserts:
  - `system-{today}.jsonl` exists after the run
  - ≥1 line written
  - Each line is valid JSON with all REQ-008 fields
  - The thread is no longer alive after `pipeline.run` returns
- **REQ-019**: Schema tests per REQ-004.

### Verification

- **REQ-020**: `pytest` MUST report ≥670 passing (≥655 + the
  new tier-5 tests).
- **REQ-021**: `mypy src/cmcourier/` clean (including new
  `psutil` import — needs `types-psutil` in pre-commit
  `additional_dependencies`).
- **REQ-022**: `ruff check` + `ruff format --check` clean.
- **REQ-023**: Documented sampling cost in the CHANGELOG entry:
  measured CPU % at default interval on the dev workstation.

---

## 5. Acceptance scenarios

1. **Default ON**: A YAML that omits the `system_metrics` block
   loads with `enabled=True, sample_interval_s=5.0`. A run
   produces `system-<today>.jsonl`.
2. **Legacy bool false**: A YAML with
   `observability.system_metrics: false` still loads (no
   error) and disables the sampler.
3. **Explicit opt-out**: A YAML with
   `observability.system_metrics: {enabled: false}` disables
   the sampler — no file created, no thread spawned.
4. **Cross-midnight**: A long-running batch crosses local
   midnight; samples after midnight land in the next day's
   file. Both files end with valid JSON lines.
5. **Process crash**: The sampler raises (e.g. `psutil`
   transient failure) — the thread logs WARNING, continues
   with the next sample, and the pipeline run is unaffected.
6. **Pipeline exception**: The pipeline raises inside `run()`
   — the sampler is still stopped before the exception
   propagates (REQ-015's `finally:`).
7. **Doctor**: `cmcourier doctor` invokes
   `configure_observability` but does NOT spawn the sampler
   (only `pipeline.run` does). No `system-<today>.jsonl` is
   created by `doctor` alone.
8. **TUI**: The two-tab TUI is unchanged — tier 5 is post-hoc
   analysis only. The PREP / UPLOAD tabs do not gain a system
   metrics panel in 026.

---

## 6. Risks

- **psutil overhead at scale**: Per-second sampling is known
  to cost measurable CPU. We default to 5s and cap at 1s
  minimum. Verification step measures actual cost.
- **Process-disappeared race**: `psutil.Process()` can raise
  if the process exits mid-sample. The sampler handles this
  (REQ-011) but it requires careful exception handling.
- **types-psutil availability**: mypy stub package needs to be
  in pre-commit's mypy `additional_dependencies` or strict
  mode fails on the new import. Already a known pattern from
  025's `textual` addition.
- **JSONL file growth**: One sample every 5s = 17,280 lines
  per day = roughly 2–5 MB / day. Daily rotation is enough; no
  size-based rotation needed.

---

## 7. Dependencies

- **Hard**: REBIRTH §17.4 (tier 5 contract), 020 (the existing
  observability surface), 025 (WorkerPoolStats — for the
  `active_workers` field).
- **Unblocks**: POST-MVP §3 (offline log analyzer), validation
  of 025's AIMD target.

---

## 8. Estimate

~3 hours across four small phases (see `tasks.md`).

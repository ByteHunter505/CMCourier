# Spec — 025-tui-workers-autotune

**Status**: Draft
**Owner**: bitBreaker
**Date**: 2026-05-10
**Predecessors**: 020 (observability), 022 (safety flags), 024 (background runner)
**Successors**: TBD (Post-MVP §1 adaptive lanes)

---

## 1. Problem

Three interlinked gaps remain before the project can run a credible
dry run with operator visibility:

1. **S5 is single-threaded.** The orchestrator's `_stage_s5` is
   a plain `for item in items:` loop. Every upload blocks the
   batch. Production-scale runs (10k+ docs) take wall-clock-hours
   when the CMIS server can sustain 5–10 concurrent uploads.
2. **No adaptive tuning.** the spec documents an `auto_tune:`
   block (AIMD on thread count + timeout). It does not exist in
   code. Static `cmis.workers` is good MVP; AIMD lets long-running
   batches react to backpressure.
3. **No live TUI.** the spec says "Every pipeline displays a
   Rich TUI with two switchable tabs (PREP / UPLOAD)". Today the
   operator stares at scrolling stderr or `tail -f logs/`. The
   observability tiers (020) capture everything, but live attended
   runs benefit from a dashboard view.

025 ships all three together because they're entangled: the TUI's
UPLOAD tab needs worker / auto-tune state to display; auto-tune
needs the worker pool to control; the worker pool needs the
adapter thread-safety review to be safe.

Post-MVP §1 (slow/fast lanes) is explicitly **deferred** to a
future change — confirmed by the spec. 025 ships a single
adaptive pool.

---

## 2. Goals

- **G1**: `_stage_s5` runs N concurrent uploads via
  `concurrent.futures.ThreadPoolExecutor`, where N is
  `config.cmis.workers` (default 4, min 1).
- **G2**: `CmisUploader` and `MetricsRecorder` are
  thread-safe under N-worker concurrent calls. No data races on
  `_folder_cache`, `_warm`, `_stage_buckets`, slow-op aggregator.
- **G3**: Optional AIMD auto-tune controller adjusts worker
  count and CMIS request timeout based on observed p95 latency
  vs `target_p95_ms`. Configurable via `cmis.auto_tune:` YAML
  block matching the spec.
- **G4**: Two-tab `textual` TUI (PREP / UPLOAD) displays live
  per-stage progress, percentiles, throughput, worker state,
  auto-tune state, bandwidth chart (1Hz, 60s rolling), recent
  uploads, slow-ops drawers. Tab navigation via `[P]` / `[U]`
  keys; `[Q]` quits.
- **G5**: TUI default-ON for `*-pipeline run` and `single-doc run`
  commands. `--no-tui` opt-out for headless
  shells. `background` command (024) keeps TUI off (per
  the spec final sentence — "exception is `cmcourier
  background`").
- **G6**: TUI bandwidth chart y-axis is `0 → cmis.max_bandwidth_mbps`
  when set (config-known ceiling); falls back to auto-scale to
  the rolling-window peak when ceiling is 0/unset.
- **G7**: Slow/Fast lanes are explicitly NOT implemented (post-MVP).
  The TUI WORKERS panel shows a single pool.

## 3. Non-goals

- **NG1**: Adaptive heavy/light lanes (the spec post-MVP).
- **NG2**: Auto-detected network interface theoretical max
  (frágil cross-host; use config ceiling).
- **NG3**: GUI / web dashboard. CLI-only.
- **NG4**: Per-worker bandwidth shaping. The existing
  `BandwidthLimiter` is global per `CmisUploader`; reused as-is.
- **NG5**: Persistent worker state across batches. Pool spins
  up at S5 start, tears down at S5 close.
- **NG6**: Hot-swap of `cmis.workers` mid-run via signal /
  SIGHUP. Only the AIMD auto-tune changes pool size mid-run.
- **NG7**: Backporting AIMD logic to S1..S4. Those stages are
  fast and CPU-bound; concurrency adds little.

---

## 4. Requirements (RFC 2119)

### Schema (`config/schema.py`)

- **REQ-001**: `CmisConfigModel` MUST add field
  `workers: int = Field(default=4, ge=1)`.
- **REQ-002**: `CmisConfigModel` MUST add field
  `auto_tune: AutoTuneConfig = Field(default_factory=AutoTuneConfig)`.
- **REQ-003**: New `AutoTuneConfig` model mirrors the spec:
  - `enabled: bool = False`
  - `min_threads: int = Field(default=2, ge=1)`
  - `max_threads: int = Field(default=50, ge=1)`
  - `target_p95_ms: float = Field(default=5000.0, gt=0)`
  - `adjustment_interval_s: int = Field(default=30, ge=1)`
  - `warmup_seconds: int = Field(default=60, ge=0)`
  - `timeout_auto_adjust: bool = True`
  - `min_timeout_s: int = Field(default=30, ge=1)`
  - `max_timeout_s: int = Field(default=600, ge=1)`
- **REQ-004**: A `@model_validator(mode="after")` MUST reject
  configs where `min_threads > max_threads` or
  `min_timeout_s > max_timeout_s`.
- **REQ-005**: Backwards-compat: existing YAMLs without
  `workers` / `auto_tune` blocks MUST keep validating
  (defaults kick in).

### S5 worker pool (`orchestrators/staged.py`)

- **REQ-006**: `_stage_s5` MUST submit each item to a
  `concurrent.futures.ThreadPoolExecutor` of size
  `config.cmis.workers`.
- **REQ-007**: The pool MUST set
  `thread_name_prefix="cmcourier-s5"` so worker labels
  (`cmcourier-s5_0`, `..._1`, …) appear in
  `threading.current_thread().name`.
- **REQ-008**: Tracking-store calls MUST remain serializable
  via the existing writer queue. Reads (`is_stage_done`,
  `is_uploaded`) MAY occur from worker threads — they use the
  reader connection (WAL mode, thread-safe by SQLite contract).
- **REQ-009**: Per-stage timing aggregation MUST stay correct
  under concurrency. `MetricsRecorder.record_stage` and the
  underlying `_StageBucket` MUST become thread-safe (mutex
  around `durations_ms.append`).
- **REQ-010**: `_SlowOpHandler` MUST become thread-safe
  (mutex around `_candidates.append`).
- **REQ-011**: `CmisUploader.ensure_folder` MUST become
  thread-safe (mutex around `_folder_cache` mutation; idempotent
  POST is OK to send twice in races).
- **REQ-012**: `CmisUploader._warmup_session` MUST become
  thread-safe (mutex around `_warm` set + read).
- **REQ-013**: Pool lifecycle: enter at `_stage_s5` start,
  exit at the end (use a `with ThreadPoolExecutor(...) as pool:`
  block). On orchestrator exception, the `as` block ensures
  shutdown.
- **REQ-014**: Per-doc work order MAY differ from the input
  list (concurrency is non-deterministic). The aggregation
  counters (`s5_done`, `failed`) MUST be correct regardless of
  order. Use `concurrent.futures.as_completed`.

### Auto-tune controller (`services/auto_tune.py`)

- **REQ-015**: New `AutoTuneController` class. Constructor
  takes the `AutoTuneConfig` and a callback to read current
  observed `p95_ms` from `MetricsRecorder`.
- **REQ-016**: A background thread invokes the controller every
  `adjustment_interval_s` once `warmup_seconds` elapsed.
- **REQ-017**: AIMD logic:
  - `if observed_p95 < 0.8 * target → +1 worker` (cap at
    `max_threads`).
  - `if observed_p95 > 1.2 * target → halve pool size, floor
    at min_threads` (MD).
  - `else: leave alone` (within target band ± 20%).
- **REQ-018**: When `timeout_auto_adjust: true`:
  - On worker count INCREASE: timeout stays.
  - On worker count DECREASE: timeout DOUBLES (clamped to
    `max_timeout_s`). Operator interpretation: "system is
    under pressure, give each call more headroom".
  - On stable target band: timeout halves toward base (clamped
    to `min_timeout_s`). Operator interpretation: "system
    healthy, tighten the screws".
- **REQ-019**: The controller MUST emit an INFO event
  `auto_tune_decision` per cycle with
  `extra={"action": "+1" | "halve" | "noop", "p95_observed_ms":
  ..., "p95_target_ms": ..., "workers_before": ..., "workers_after":
  ..., "timeout_before_s": ..., "timeout_after_s": ...}`.
- **REQ-020**: The controller MUST shut down cleanly when the
  pipeline exits (background thread joins).
- **REQ-021**: When `auto_tune.enabled: false` (default), the
  controller is NOT instantiated; pool size stays at
  `config.cmis.workers`. The TUI shows `Auto-tune: OFF`.

### Bandwidth sampling

- **REQ-022**: `MetricsRecorder` MUST gain a `_BandwidthSampler`
  that buckets `cmis_upload` event sizes by 1-second wall-clock
  windows. Keeps a 60-bucket rolling window.
- **REQ-023**: The sampler exposes `current_mbps() -> float`
  and `series(seconds=60) -> list[tuple[float, float]]`
  (timestamps, MB/s values) for the TUI chart.

### TUI

- **REQ-024**: New top-level package `cmcourier/tui/` with
  modules `app.py` (textual `App` subclass), `prep_tab.py`,
  `upload_tab.py`, `data_provider.py` (the read-only adapter
  that pulls from MetricsRecorder + WorkerPoolStats).
- **REQ-025**: New dependency: `textual` (latest stable).
  Added to `pyproject.toml`.
- **REQ-026**: PREP tab displays per-stage S0..S4 with
  progress bars + p50/p95 + counts. Refreshes at ≥4 Hz.
- **REQ-027**: UPLOAD tab displays:
  - S5 progress + done/failed/pending + percentiles.
  - WORKERS panel: pool size, busy/idle, queue depth, auto-tune
    state (target p95, observed p95, adjust countdown, current
    timeout, last decision).
  - NETWORK panel: endpoint, bandwidth current/peak, ceiling
    citation, requests/sec, retries-in-60s, JSESSIONID warm
    status.
  - Bandwidth chart: 60-bucket rolling sparkline, y=0 to
    `cmis.max_bandwidth_mbps` (config) or auto-scale (peak) if 0.
  - Recent uploads (last 10): txn_num, size, duration, status,
    worker label.
  - Slow ops (UPLOAD, top 5): rank, stage, txn_num, worker
    label, duration_ms.
- **REQ-028**: Tab switching: pressing `p`/`P` shows PREP,
  `u`/`U` shows UPLOAD, `q`/`Q` quits (after warning prompt
  "Quit and abort pipeline? [y/N]").
- **REQ-029**: TUI MUST be a separate THREAD from the pipeline
  (textual runs its own event loop). The pipeline runs in the
  main thread; the TUI subscribes via the `data_provider`
  which polls every 250ms.
- **REQ-030**: On pipeline completion (success or failure),
  the TUI MUST display a "Run complete (s5_done=N
  s5_failed=M)" overlay and wait for `[Q]` to exit (so
  operators can read the final state).
- **REQ-031**: With `--no-tui`, the TUI is not started; output
  matches the pre-025 behavior.

### CLI integration

- **REQ-032**: Each pipeline run command (`csv-trigger`,
  `rvabrep`, `as400-trigger`, `local-scan`, `single-doc`)
  MUST accept `--tui / --no-tui` (`is_flag` pair, default
  `tui=True`).
- **REQ-033**: The `background` command (024) MUST NOT
  accept `--tui` (the TUI is disabled by design for
  unattended runs).
- **REQ-034**: When stdin is not a TTY (e.g., pytest runner,
  CI), the TUI MUST auto-disable even if `--tui` is the
  default. `--tui` explicitly passed in a non-TTY context
  MUST exit 2 with a clear error.
- **REQ-035**: All existing CLI tests MUST be patched to pass
  `--no-tui` so they exercise the headless path (the same
  pattern as 022's `--skip-doctor` rollout).

### Observability integration

- **REQ-036**: Network metrics events (from 020) MUST gain a
  `worker` field (the thread name's suffix, e.g., `"w_3"`)
  for `cmis_upload` and `cmis_post`. Whitelisted in
  `ALLOWED_EXTRA_FIELDS`.
- **REQ-037**: The TUI's worker labels MUST be derived from
  the same source as the log records (no parallel scheme).

### Tests

- **REQ-038**: ≥6 schema tests cover the new fields:
  defaults, validation (min/max threads, min/max timeout),
  `auto_tune.enabled=true` loads cleanly, regression for
  YAMLs without the blocks.
- **REQ-039**: ≥6 orchestrator tests cover the worker pool:
  N=1 (sequential equivalence), N=4 (parallel happy path),
  exception in worker (other workers continue), graceful
  shutdown on KeyboardInterrupt, slow-ops correctly attribute
  worker labels, MetricsRecorder p95 correct under
  concurrency.
- **REQ-040**: ≥5 auto-tune unit tests cover the AIMD logic:
  AI under target, MD over target, noop in band, warmup
  honored, timeout adjustment (up on MD, down on stable).
- **REQ-041**: ≥4 thread-safety tests on `CmisUploader` and
  `MetricsRecorder` ensure no data races with 4 concurrent
  threads.
- **REQ-042**: ≥1 TUI smoke test renders the PREP and UPLOAD
  tabs against a synthetic data provider and asserts key
  fields appear. Use `textual.testing.AppTest` (or fall back
  to capture-text if the API is unstable).
- **REQ-043**: ≥3 CLI integration tests verify
  `--no-tui` flag works on at least 3 pipeline commands;
  `--tui` in non-TTY exits 2.

### Verification

- **REQ-044**: `pytest` MUST report ≥620 passing.
- **REQ-045**: `mypy src/cmcourier/` MUST be clean.
- **REQ-046**: `ruff check` / `ruff format --check` clean.
- **REQ-047**: Coverage on new modules
  (`services/auto_tune.py`, `tui/*`) ≥ 80%.
  Coverage on `orchestrators/staged.py` ≥ 90% (it was 96%;
  refactor must not regress).

---

## 5. Acceptance scenarios

1. **Backwards-compat config**: YAMLs from 024 keep working —
   defaults kick in (workers=4, auto_tune.enabled=False).
2. **Workers=1**: A YAML with `cmis.workers: 1` runs S5
   sequentially, identical to pre-025 behavior. Slow-op records
   show `worker=cmcourier-s5_0`.
3. **Workers=8 parallel**: A YAML with `cmis.workers: 8` runs
   S5 with 8 concurrent uploads. End-of-batch `s5_done`
   matches input doc count.
4. **Worker exception isolation**: One CMIS upload raises
   `CMISServerError` after retries exhausted; other 7 workers
   continue; batch finishes with `s5_failed=1` and the rest
   `S5_DONE`.
5. **Auto-tune AI**: 20-doc batch with `auto_tune.enabled:
   true`, `target_p95_ms: 1000`, observed p95 = 600 ms →
   after `adjustment_interval_s`, the log shows
   `auto_tune_decision action=+1`.
6. **Auto-tune MD**: 20-doc batch, observed p95 = 5000 ms,
   target 1000 → halve the pool, log
   `auto_tune_decision action=halve workers_after=N/2`.
7. **Auto-tune warmup**: No `auto_tune_decision` event before
   `warmup_seconds` elapsed.
8. **Auto-tune off**: `enabled: false` → no controller thread,
   no events, pool size constant.
9. **TUI default-on**: `cmcourier csv-trigger-pipeline run -c y.yaml`
   in a TTY starts the TUI. Operator presses `Q` after
   completion to exit.
10. **TUI --no-tui**: `cmcourier ... run -c y.yaml --no-tui`
    skips the TUI; output identical to pre-025 (interactive
    or quiet depending on context).
11. **TUI non-TTY**: pytest's CliRunner auto-disables TUI
    even without `--no-tui`. Existing tests stay green after
    sed-patch.
12. **TUI tab switch**: `P` shows PREP, `U` shows UPLOAD.
    Active tab indicated visually.
13. **TUI bandwidth chart**: With `cmis.max_bandwidth_mbps:
    50`, the chart y-axis tops at 50. Reading the recent
    plotted values matches `network-{date}.jsonl` size
    samples.
14. **TUI run-complete overlay**: After pipeline ends, the
    last screen freezes with totals; `Q` exits.
15. **Background command unchanged**: `cmcourier background
    --pipeline csv-trigger -c y.yaml` does NOT accept `--tui`
    (Click rejects unknown flag). Stays quiet on success per
    024.
16. **Existing test suite green**: All existing CLI tests
    pass after sed-patch with `--no-tui`. Behavior under
    `--no-tui` is identical to pre-025.

---

## 6. Out of scope (explicit)

- Adaptive slow/fast lanes (the spec post-MVP).
- Auto-detected network interface theoretical max.
- TUI hot-reload of config.
- Web / GUI dashboard.
- Per-worker bandwidth shaping.
- AIMD on S1..S4 stages.
- TUI playback from JSONL log files (offline mode).

---

## 7. References

- the spec — pipeline stages
- the spec — TUI by Default (two tabs)
- the spec — Adaptive Heavy / Light Upload Lanes (Post-MVP)
- the spec — `auto_tune:` config block specification
- the spec — Observability tiers (we hook into them)
- POST-MVP §1 — Adaptive lanes (deferred)
- 020 — Observability (MetricsRecorder, BandwidthLimiter)
- 022 — Auto-doctor + safety flags (--no-tui follows same pattern)
- 024 — Background runner (this change preserves the
  TUI-off-by-design behavior)

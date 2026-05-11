# 026 — Implementation Plan

> Companion to `spec.md`. Four phases, ~3h total.

---

## Phase 1 — Dependency + Schema (~30 min)

1. Add `psutil>=5.9,<7.0` to `pyproject.toml` `[project.dependencies]`.
2. Add `psutil>=5.9,<7.0` and `types-psutil>=5.9,<7.0` to
   `.pre-commit-config.yaml` mypy `additional_dependencies`.
3. Refactor `ObservabilityConfig.system_metrics`:
   - Drop the `_reject_system_metrics` validator.
   - Introduce a new `SystemMetricsConfig(BaseModel)` with
     `enabled: bool = True`, `sample_interval_s: float =
     Field(default=5.0, ge=1.0, le=60.0)`.
   - Change the field type from `bool` to `SystemMetricsConfig`
     with `default_factory=SystemMetricsConfig`.
   - Add a `field_validator("system_metrics", mode="before")`
     that converts bare `bool` inputs to
     `{"enabled": <bool>}` for backwards compat.
4. Update test_schema.py:
   - Replace `test_system_metrics_true_rejected` with the new
     coverage matrix (REQ-004): structured-true, structured-
     false, legacy-bool-false, legacy-bool-true, invalid
     interval → ValidationError.
   - Update any test that asserts `cfg.system_metrics is False`
     to `cfg.system_metrics.enabled is True` (new default ON).

**Risk**: if the validator order matters for `mode="before"`, we
may need to also disable strict-extra-forbids for that field.
The `_STRICT` config has `extra="forbid"` — make sure the
inner `SystemMetricsConfig` carries `_STRICT` too so unknown
fields under `system_metrics:` still fail loudly.

**Done when**: pytest tests/unit/config/ passes (with the
updated tests).

---

## Phase 2 — Sampler module (~60 min)

1. Create `src/cmcourier/observability/system_metrics.py` with:
   ```python
   @dataclass(frozen=True, slots=True)
   class SystemSample:
       ts_iso: str
       cpu_pct: float
       ram_used_mb: int
       ram_total_mb: int
       disk_read_mbps: float
       disk_write_mbps: float
       net_in_mbps: float
       net_out_mbps: float
       process_pid: int
       process_threads: int
       process_cpu_pct: float
       process_rss_mb: int
       active_workers: int | None
   ```
2. `SystemMetricsSampler` class:
   - `__init__(*, cfg, output_dir, pool_stats=None)`.
   - `attach_pool_stats(stats)` — late binding for when the
     sampler is built before the pipeline.
   - Internal state: `_stop: threading.Event`, `_thread:
     threading.Thread | None`, `_prev_disk_io`,
     `_prev_net_io`, `_prev_ts: float`, `_process:
     psutil.Process`.
   - `start()` — idempotent; spawns thread if
     `cfg.enabled and self._thread is None`.
   - `stop()` — sets the Event, joins with 2.0s timeout.
   - `_loop()` — runs until `_stop.is_set()`. Each iteration:
     compute sample, write JSONL, `_stop.wait(interval_s)`.
   - `_take_sample()` — returns `SystemSample`; first call has
     zero deltas.
   - `_write_sample(sample)` — open in append mode each time
     (cheap for our cadence; lets daily rotation be transparent
     via filename re-resolution). Resolved filename:
     `output_dir / f"system-{date.today().isoformat()}.jsonl"`.
   - All psutil access wrapped in `try/except (psutil.Error,
     OSError)` → log WARNING, skip sample.
3. `build_sampler(observability_cfg, log_dir)` factory:
   - Returns `SystemMetricsSampler` instance when
     `cfg.system_metrics.enabled`, else `None`.

**Risk**: psutil's `cpu_percent()` is *blocking* if called with
`interval=None` and it's the first call (returns 0.0). We need
to seed the call once in `__init__` so subsequent calls return
meaningful values.

**Done when**: 6 unit tests pass (REQ-017).

---

## Phase 3 — Pipeline lifecycle wiring (~45 min)

1. `StagedPipeline.__init__`:
   - Accept `sampler: SystemMetricsSampler | None = None`
     (default None so external callers / tests don't need to
     change).
   - If `sampler is not None`, call
     `sampler.attach_pool_stats(self._pool_stats)`.
   - Store as `self._sampler`.
2. Public accessor `StagedPipeline.sampler` (returns
   `SystemMetricsSampler | None`).
3. `StagedPipeline.run(...)`:
   - At the start, after batch_id is resolved:
     `if self._sampler: self._sampler.start()`.
   - Wrap the run body in `try: ... finally: stop_sampler()`
     so exceptions don't leak the thread.
4. `config/wiring.py::build_pipeline`:
   - Construct the sampler via
     `build_sampler(config.observability,
     config.observability.log_dir)`.
   - Thread it into `StagedPipeline(...)`.

**Risk**: `build_pipeline` already has a lot of kwargs.
Threading one more is fine but worth a quick re-read to avoid
accidentally breaking a different code path that constructs
`StagedPipeline` (e.g. tests). Plan: search for
`StagedPipeline(` callsites and verify they're all in
`build_pipeline` or contract tests that pass via positional
kwargs.

**Done when**: integration test for REQ-018 passes.

---

## Phase 4 — Docs + verification + commit (~30 min)

1. CHANGELOG `[0.28.0]` entry — feature, defaults, sampling
   cost measurement.
2. README status checklist tick (26th change).
3. POST-MVP.md — mark §2 SHIPPED with link to CHANGELOG.
4. Update `[Unreleased]` block in CHANGELOG to drop §2 from
   pending.
5. Run the full verification gate:
   - `ruff check`, `ruff format --check`
   - `mypy src/cmcourier/`
   - `pytest -q` — full suite ≥670 green
   - Manual cost measurement: run a 60-second loop, measure
     CPU% of the sampler thread, document in CHANGELOG.
6. Conventional commit + FF merge into `main`.

**Done when**: `git log` on `main` shows the FF commit and all
gates are green.

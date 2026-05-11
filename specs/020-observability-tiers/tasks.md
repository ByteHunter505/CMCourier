# Tasks — 020-observability-tiers

**Status**: Draft
**Spec**: `specs/020-observability-tiers/spec.md`
**Plan**: `specs/020-observability-tiers/plan.md`

---

## Phase 1 — Foundation (config + package + tier 1 app log)

- [ ] **1.1 (R)** Add 5 schema tests to
  `tests/unit/config/test_schema.py` for `ObservabilityConfig`
  (defaults, system_metrics rejected, log_format invalid,
  rotation_mb < 1, observability-absent regression).
- [ ] **1.2 (G)** Edit `src/cmcourier/config/schema.py`:
  - Add `ObservabilityConfig` BaseModel with REQ-001 fields.
  - Add `field_validator` rejecting `system_metrics=True`.
  - Add `observability:
    ObservabilityConfig = Field(default_factory=ObservabilityConfig)`
    to `PipelineConfig`.
  - Update `__all__`.
- [ ] **1.3 (R)** Create `tests/unit/observability/test_formatter.py`
  with 4 tests (JSON shape, text fallback, PII denylist mask, PII
  whitelist passthrough).
- [ ] **1.4 (G)** Create `src/cmcourier/observability/`:
  - `__init__.py` — public re-exports.
  - `formatter.py` — `JsonFormatter` per plan §4.1.
  - `pii.py` — `PiiMaskingFilter` per plan §4.2 + `MASK` constant.
  - `setup.py` — `configure(config, log_level, stderr_only=False)`
    per plan §3.2.
- [ ] **1.5 (G)** Edit `src/cmcourier/cli/logging_setup.py` to
  shim into `observability.setup.configure(stderr_only=True)`
  when called with no config (legacy path).
- [ ] **1.6 (G)** Edit `src/cmcourier/cli/app.py`: after
  `load_config(...)`, call `observability.setup.configure(config.observability, log_level)`
  so file handlers come up.
- [ ] **1.7** Run phase-1 tests. Iterate to green.

---

## Phase 2 — Pipeline metrics (tier 2) + batch summary

- [ ] **2.1 (R)** Create
  `tests/unit/observability/test_metrics.py` with 5 tests
  (percentile correctness, empty bucket, slow-op threshold,
  top_n cap, StageTimer outcome=FAIL on exception).
- [ ] **2.2 (G)** Add `src/cmcourier/observability/metrics.py`:
  - `_StageBucket` and `_percentile` helpers.
  - `BatchSummary` builder.
  - `StageTimer` context manager.
  - `SlowOpAggregator` per plan §4.4.
  - `_SlowOpHandler` per plan §4.7.
  - `MetricsRecorder` per plan §3.3 (owns aggregator + handler +
    file paths).
- [ ] **2.3 (R)** Create
  `tests/integration/observability/test_setup.py` with 4 tests
  (app log written, enabled=False no files, metrics handler
  writes to metrics-{date}.jsonl, JsonFormatter output shape).
- [ ] **2.4 (G)** Edit `src/cmcourier/observability/setup.py`:
  - Wire metrics file handler when
    `config.pipeline_metrics=True`.
  - Wire stderr handler with level from `log_level`.
  - Install `PiiMaskingFilter` on every handler.
- [ ] **2.5 (R)** Add 1 e2e test in
  `tests/integration/observability/test_pipeline_emits.py`:
  pipeline run writes one batch-summary line to metrics file.
- [ ] **2.6 (G)** Edit `src/cmcourier/orchestrators/staged.py`:
  - Accept optional `MetricsRecorder` in constructor.
  - Wrap per-stage doc processing in `with StageTimer(...)`.
  - At batch start: `recorder.start_batch(...)`.
  - At batch close: `recorder.close_batch(...)` emits summary.
- [ ] **2.7 (G)** Edit `src/cmcourier/config/wiring.py`: wire
  `MetricsRecorder` from `config.observability` into
  `StagedPipeline`.
- [ ] **2.8** Run phase-2 tests. Iterate to green.

---

## Phase 3 — Network metrics (tier 3) + slow ops (tier 4)

- [ ] **3.1 (R)** Add 2 e2e tests to
  `tests/integration/observability/test_pipeline_emits.py`:
  - network-{date}.jsonl populated by CMIS+AS400 calls
  - slow-ops-{batch_id}.jsonl top-N with threshold filtering
- [ ] **3.2 (G)** Edit `src/cmcourier/adapters/sources/as400.py`:
  - Add `_network_log = logging.getLogger("cmcourier.metrics.network")`.
  - Wrap `query` and `query_stream` to time + emit
    `as400_query` event with `extra={kind, duration_ms,
    sql_prefix, row_count}`.
- [ ] **3.3 (G)** Edit `src/cmcourier/adapters/upload/cmis_uploader.py`:
  - Add `_network_log`.
  - Time each HTTP request in `upload`, `ensure_folder`,
    `test_connection`, `get_type_definition`.
  - Emit `cmis_upload` / `cmis_post` / `cmis_get` events with
    `extra={kind, duration_ms, size_bytes, status, url_prefix}`.
- [ ] **3.4 (R)** Add 1 doctor test in
  `tests/integration/cli/test_doctor.py`: log_dir_writable
  FAILs for unwritable dir.
- [ ] **3.5 (G)** Edit `src/cmcourier/cli/doctor.py`:
  - Add `_check_log_dir_writable(config)` per REQ-022.
  - Append to `results` in `run_doctor()` before the
    sample_dry_run check.
- [ ] **3.6 (R)** Add 1 PII regression test in
  `tests/integration/observability/test_pipeline_emits.py`:
  passes `extra={"cif": "BAD"}` → file contains `"***"`, never
  `"BAD"`.
- [ ] **3.7** Run phase-3 tests. Iterate to green.

---

## Phase 4 — Verification + docs + commit + merge FF

- [ ] **4.1** `ruff check src/ tests/` — clean.
- [ ] **4.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **4.3** `mypy src/cmcourier/` — clean.
- [ ] **4.4** `pytest --cov=src/cmcourier --cov-report=term` —
  ≥482 pass, coverage on `observability/` ≥85%, total ≥80%.
- [ ] **4.5** `pre-commit run --all-files` — clean.
- [ ] **4.6** Smoke: `cmcourier doctor --config <fixture>` lists
  `log_dir_writable` check; `cmcourier csv-trigger-pipeline run`
  produces `./logs/app-{date}.log` + `metrics-{date}.jsonl`.
- [ ] **4.7** Update `CHANGELOG.md`:
  - Remove "Observability tiers (REBIRTH §17.4)" from Planned.
  - Add `[0.22.0] — 2026-05-10` entry: Added / Changed /
    Verification / Rationale.
- [ ] **4.8** Update `README.md` Status checklist: tick
  "Twentieth change: observability tiers 1-4 (REBIRTH §17.4)".
- [ ] **4.9** PII grep on new content. Synthetic only.
- [ ] **4.10** Stage. Commit:
  `feat(observability): add tiered structured logging (REBIRTH §17.4 tiers 1-4)`.
- [ ] **4.11** `git checkout main && git merge --ff-only feat/020-observability-tiers && git branch -d feat/020-observability-tiers`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..003 (schema) | 1.1, 1.2 |
| REQ-004..008 (package, hierarchy) | 1.3, 1.4, 1.5, 1.6, 2.4 |
| REQ-009..012 (files) | 2.2, 2.3, 2.4, 3.2, 3.3 |
| REQ-013..015 (PII) | 1.3, 1.4, 3.6 |
| REQ-016..018 (orchestrator) | 2.5, 2.6, 2.7 |
| REQ-019..021 (network events) | 3.1, 3.2, 3.3 |
| REQ-022 (doctor) | 3.4, 3.5 |
| REQ-023..028 (test counts) | covered across phases |
| REQ-029..031 (verification) | 4.1..4.6 |

---

## Estimated effort

- Phase 1: 90 min (foundation + tier 1 + 9 tests)
- Phase 2: 90 min (metrics + orchestrator + 9 tests)
- Phase 3: 90 min (network + slow ops + doctor + 4 tests)
- Phase 4: 30 min (verification + docs + merge)
- **Total**: ~5 h

---

## Notes for the implementor

- The `cmcourier.metrics.*` logger names are intentional —
  configuring file handlers by logger name keeps the orchestrator
  and adapter code blissfully unaware of where the bytes go.
- The `_SlowOpHandler` is the trick that avoids passing a
  recorder into every adapter — it intercepts records by logger
  name and filters by threshold. No constructor pollution.
- Existing call sites use `_log.info("msg")` without `extra=`.
  Don't rewrite them. Only the NEW emit points (per-stage close,
  per-network-request, batch close) need structured fields.
- The `PiiMaskingFilter` denylist is a starting point. The
  denylist can grow as new field names appear — that's the
  whole point of being conservative.
- `RotatingFileHandler(maxBytes=config.rotation_mb * 1024 * 1024,
  backupCount=5)` gives us rotation without writing custom code.
- Keep `cli/logging_setup.configure(level)` callable for the
  doctor's early-load failure path (it doesn't have a config yet).
  It calls the new entry point with `stderr_only=True`.
- The slow-ops file path includes `batch_id`, so it's created
  fresh per batch. The handler is attached at `start_batch` and
  detached at `close_batch`. No leak between batches.

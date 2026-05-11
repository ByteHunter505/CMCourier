# 026 — Tasks

> RED → GREEN per Strict TDD. Each task lists the test file
> that must exist (failing) before the implementation file is
> written.

## Phase 1 — Schema

- [ ] T1.1 — Update `tests/unit/config/test_schema.py`:
      drop `test_system_metrics_true_rejected`; add
      structured-true, structured-false, legacy-bool-false,
      legacy-bool-true, interval-out-of-range tests.
- [ ] T1.2 — Replace `system_metrics: bool` with
      `SystemMetricsConfig` model in
      `src/cmcourier/config/schema.py`. Drop the rejection
      validator. Add a `mode="before"` coercion validator.
- [ ] T1.3 — Add `psutil` + `types-psutil` to `pyproject.toml`
      and `.pre-commit-config.yaml`.

## Phase 2 — Sampler

- [ ] T2.1 — Write `tests/unit/observability/test_system_metrics.py`
      with the 6 sampler unit tests from REQ-017.
- [ ] T2.2 — Implement
      `src/cmcourier/observability/system_metrics.py`
      (`SystemSample`, `SystemMetricsSampler`,
      `build_sampler`).

## Phase 3 — Pipeline wiring

- [ ] T3.1 — Add the integration test
      `tests/integration/observability/test_system_metrics_e2e.py`
      (REQ-018) — runs a `csv-trigger-pipeline` and verifies
      `system-<today>.jsonl` lands with valid JSON lines.
- [ ] T3.2 — Modify `StagedPipeline.__init__` to accept and
      store the sampler; add `sampler` property; wrap
      `run(...)` body in `try/finally` that starts and stops
      the sampler.
- [ ] T3.3 — Modify `config/wiring.py::build_pipeline` to
      construct + pass the sampler.

## Phase 4 — Docs + verification

- [ ] T4.1 — Run sampling cost measurement (5s interval, 60s
      duration). Record CPU% in the CHANGELOG.
- [ ] T4.2 — CHANGELOG `[0.28.0]` entry + `[Unreleased]`
      reconciliation.
- [ ] T4.3 — README status checklist tick.
- [ ] T4.4 — POST-MVP.md — mark §2 SHIPPED.
- [ ] T4.5 — Full gate: ruff + mypy + pytest (≥670 green).
- [ ] T4.6 — Conventional commit + FF merge into `main`.

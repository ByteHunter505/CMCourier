# 027 — Tasks

> RED → GREEN per Strict TDD.

## Phase 1 — Log reader + report + classifier

- [ ] T1.1 — Write `tests/unit/services/test_analyze.py` with the
      16+ unit tests from `plan.md` Phase 1.
- [ ] T1.2 — Implement `src/cmcourier/services/analyze.py`
      with all the dataclasses + `LogReader` +
      `build_batch_report` + `classify_bottleneck`.

## Phase 2 — `analyze batch` CLI

- [ ] T2.1 — Write `tests/integration/cli/test_analyze.py`
      with the `analyze batch` golden-file + smoke test.
- [ ] T2.2 — Implement
      `src/cmcourier/cli/commands/analyze.py` with the
      `analyze_group` + `batch_command`.
- [ ] T2.3 — Wire `analyze_group` into
      `src/cmcourier/cli/app.py::main`.
- [ ] T2.4 — Add `format_terminal` to
      `src/cmcourier/services/analyze.py`.

## Phase 3 — `compare` + `trends`

- [ ] T3.1 — Add `compare_batches` + `compute_trends` +
      their terminal formatters with unit tests.
- [ ] T3.2 — Add `compare_command` + `trends_command` to
      the CLI module.
- [ ] T3.3 — Integration tests for both subcommands.

## Phase 4 — JSON + docs + verification

- [ ] T4.1 — Add `--format text|json` to all 3 subcommands +
      JSON formatters with unit tests.
- [ ] T4.2 — Write `docs/how-to/log-analysis.md` (classifier
      rules, sample output, known limits).
- [ ] T4.3 — `CHANGELOG.md` `[0.29.0]` entry +
      `[Unreleased]` reconciliation.
- [ ] T4.4 — `README.md` status checklist tick (27th
      change).
- [ ] T4.5 — Mark POST-MVP §3 SHIPPED in
      `docs/roadmap/POST-MVP.md`.
- [ ] T4.6 — Full gate: ruff + mypy + pytest (≥695 green).
- [ ] T4.7 — Conventional commit + FF merge into `main`.

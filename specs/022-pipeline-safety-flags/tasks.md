# Tasks — 022-pipeline-safety-flags

**Status**: Draft
**Spec**: `specs/022-pipeline-safety-flags/spec.md`
**Plan**: `specs/022-pipeline-safety-flags/plan.md`

---

## Phase 1 — Auto-doctor + `--skip-doctor`

- [ ] **1.1 (R)** Add 6 tests to
  `tests/integration/cli/test_cli.py`:
  - auto-doctor blocks when CMIS down (csv-trigger)
  - auto-doctor blocks when log_dir not writable (e2e)
  - `--skip-doctor` bypasses on csv-trigger
  - app log records `doctor_pass`
  - app log records `doctor_fail`
  - single-doc inherits auto-doctor
- [ ] **1.2 (G)** Edit `cli/app.py`:
  - Add `--skip-doctor` Click option to every pipeline run
    command (csv/rvabrep/as400/local-scan/single-doc).
  - In `_run_pipeline_command` and `single_doc_run_command`,
    insert the auto-doctor block per plan §3.2 (between
    `configure_observability` and `build_pipeline`).
  - Emit `doctor_pass` / `doctor_fail` events via the
    `cmcourier` logger.
- [ ] **1.3** Re-run existing test suite. Many CLI tests will
  now break because their fixtures don't set up complete doctor
  scaffolding. Add `--skip-doctor` to those tests so they keep
  exercising pipeline behavior only.
- [ ] **1.4** Run phase-1 tests. Iterate to green.

---

## Phase 2 — `--resume` flag

- [ ] **2.1 (R)** Add 4 tests to
  `tests/integration/cli/test_pipeline_kinds.py`:
  - `--resume` without `--batch-id` exits 2
  - `--resume` with unknown batch_id exits 1
  - `--resume` on clean batch prints "Nothing to resume"
  - `--resume` on mid-flight batch resolves
    `from_stage=<lowest pending>` and runs
- [ ] **2.2 (G)** Edit `cli/app.py`:
  - Add `--resume` flag to every pipeline run command.
  - Add `_resolve_resume_stage(config, batch_id) -> int | None`
    helper per plan §3.3.
  - Insert the resume resolution block AFTER auto-doctor and
    BEFORE `build_pipeline`.
  - When both `--resume` and `--from-stage` (non-default) are
    set, log WARNING and use `--from-stage`.
- [ ] **2.3** Run phase-2 tests. Iterate to green.

---

## Phase 3 — `doctor --check <name>` selective

- [ ] **3.1 (R)** Add 5 tests to
  `tests/integration/cli/test_doctor.py`:
  - `doctor --check connections` → only connection checks
  - `doctor --check mapping` → only mapping_completeness
  - `doctor --check metadata` → metadata_sources +
    sample_dry_run
  - `doctor --check cm-types` → only cm_type_alignment
  - `doctor --check all` → all checks (regression)
- [ ] **3.2 (G)** Edit `cli/doctor.py`:
  - Add `_CHECK_GROUPS` mapping per plan §3.1.
  - Add `selected: str = "all"` kwarg to `run_doctor`.
  - Gate each `results.append(...)` with
    `_selected_includes(name, selected)` helper.
  - Add `"Selected checks: <name>"` header line in report when
    `selected != "all"`.
- [ ] **3.3 (G)** Edit `cli/app.py`'s `doctor_command`:
  - Add `--check` Click option with `Choice(["connections",
    "mapping", "metadata", "cm-types", "all"])`, default `"all"`.
  - Pass `selected=selected_check` to `run_doctor`.
- [ ] **3.4** Run phase-3 tests. Iterate to green.

---

## Phase 4 — Verification + docs + commit + merge FF

- [ ] **4.1** `ruff check src/ tests/` clean.
- [ ] **4.2** `ruff format --check src/ tests/` clean (or apply).
- [ ] **4.3** `mypy src/cmcourier/` clean.
- [ ] **4.4** `pytest --cov` ≥550 pass; coverage stays ≥80%
  total; auto-doctor + resume + check paths in `cli/app.py` /
  `cli/doctor.py` covered ≥85%.
- [ ] **4.5** `pre-commit run --all-files` clean.
- [ ] **4.6** Smoke:
  - `cmcourier doctor --help` shows `--check`.
  - `cmcourier csv-trigger-pipeline run --help` shows
    `--skip-doctor` + `--resume`.
- [ ] **4.7** Update `CHANGELOG.md`:
  - Remove pipeline-flag bullet from Planned section.
  - Add `[0.24.0] — 2026-05-10` entry.
- [ ] **4.8** Update `README.md` Status checklist: tick
  "Twenty-second change: pipeline safety flags".
- [ ] **4.9** PII grep on new content.
- [ ] **4.10** Stage. Commit:
  `feat(cli): pipeline safety flags — auto-doctor + --resume + doctor --check`.
- [ ] **4.11** `git checkout main && git merge --ff-only feat/022-pipeline-safety-flags && git branch -d feat/022-pipeline-safety-flags`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..005 (auto-doctor) | 1.1, 1.2 |
| REQ-006..010 (--resume) | 2.1, 2.2 |
| REQ-011..015 (doctor --check) | 3.1, 3.2, 3.3 |
| REQ-016 (logging) | 1.2, 2.2, 3.2 |
| REQ-017..020 (tests) | covered across phases |
| REQ-021..023 (verification) | 4.1..4.5 |

---

## Estimated effort

- Phase 1: 60 min (impl + adapting existing tests is the work)
- Phase 2: 60 min
- Phase 3: 60 min
- Phase 4: 30 min
- **Total**: ~3 h 30 min

---

## Notes for the implementor

- The big work in Phase 1 isn't the auto-doctor block — it's
  updating existing CLI tests that don't set up complete doctor
  scaffolding to pass `--skip-doctor`. Do this systematically:
  grep `cli_runner.invoke(main, ["csv-trigger-pipeline", "run"` /
  `"rvabrep-pipeline"` / `"as400-trigger-pipeline"` /
  `"local-scan-pipeline"` / `"single-doc"`, decide per-test
  whether it should exercise auto-doctor or skip it.
- `_resolve_resume_stage` iterates S1..S5 (S0 is trigger
  acquisition, no per-doc state). The orchestrator's `from_stage`
  is 1-indexed and `from_stage > 1` requires `batch_id` — so
  returning anything ≥1 is fine.
- The `cm_type_alignment` check has a SKIP fallback when CMIS
  failed. With selective `--check`, if `cmis_connectivity` isn't
  in the selected group, just don't add cm_type_alignment at
  all — no SKIP needed.
- Use `extra={"selected_checks": selected_check}` on the doctor
  invocation log line so observability captures the filter.
- `--from-stage` already exists on every pipeline command;
  `--resume` is a new flag that, when present, overrides the
  default but loses to an explicit non-default `--from-stage`.
- Auto-doctor uses the FULL check set, never the selective one.
  REQ-014 is explicit about this.

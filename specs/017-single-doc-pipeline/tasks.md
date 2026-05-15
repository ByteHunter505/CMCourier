# Tasks — 017-single-doc-pipeline

**Status**: Draft
**Spec**: `specs/017-single-doc-pipeline/spec.md`
**Plan**: `specs/017-single-doc-pipeline/plan.md`

---

## Phase 1 — Strategy + schema

- [ ] **1.1 (R)** Add `TestSingleDocStrategy` to
  `tests/unit/services/test_trigger_strategies.py` (~5 tests per
  plan §5.1).
- [ ] **1.2 (G)** Create `src/cmcourier/services/triggers/single_doc.py`
  with `SingleDocTriggerStrategy` per plan §4.1.
- [ ] **1.3 (G)** Update `services/triggers/__init__.py` to re-export
  `SingleDocTriggerStrategy`.
- [ ] **1.4 (R)** Add 2 schema tests to
  `tests/unit/config/test_schema.py`.
- [ ] **1.5 (G)** Edit `src/cmcourier/config/schema.py`:
  - Add `SingleDocTriggerConfig(kind: Literal["single_doc"])`.
  - Add to `TriggerConfigUnion`.
  - Update `__all__`.
- [ ] **1.6** Run strategy + schema tests. Iterate to green.

---

## Phase 2 — Wiring override + CLI + doctor

- [ ] **2.1 (R)** Add 2 wiring tests to
  `tests/integration/config/test_wiring.py` per plan §5.3.
- [ ] **2.2 (G)** Edit `src/cmcourier/config/wiring.py`:
  - `build_pipeline(config, secrets, *, trigger_strategy_override=None)`.
  - `_build_trigger_strategy` for `SingleDocTriggerConfig` raises
    `ConfigurationError`.
- [ ] **2.3 (R)** Add `TestSingleDocPipeline` (~3 CLI tests) to
  `tests/integration/cli/test_pipeline_kinds.py`.
- [ ] **2.4 (G)** Edit `src/cmcourier/cli/app.py`:
  - Add `@main.group("single-doc")` + `run` command per plan §4.2.
  - Extend `_TriggerKind` Literal with `"single_doc"`.
- [ ] **2.5 (R)** Add 1 doctor test to
  `tests/integration/cli/test_doctor.py`.
- [ ] **2.6 (G)** Edit `src/cmcourier/cli/doctor.py`: add SKIP
  branch in `_check_sample_dry_run` for `SingleDocTriggerConfig`.

---

## Phase 3 — Verification

- [ ] **3.1** `ruff check src/ tests/` — clean.
- [ ] **3.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **3.3** `mypy src/cmcourier/` — clean.
- [ ] **3.4** `pytest --cov=src/cmcourier --cov-report=term` —
  coverage on `services/triggers/single_doc.py` ≥ 90%, total ≥ 80%.
- [ ] **3.5** `pre-commit run --all-files` — clean.
- [ ] **3.6** Smoke: `cmcourier --help` lists 6 commands;
  `cmcourier single-doc --help` lists `run`;
  `cmcourier single-doc run --help` lists flags.

---

## Phase 4 — Docs + commit + merge FF

- [ ] **4.1** Update `CHANGELOG.md`:
  - "Planned for next release" → the spec CLI tree, observability
    tiers, port hygiene, per-field as400_query.
  - Add `[0.19.0] — 2026-05-10` entry: Added / Changed /
    Verification / Rationale. Milestone: 5th pipeline + diagnostic
    surface complete.
- [ ] **4.2** Update `README.md` Status checklist: tick
  "Seventeenth change: single-doc-pipeline".
- [ ] **4.3** PII grep on new content. Synthetic only.
- [ ] **4.4** Stage. Commit:
  `feat(services,cli): add single-doc-pipeline (the spec diagnostic)`.
- [ ] **4.5** `git checkout main && git merge --ff-only feat/017-single-doc-pipeline && git branch -d feat/017-single-doc-pipeline`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..004 (strategy) | 1.1, 1.2 |
| REQ-005..007 (schema) | 1.4, 1.5 |
| REQ-008..009 (wiring) | 2.1, 2.2 |
| REQ-010..012 (CLI) | 2.3, 2.4 |
| REQ-013 (doctor SKIP) | 2.5, 2.6 |

---

## Estimated effort

- Phase 1: 60 min
- Phase 2: 60 min
- Phase 3: 20 min
- Phase 4: 20 min
- **Total**: ~2 h 40 min

---

## Notes for the implementor

- `SingleDocTriggerStrategy` doesn't need a `RvabrepColumnsConfig`
  or any data source — it carries the trigger directly. Constructor
  is tiny.
- The CLI command bypasses the discriminator's dispatch by passing
  `trigger_strategy_override`. The wiring's `_build_trigger_strategy`
  is NOT reached for single_doc kind UNLESS some non-CLI caller
  invokes `build_pipeline` without the override — that's the
  rejection path.
- The doctor's `_check_sample_dry_run` short-circuits BEFORE
  building the pipeline. Order matters: SKIP is checked first;
  otherwise `build_pipeline` raises and the check would report FAIL
  (which is technically correct but less informative for operators).
- The `--cif` flag is optional. Empty string is treated same as
  None — the strategy normalizes via `cif if cif else None`.
- The `--from-stage` and `--batch-id` flags work the same as the
  other pipelines: resume an in-flight migration.
- `_apply_overrides(config, triggers_override=None, batch_size=...)`
  is called from the single-doc command for batch-size override
  only. The triggers_override path is irrelevant for single_doc
  (and the helper already handles `triggers_override=None`).

# Tasks — 016-local-scan-pipeline

**Status**: Draft
**Spec**: `specs/016-local-scan-pipeline/spec.md`
**Plan**: `specs/016-local-scan-pipeline/plan.md`

---

## Phase 1 — LocalScanTriggerStrategy

- [ ] **1.1** Edit `src/cmcourier/services/triggers/direct_rvabrep.py`:
  add `file_name_column: str = "ABAJCD"` to `RvabrepColumnsConfig`.
- [ ] **1.2 (R)** Create `tests/unit/services/test_local_scan.py` (or
  add `TestLocalScanStrategy` to `test_trigger_strategies.py`) with
  ~10 tests per plan §5.1. Confirm ImportError.
- [ ] **1.3 (G)** Create `src/cmcourier/services/triggers/local_scan.py`
  with the real `LocalScanTriggerStrategy` implementation per
  plan §4.1.
- [ ] **1.4** Edit `src/cmcourier/services/triggers/stubs.py`: remove
  `LocalScanTriggerStrategy`. With nothing left, DELETE
  `stubs.py` entirely.
- [ ] **1.5** Edit `src/cmcourier/services/triggers/__init__.py`:
  re-export `LocalScanTriggerStrategy` from `local_scan` module
  (replacing the prior import from `stubs`).
- [ ] **1.6** Edit `tests/unit/services/test_trigger_strategies.py`:
  remove `TestStubStrategies` class (no stubs remain).
- [ ] **1.7** Run trigger-strategies tests. Iterate to green.

---

## Phase 2 — Schema + wiring + CLI

- [ ] **2.1 (R)** Edit `tests/unit/config/test_schema.py`: add 3 tests
  for `kind=local_scan` per plan §5.2.
- [ ] **2.2 (G)** Edit `src/cmcourier/config/schema.py`:
  - Add `LocalScanTriggerConfig(kind: Literal["local_scan"], scan_path: DirectoryPath)`.
  - Add to `TriggerConfigUnion` members and `__all__`.
- [ ] **2.3 (G)** Edit `src/cmcourier/config/wiring.py`:
  - Import `LocalScanTriggerConfig` + `LocalScanTriggerStrategy`.
  - Add `local_scan` branch in `_build_trigger_strategy`.
- [ ] **2.4 (R)** Edit `tests/integration/config/test_wiring.py`: 1
  new test for the local_scan dispatch.
- [ ] **2.5 (G)** Edit `src/cmcourier/cli/app.py`:
  - Add `@main.group(name="local-scan-pipeline")` + `run` command.
  - Use `_run_pipeline_command(..., expected_kind="local_scan", ...)`.
  - Omit `--triggers` flag.
- [ ] **2.6 (R)** Edit `tests/integration/cli/test_pipeline_kinds.py`:
  add `TestLocalScanPipeline` with 3 tests (help, happy path, kind
  mismatch).
- [ ] **2.7** Run wiring + CLI tests. Iterate to green.

---

## Phase 3 — End-to-end + verification

- [ ] **3.1** `ruff check src/ tests/` — clean.
- [ ] **3.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **3.3** `mypy src/cmcourier/` — clean.
- [ ] **3.4** `pytest --cov=src/cmcourier --cov-report=term` —
  coverage on `services/triggers/local_scan.py` ≥ 90%, total ≥ 80%.
- [ ] **3.5** `pre-commit run --all-files` — clean.
- [ ] **3.6** Smoke: `cmcourier --help` lists 5 commands including
  `local-scan-pipeline`.

---

## Phase 4 — Docs + commit + merge FF

- [ ] **4.1** Update `CHANGELOG.md`:
  - "Planned for next release" → single-doc, REBIRTH §11 batch/
    inspect CLI, observability tiers, port hygiene cleanup.
  - Add `[0.18.0] — 2026-05-10` entry: Added / Changed /
    Verification / Rationale. Milestone: all four production
    pipelines shipped.
- [ ] **4.2** Update `README.md` Status checklist: tick "Sixteenth
  change: local-scan-pipeline".
- [ ] **4.3** PII grep on new content. Synthetic only.
- [ ] **4.4** Stage all files. Commit:
  `feat(services,cli): add local-scan-pipeline (REBIRTH §5.1 mode 4)`.
- [ ] **4.5** `git checkout main && git merge --ff-only feat/016-local-scan-pipeline && git branch -d feat/016-local-scan-pipeline`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..005 (strategy) | 1.3 + test_local_scan |
| REQ-006..008 (schema) | 2.2 + test_schema |
| REQ-009..010 (wiring) | 2.3 + test_wiring |
| REQ-011 (RvabrepColumnsConfig) | 1.1 + column-override test |
| REQ-012 (CLI) | 2.5 + test_pipeline_kinds |
| REQ-013 (doctor unchanged) | implicit — existing doctor tests survive |
| REQ-014 (logging) | 1.3 + warning test |

---

## Estimated effort

- Phase 1: 60 min
- Phase 2: 75 min
- Phase 3: 30 min
- Phase 4: 20 min
- **Total**: ~3 h 5 min

---

## Notes for the implementor

- `Path.iterdir()` returns entries in filesystem order, which is
  not stable across platforms. Tests use sets for the trigger
  emission assertions.
- The two-extension filter (`.PDF` + `.001`) is hard-coded —
  REBIRTH §3.4 guarantees these are the only first-page identifiers.
  A future per-pattern flag is out of scope.
- `stubs.py` is fully retired. The historical 006-trigger-service
  spec is unchanged; that history stands.
- The CLI command omits `--triggers` (the override flag) because
  there's no analogous concept for local_scan. Operators who want
  to point at a different folder edit the YAML or use `--config`.
- `LocalScanTriggerStrategy.acquire` raises `ConfigurationError` (a
  domain exception) when the scan path is missing. This is
  consistent with the project's "wrong configuration fails loud at
  the boundary" pattern.
- The strategy emits one TriggerRecord per matched ROW, NOT per
  matched FILE. A single file might match multiple RVABREP rows
  (rare but possible — e.g., re-archived with a different
  shortname). The downstream IndexingService dedupes by
  `(shortname, system_id)` already.

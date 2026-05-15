# Tasks — 013-doctor

**Status**: Draft
**Spec**: `specs/013-doctor/spec.md`
**Plan**: `specs/013-doctor/plan.md`

---

## Phase 1 — IUploader port + CmisUploader.get_type_definition

- [ ] **1.1** Edit `src/cmcourier/domain/ports.py`: add abstract
  `get_type_definition(self, object_type_id: str) -> Mapping[str, Any]`
  on `IUploader`.
- [ ] **1.2** Edit `tests/unit/domain/test_ports.py`: include
  `"get_type_definition"` in the IUploader abstract-method set.
- [ ] **1.3 (R)** Edit `tests/integration/adapters/test_cmis_uploader.py`:
  add `TestGetTypeDefinition` with 3 tests (200 → returns dict; 404
  → raises `CMISClientError`; 500 → raises `CMISServerError`).
- [ ] **1.4 (G)** Edit `src/cmcourier/adapters/upload/cmis_uploader.py`:
  implement `get_type_definition` per plan §3.4. Calls
  `_warmup_session` if not warm; uses `params=` for the query
  string; raises `CMISClientError` / `CMISServerError` directly
  (no retry loop).
- [ ] **1.5** Run the new tests + existing CMIS tests: `pytest
  tests/integration/adapters/test_cmis_uploader.py
  tests/unit/domain/test_ports.py -v`. Confirm green.

---

## Phase 2 — Doctor module

- [ ] **2.1 (R)** Create `tests/integration/cli/test_doctor.py` with
  the ~10 tests per plan §5.1, importing
  `cmcourier.cli.doctor.run_doctor` (yet-to-exist). Reuse the YAML
  builder from `test_cli.py` (extract to conftest.py if duplicated).
- [ ] **2.2 (R)** Run `pytest tests/integration/cli/test_doctor.py -v`.
  Confirm collection ImportError on `cmcourier.cli.doctor`.
- [ ] **2.3 (G)** Create `src/cmcourier/cli/doctor.py`:
  - `CheckStatus`, `CheckResult`, `DoctorReport` types per plan §3.1, §3.2.
  - `_frozen(d)` helper returning a `MappingProxyType` over `dict(d)`.
  - `_fail(name, exc, base_details)` helper for FAIL CheckResults.
  - `_skip(name, reason)` helper for SKIP CheckResults.
  - `_try(stage, fn)` helper for the dry-run check.
  - 6 `_check_<name>` functions per plan §4.2-§4.3.
  - `run_doctor(config, secrets)` per plan §4.1.
- [ ] **2.4 (G)** Run the doctor tests. Iterate until green.
- [ ] **2.5 (Rf)** Verify every method ≤ 50 lines. Extract helpers if
  the dry-run grows.

---

## Phase 3 — CLI `doctor` command

- [ ] **3.1 (R)** Add 3 CLI tests to `tests/integration/cli/test_doctor.py`:
  - `cli_runner.invoke(main, ["doctor", "--config", str(yaml)])` →
    exit 0; stdout has `[PASS]` lines.
  - Same with a misconfigured YAML that produces a FAIL → exit 1.
  - Missing config file → exit 2 (Click's path-exists rejection).
- [ ] **3.2 (G)** Edit `src/cmcourier/cli/app.py`:
  - Add `@main.command("doctor")` with `--config` and `--log-level`
    options.
  - Body: configure_logging → load_config + load_secrets (exit 2 on
    error) → `run_doctor(...)` → `_emit_report(report)` → exit 0/1.
  - Extract `_emit_report(report)` helper that prints one line per
    check + a summary.
- [ ] **3.3 (G)** Run all CLI tests. Confirm green.

---

## Phase 4 — Verification + docs + commit + merge FF

- [ ] **4.1** `ruff check src/ tests/` — clean.
- [ ] **4.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **4.3** `mypy src/cmcourier/` — clean.
- [ ] **4.4** `pytest --cov=src/cmcourier --cov-report=term-missing` —
  coverage on `cli/doctor.py` ≥ 85%, total ≥ 80%.
- [ ] **4.5** `pre-commit run --all-files` — clean.
- [ ] **4.6** Smoke: `cmcourier doctor --help` lists `--config` and
  `--log-level`.
- [ ] **4.7** Update `CHANGELOG.md`:
  - "Planned for next release" → additional pipelines + the spec
    CLI tree (`batch list/status/retry-failed`, `inspect`).
  - Add `[0.15.0] — 2026-05-10` entry: Added / Changed / Verification
    / Rationale. Milestone: pre-flight validation.
- [ ] **4.8** Update `README.md` Status checklist: tick "Thirteenth
  change: pre-flight `doctor` command".
- [ ] **4.9** PII grep on new files. Synthetic only.
- [ ] **4.10** Stage all files:
  ```
  modified: CHANGELOG.md
  modified: README.md
  modified: src/cmcourier/domain/ports.py
  modified: src/cmcourier/adapters/upload/cmis_uploader.py
  modified: src/cmcourier/cli/app.py
  added:    src/cmcourier/cli/doctor.py
  modified: tests/unit/domain/test_ports.py
  modified: tests/integration/adapters/test_cmis_uploader.py
  added:    tests/integration/cli/test_doctor.py
  modified: tests/integration/cli/conftest.py    # only if shared YAML extracted
  added:    specs/013-doctor/{spec,plan,tasks}.md
  ```
- [ ] **4.11** Commit `feat(cli): add doctor pre-flight command` (full body per template).
- [ ] **4.12** `git checkout main && git merge --ff-only feat/013-doctor && git branch -d feat/013-doctor`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..003 (port + uploader) | 1.1..1.5 |
| REQ-004..008 (doctor types + run_doctor) | 2.3 + TestRunDoctorHappyPath |
| REQ-009..014 (6 checks) | 2.3 + per-check tests |
| REQ-015..018 (CLI) | 3.2 + TestCli |
| REQ-019..020 (logging discipline) | 2.3 _frozen/_fail helpers strip values |
| NFR-002 (coverage) | 4.4 |
| NFR-003 (50-line cap) | 2.5 |

---

## Estimated effort

- Phase 1 (port + uploader): 40 min
- Phase 2 (doctor module + tests): 90 min
- Phase 3 (CLI + tests): 30 min
- Phase 4 (verification + docs + commit + merge): 25 min
- **Total**: ~3 h 25 min

---

## Notes for the implementor

- `cmisselector=typeDefinition` returns the type's JSON description.
  Empty body is unusual; treat parse failure as `{}` and let the
  doctor's check decide (presence of `id` key in the response is a
  reasonable signal but not required for 013).
- For test fixtures, the existing modelo_documental.csv references
  4 distinct cm_object_types (after the FF17 duplicate is dropped):
  `$t!-2_BAC_01_02_04_01_01v-1`, `$t!-2_BAC_02_01_03_01_01v-1`,
  `$t!-2_BAC_03_01_01_01_01v-1`, `$t!-2_BAC_04_01_01_01_01v-1`, ... etc.
  Each test registering the typeDefinition stubs should register one
  per unique type.
- The conftest helper for the YAML can be extracted to
  `tests/integration/cli/conftest.py` to share with `test_doctor.py`.
  Keep `test_cli.py`'s copy if extraction proves more friction than
  reuse.
- `enum.StrEnum` (Python 3.11+) makes `CheckStatus.PASS == "PASS"`.
  The CLI emits `result.status.value` for human-readable output.
- The CLI's `_emit_report` should iterate `result.details.items()`
  in sorted key order for deterministic test assertions.
- Dry-run S4 writes a PDF. Best-effort delete via `unlink(missing_ok=True)`.
  Failing to delete is logged but doesn't fail the check (it's a
  diagnostic, not a workflow step).

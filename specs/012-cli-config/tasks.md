# Tasks — 012-cli-config

**Status**: Draft
**Spec**: `specs/012-cli-config/spec.md`
**Plan**: `specs/012-cli-config/plan.md`

---

## Phase 1 — PyYAML dep + Pydantic schema

- [ ] **1.1** Add `"PyYAML>=6.0,<7.0"` to `pyproject.toml` runtime deps.
- [ ] **1.2** `pip install -e .[dev]` and verify `python -c "import yaml; print(yaml.safe_load('a: 1'))"`.
- [ ] **1.3 (R)** Create `tests/unit/config/__init__.py` (empty marker).
- [ ] **1.4 (R)** Create `tests/unit/config/test_schema.py` with ~6 tests per plan §5.1. Confirm ImportError on `cmcourier.config.schema`.
- [ ] **1.5 (G)** Create `src/cmcourier/config/schema.py` per plan §3.1. Use `pydantic.BaseModel` + `ConfigDict(frozen=True, extra="forbid")` for every model. Use `FilePath` for required-to-exist inputs and `Path` for outputs.
- [ ] **1.6 (G)** Run `pytest tests/unit/config/test_schema.py -v`. Iterate until green.

---

## Phase 2 — YAML loader + Secrets

- [ ] **2.1 (R)** Create `tests/unit/config/test_loader.py` with ~6 tests per plan §5.2. Use `tmp_path` for YAML files and `monkeypatch.setenv` / `delenv` for env vars.
- [ ] **2.2 (G)** Create `src/cmcourier/config/loader.py` with `Secrets`, `load_config`, `load_secrets`. Wrap `yaml.YAMLError` and `pydantic.ValidationError` in `ConfigurationError`.
- [ ] **2.3 (G)** Run `pytest tests/unit/config/test_loader.py -v`. Iterate until green.

---

## Phase 3 — Adapter factory (wiring)

- [ ] **3.1 (R)** Create `tests/integration/config/__init__.py` and `tests/integration/config/test_wiring.py` with ~3 tests per plan §5.3.
- [ ] **3.2 (G)** Create `src/cmcourier/config/wiring.py` with `build_pipeline(config, secrets)` + the private converters `_indexing_columns_from_schema`, `_mapping_columns_from_schema`, `_metadata_config_from_schema` per plan §4.3.
- [ ] **3.3 (G)** Update `src/cmcourier/config/__init__.py` to re-export `PipelineConfig`, `Secrets`, `load_config`, `load_secrets`, `build_pipeline`.
- [ ] **3.4 (G)** Run `pytest tests/integration/config/test_wiring.py -v`. Iterate until green.

---

## Phase 4 — CLI command + logging

- [ ] **4.1 (R)** Create `tests/fixtures/cli/valid_config.yaml` matching the pipeline fixtures (rvabrep.csv, modelo_documental.csv, clients.csv, assembly fixtures, tracking in tmp). The YAML's `cmis.base_url` must match the test stubs (`http://cmis.example.test:9080/opencmcmis/browser`).
- [ ] **4.2 (R)** Create `tests/integration/cli/__init__.py`, `tests/integration/cli/conftest.py` (autouse logging-reset fixture + `cli_runner` fixture), and `tests/integration/cli/test_cli.py` with ~8 tests per plan §5.4.
- [ ] **4.3 (G)** Create `src/cmcourier/cli/logging_setup.py` per plan §4.5.
- [ ] **4.4 (G)** Replace `src/cmcourier/cli/app.py` with the Click root group + `csv-trigger-pipeline run` command per plan §4.4. Extract helpers `_apply_overrides` and `_emit_summary` to keep the command body short. Keep every method ≤ 50 lines.
- [ ] **4.5 (G)** Run `pytest tests/integration/cli/test_cli.py -v`. Iterate until green.

---

## Phase 5 — Verification

- [ ] **5.1** `ruff check src/ tests/` — clean.
- [ ] **5.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **5.3** `mypy src/cmcourier/` — clean.
- [ ] **5.4** `pytest --cov=src/cmcourier --cov-report=term-missing` — combined coverage on the 4 new modules ≥ 85%, total ≥ 80%.
- [ ] **5.5** `pre-commit run --all-files` — clean.
- [ ] **5.6** Smoke test the installed entry point: `which cmcourier && cmcourier --help`.

---

## Phase 6 — Docs + commit + merge FF

- [ ] **6.1** Update `CHANGELOG.md`:
  - "Planned for next release" → additional pipelines (rvabrep, as400, local-scan, single-doc) + REBIRTH §11 CLI tree.
  - Add `[0.14.0] — 2026-05-10` entry: Added / Changed / Verification / Rationale. Milestone: **MVP CLI usable end-to-end**.
- [ ] **6.2** Update `README.md` Status checklist: tick "Twelfth change: CLI + Pydantic config + YAML loader". Add a "Getting started — first run" subsection with the `export CMIS_USERNAME=... && cmcourier csv-trigger-pipeline run --config config/config.yaml` invocation.
- [ ] **6.3** PII grep on new files. Synthetic only.
- [ ] **6.4** Stage all files. Expected status:
  ```
  modified: CHANGELOG.md
  modified: README.md
  modified: pyproject.toml
  added:    src/cmcourier/cli/app.py            # full impl
  added:    src/cmcourier/cli/logging_setup.py
  modified: src/cmcourier/config/__init__.py
  added:    src/cmcourier/config/schema.py
  added:    src/cmcourier/config/loader.py
  added:    src/cmcourier/config/wiring.py
  added:    tests/unit/config/{__init__.py,test_schema.py,test_loader.py}
  added:    tests/integration/config/{__init__.py,test_wiring.py}
  added:    tests/integration/cli/{__init__.py,conftest.py,test_cli.py}
  added:    tests/fixtures/cli/valid_config.yaml
  added:    specs/012-cli-config/{spec,plan,tasks}.md
  ```
- [ ] **6.5** Commit `feat(cli): add csv-trigger-pipeline run command with Pydantic config` (full body per template).
- [ ] **6.6** `git checkout main && git merge --ff-only feat/012-cli-config && git branch -d feat/012-cli-config`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001 (PyYAML) | 1.1, 1.2 |
| REQ-002..007 (schema) | 1.5 + test_schema.py |
| REQ-008..011 (loader) | 2.2 + test_loader.py |
| REQ-012..013 (secrets) | 2.2 + test_loader.py |
| REQ-014..016 (wiring) | 3.2 + test_wiring.py |
| REQ-017..022 (CLI) | 4.4 + test_cli.py |
| REQ-023..024 (logging) | 4.3 + test_cli.py log-level test |
| NFR-002 (coverage) | 5.4 |

---

## Estimated effort

- Phase 1 (dep + schema): 45 min
- Phase 2 (loader): 30 min
- Phase 3 (wiring): 45 min
- Phase 4 (CLI): 45 min
- Phase 5 (verification): 20 min
- Phase 6 (docs + commit + merge): 15 min
- **Total**: ~3 h 20 min

---

## Notes for the implementor

- Pydantic v2 `FilePath` does NOT support relative paths against an
  arbitrary base — the YAML loader resolves paths AS WRITTEN. If the
  CLI is invoked from `./project_root` but the config has
  `csv_path: data/triggers.csv`, the resolution is relative to CWD,
  not to the config file's directory. This is documented in the
  loader docstring; tests use absolute paths under `tmp_path` to
  sidestep the issue.
- `model_copy(update={...})` shallow-copies. For nested overrides
  (`--triggers` updates `config.trigger.csv_path`), build the nested
  model explicitly: `config.trigger.model_copy(update={...})`, then
  wrap in the top-level copy.
- `click.testing.CliRunner(mix_stderr=False)` keeps stdout and
  stderr separable in the result object. Tests assert on
  `result.stdout` vs `result.stderr` accordingly.
- The `--config` flag uses `click.Path(exists=True, dir_okay=False)`
  to fail fast on a missing file at the CLI layer; the loader's
  defensive `is_file()` check is still kept for the library entry.
- Logging reset MUST happen at the start of every test (autouse) AND
  at teardown. Re-invocations of `configure(level)` are idempotent
  by design (REQ-023's "replaces existing handlers").
- For env-var tests, use `monkeypatch.setenv` and
  `monkeypatch.delenv(name, raising=False)`. NEVER write to
  `os.environ` directly.
- The smoke test `cmcourier --help` (task 5.6) verifies the
  console-script wiring in `pyproject.toml`. If `pip install -e .`
  didn't pick up the entry, that step is a no-op.

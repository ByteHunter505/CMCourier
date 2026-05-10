# Tasks — 014-as400-pipelines

**Status**: Draft
**Spec**: `specs/014-as400-pipelines/spec.md`
**Plan**: `specs/014-as400-pipelines/plan.md`

---

## Phase 1 — AS400DataSource adapter

- [ ] **1.1 (R)** Create `tests/integration/adapters/test_as400.py` with
  `_FakeAs400Cursor`, `_FakeAs400Connection`, `_fake_connect` helpers
  + ~12 tests per plan §5.1. Confirm ImportError.
- [ ] **1.2 (G)** Create `src/cmcourier/adapters/sources/as400.py`:
  - Lazy `import pyodbc` (inside `_connect()` and `_extract_sqlstate`).
  - `As400DataSource(host, port, database, driver, username, password, table)`.
  - `_connect()`, `_build_connection_string()`, `_extract_sqlstate(exc)`.
  - All IDataSource methods per plan §4.
- [ ] **1.3 (G)** Re-export from `src/cmcourier/adapters/sources/__init__.py`.
- [ ] **1.4** Run AS400 tests. Iterate to green.

---

## Phase 2 — StagedPipeline rename

- [ ] **2.1** `git mv src/cmcourier/orchestrators/csv_trigger.py
  src/cmcourier/orchestrators/staged.py`. Edit the file:
  - Class name → `StagedPipeline`.
  - Docstring updated.
- [ ] **2.2** Edit `src/cmcourier/orchestrators/__init__.py`:
  re-export `StagedPipeline` (drop `CsvTriggerPipeline`).
- [ ] **2.3** Find/replace `CsvTriggerPipeline` → `StagedPipeline`
  in every test file. Imports go from `cmcourier.orchestrators.csv_trigger`
  to `cmcourier.orchestrators.staged`.
- [ ] **2.4** Edit `src/cmcourier/config/wiring.py` and
  `src/cmcourier/cli/doctor.py` to import `StagedPipeline` from
  `cmcourier.orchestrators.staged`.
- [ ] **2.5** Run `pytest` — every test that was green before MUST be
  green now. Zero new test logic this phase.

---

## Phase 3 — Schema discriminated union

- [ ] **3.1 (R)** Add 5 tests to `tests/unit/config/test_schema.py`
  per plan §5.3.
- [ ] **3.2 (G)** Edit `src/cmcourier/config/schema.py`:
  - Add `Literal` import from `typing`.
  - `CsvTriggerConfig` gets `kind: Literal["csv"] = "csv"`.
  - New `RvabrepFiltersModel`, `RvabrepTriggerConfig`,
    `As400ConnectionConfig`, `As400TriggerConfig`.
  - `TriggerConfigUnion = Annotated[..., Field(discriminator="kind")]`.
  - `PipelineConfig.trigger: TriggerConfigUnion`.
- [ ] **3.3 (G)** Edit `src/cmcourier/config/loader.py`:
  - In `load_config`, after parsing YAML, if `data["trigger"]` is a
    dict without `kind` AND no `kind`-specific fields (e.g.,
    `filters` or `query`) — inject `kind: "csv"`. Documented in
    loader docstring.
- [ ] **3.4** Run schema tests. Iterate to green.
- [ ] **3.5** Re-run the FULL test suite (`pytest`). Most existing
  tests should still pass via the csv default. Fix any breakage.

---

## Phase 4 — Real As400TriggerStrategy + 2 CLI commands

- [ ] **4.1 (G)** Create `src/cmcourier/services/triggers/as400.py`
  with `As400TriggerStrategy(source, query, columns)`. Iterates
  `source.query(query, [])` and yields TriggerRecord.
- [ ] **4.2 (G)** Delete the `As400TriggerStrategy` stub from
  `services/triggers/stubs.py`. Update `services/triggers/__init__.py`
  to re-export from the new module.
- [ ] **4.3 (G)** Edit `src/cmcourier/config/wiring.py`:
  - `_build_trigger_strategy(trigger_cfg, secrets, indexing_src)`
    helper that dispatches by `trigger_cfg.kind`.
  - `build_pipeline` invokes the helper.
- [ ] **4.4 (G)** Edit `src/cmcourier/cli/app.py`:
  - Extract `_run_pipeline_command(config_path, *, expected_kind, ...)`
    helper.
  - `csv-trigger-pipeline run` now wraps the helper with `expected_kind="csv"`.
  - Add `@main.group("rvabrep-pipeline")` + `run` command with
    `expected_kind="rvabrep"`.
  - Add `@main.group("as400-trigger-pipeline")` + `run` command with
    `expected_kind="as400"`.
- [ ] **4.5 (R)** Create `tests/integration/cli/test_rvabrep_pipeline.py`
  and `tests/integration/cli/test_as400_pipeline.py` per plan §5.5.
- [ ] **4.6 (R)** Add 3 tests to `tests/integration/config/test_wiring.py`
  per plan §5.4 (rvabrep dispatch, as400 dispatch with mocked pyodbc,
  as400 missing-secret rejection).
- [ ] **4.7 (G)** Run all CLI + wiring tests. Iterate to green.

---

## Phase 5 — Doctor as400_connectivity + verification

- [ ] **5.1 (R)** Add 2 tests to `tests/integration/cli/test_doctor.py`:
  - `as400_connectivity` SKIPs when `kind != "as400"`.
  - `as400_connectivity` PASSes with mocked pyodbc.
- [ ] **5.2 (G)** Edit `src/cmcourier/cli/doctor.py`:
  - New `_check_as400_connectivity(config, secrets)`.
  - Insert into `run_doctor` order BETWEEN cmis_connectivity and
    tracking_openable.
- [ ] **5.3** `ruff check src/ tests/` — clean.
- [ ] **5.4** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **5.5** `mypy src/cmcourier/` — clean.
- [ ] **5.6** `pytest --cov=src/cmcourier --cov-report=term` —
  combined coverage on the 3 new modules ≥ 85%, total ≥ 80%.
- [ ] **5.7** `pre-commit run --all-files` — clean.
- [ ] **5.8** Smoke: `cmcourier --help` lists 4 commands;
  `cmcourier rvabrep-pipeline --help`,
  `cmcourier as400-trigger-pipeline --help` show the run sub-command.

---

## Phase 6 — Docs + commit + merge FF

- [ ] **6.1** Update `CHANGELOG.md`:
  - "Planned for next release" → AS400 metadata source `as400:*`
    support, `local-scan-pipeline`, `single-doc`, REBIRTH §11 batch/
    inspect tree.
  - Add `[0.16.0] — 2026-05-10` entry: Added / Changed / Verification
    / Rationale. Milestone: **multi-pipeline + AS400 production-ready**.
- [ ] **6.2** Update `README.md` Status checklist: tick "Fourteenth
  change: AS400 adapter + rvabrep-pipeline + as400-trigger-pipeline".
  Tick "MVP: `rvabrep-pipeline` end-to-end" — now feasible.
- [ ] **6.3** PII grep on new files. Synthetic identities only.
- [ ] **6.4** Stage all files. Commit:
  `feat(adapters,orchestrators,cli): add AS400 adapter + multi-pipeline support`.
- [ ] **6.5** `git checkout main && git merge --ff-only feat/014-as400-pipelines && git branch -d feat/014-as400-pipelines`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..010 (AS400DataSource) | 1.1, 1.2 + test_as400.py |
| REQ-011..013 (rename) | 2.1..2.5 |
| REQ-014..017 (schema) | 3.1..3.5 + test_schema.py |
| REQ-018..019 (wiring) | 4.3 + test_wiring.py |
| REQ-020..022 (CLI) | 4.4 + test_rvabrep_pipeline.py / test_as400_pipeline.py |
| REQ-023..024 (doctor) | 5.1, 5.2 |
| REQ-025 (logging) | implicit; visual review of as400.py |

---

## Estimated effort

- Phase 1 (AS400 adapter): 90 min
- Phase 2 (rename): 30 min
- Phase 3 (schema): 90 min
- Phase 4 (strategy + wiring + CLI): 90 min
- Phase 5 (doctor + verification): 45 min
- Phase 6 (docs + commit + merge): 25 min
- **Total**: ~5 h 50 min

---

## Notes for the implementor

- `pyodbc` import inside `_connect()` (NOT at module top) so test
  environments without unixodbc-dev still pass `python -c "import
  cmcourier.adapters.sources.as400"`. Top-level only imports
  `typing` / `cmcourier.domain.*`.
- `_FakeAs400Cursor` MUST implement `execute(sql, params)`,
  `fetchall()`, `fetchmany(size)`, `description`, `close()`. The
  cursor's `description` is a list of `(name, ...)` tuples per the
  PEP 249 spec — only the first element matters for `As400DataSource`.
- The discriminator-default trick (REQ-017) lives in `load_config`,
  NOT in the schema. Schema is strict: every YAML that reaches
  Pydantic has a `kind` field. The loader inserts the default before
  validation. Document this in the loader docstring.
- `pyodbc.Error.args` may be `(sqlstate, message)` OR just `(message,)`.
  `_extract_sqlstate` returns `args[0]` when it matches `r"^\d{5}$"`
  or `r"^[A-Z]{5}$"` (SQLSTATE format), else returns empty string.
- `As400DataSource.query_stream` uses `fetchmany(500)` in a loop.
  Test the lazy semantics by asserting `cursor.fetchmany` is called
  MORE than once when 750 rows are yielded.
- For the wiring's `_build_trigger_strategy`, the rvabrep case needs
  access to the indexing source (which the strategy reads from). Pass
  the constructed `rvabrep_src` (`TabularDataSource` or
  `As400DataSource`) alongside.
- The CLI tests for `rvabrep-pipeline` and `as400-trigger-pipeline`
  reuse the YAML builder from `test_cli.py`'s pattern — extract to
  `tests/integration/cli/conftest.py` if reuse becomes painful.
- The doctor's `as400_connectivity` check should NOT depend on the
  trigger CSV existing (it's an AS400 query). SKIP when `kind !=
  "as400"`. The `details` carry `host` (NOT credentials) for
  diagnostic context.

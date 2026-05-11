# Tasks — 015-as400-metadata-source

**Status**: Draft
**Spec**: `specs/015-as400-metadata-source/spec.md`
**Plan**: `specs/015-as400-metadata-source/plan.md`

---

## Phase 1 — Schema discriminated union

- [ ] **1.1** Edit `src/cmcourier/config/schema.py`:
  - Rename `MetadataSourceConfig` to `CsvMetadataSourceConfig`. Add `kind: Literal["csv"] = "csv"`.
  - Add `As400MetadataSourceConfig(kind: Literal["as400"], alias, as400_connection, table)`.
  - Add `MetadataSourceConfig` as `Annotated[... discriminator="kind"]` type alias.
  - Update `MetadataConfigModel.sources` annotation to use the alias.
  - `__all__` updated.
- [ ] **1.2** Edit `tests/unit/config/test_schema.py`: add 5 tests for the metadata-source discriminator (csv loads, as400 loads, unknown kind raises, missing kind defaults to csv via loader, `As400MetadataSourceConfig.table` required).
- [ ] **1.3** Run schema tests + the full schema suite. Iterate to green.

---

## Phase 2 — Loader + wiring + doctor

- [ ] **2.1** Edit `src/cmcourier/config/loader.py`: rename `_inject_default_trigger_kind` to `_inject_default_kinds`. Add metadata.sources kind injection. Update the function's docstring.
- [ ] **2.2** Edit `src/cmcourier/config/wiring.py`:
  - Remove `_reject_unsupported_source_types` and its call.
  - Extract `_build_metadata_sources(sources, secrets)` helper (dispatches by kind).
  - Update `build_pipeline` to use the helper.
- [ ] **2.3** Add ~2 wiring tests in `tests/integration/config/test_wiring.py`:
  - as400 metadata source builds correctly.
  - Missing AS400 secrets raise ConfigurationError.
- [ ] **2.4** Edit `src/cmcourier/cli/doctor.py`: `_check_metadata_sources` dispatches by kind. Open `As400DataSource` for as400 sources (passing secrets). Add 1 test in `test_doctor.py` for the mixed-source case.

---

## Phase 3 — End-to-end pipeline test + verification

- [ ] **3.1** Add 1 test in `tests/integration/pipeline/test_staged_pipeline.py`:
  - Pipeline with csv trigger + as400 metadata source. pyodbc mocked to return (CIF=123456, NAME=JUAN_TEST) rows.
  - Assert pipeline.run() resolves the field, RunReport.s5_done > 0, and the CMIS upload payload contains the resolved value.
- [ ] **3.2** `ruff check src/ tests/` — clean.
- [ ] **3.3** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **3.4** `mypy src/cmcourier/` — clean.
- [ ] **3.5** `pytest --cov=src/cmcourier --cov-report=term` — total coverage ≥ 80%; touched modules hold ≥ 90%.
- [ ] **3.6** `pre-commit run --all-files` — clean.
- [ ] **3.7** Smoke: `cmcourier --help` still lists 4 commands.

---

## Phase 4 — Docs + commit + merge FF

- [ ] **4.1** Update `CHANGELOG.md`:
  - "Planned for next release" → local-scan-pipeline, single-doc, REBIRTH §11 batch/inspect, port hygiene cleanup.
  - Add `[0.17.0] — 2026-05-10` entry: Added / Changed / Verification / Rationale. Milestone: AS400 metadata sources.
- [ ] **4.2** Update `README.md` Status checklist: tick "Fifteenth change: AS400 metadata source".
- [ ] **4.3** PII grep on new content. Synthetic only.
- [ ] **4.4** Stage. Commit: `feat(config,services): support as400 metadata sources end-to-end`.
- [ ] **4.5** `git checkout main && git merge --ff-only feat/015-as400-metadata-source && git branch -d feat/015-as400-metadata-source`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..004 (schema) | 1.1, 1.2 |
| REQ-005 (loader kinds) | 2.1, 1.2 (default-injection test) |
| REQ-006..008 (wiring) | 2.2, 2.3 |
| REQ-009..010 (service) | implicit; test_staged_pipeline 3.1 |
| REQ-011 (doctor) | 2.4 |

---

## Estimated effort

- Phase 1: 30 min
- Phase 2: 60 min
- Phase 3: 60 min
- Phase 4: 20 min
- **Total**: ~2 h 50 min

---

## Notes for the implementor

- The Pydantic v2 discriminator pattern: every union member declares
  `kind: Literal["<name>"]`. The default value on the CSV member
  (`kind: Literal["csv"] = "csv"`) is what permits omitting the
  field when constructing the model directly. The loader still
  needs to inject `kind` for YAML→dict→model_validate; otherwise
  Pydantic rejects the dict before the default kicks in.
- `As400MetadataSourceConfig.table` MUST be `Field(min_length=1)` so
  empty strings are rejected (Pydantic accepts `""` for str otherwise).
- Removing `_reject_unsupported_source_types` is safe because the
  MetadataService's prefetch already validates aliases (raises
  `ConfigurationError("unknown CSV alias referenced in metadata
  config")` when a `csv:foo` source_type points at an alias not in
  `sources_registry`). The same error path covers `as400:bar` now.
- The new `_build_metadata_sources` helper returns a `dict[str,
  IDataSource]`. The wiring continues passing this dict to
  `MetadataService(config, sources_registry=...)`.
- The doctor's metadata_sources check needs `secrets` now (to build
  the AS400 source). Update its signature accordingly.
- The end-to-end test should use the same harness pattern as
  existing pipeline tests but inject an as400 source into the
  metadata config. Easiest: extend the existing test_staged_pipeline
  fixture builder with an `as400_metadata: bool` flag.

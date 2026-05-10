# Tasks — 011-csv-trigger-pipeline

**Status**: Draft
**Spec**: `specs/011-csv-trigger-pipeline/spec.md`
**Plan**: `specs/011-csv-trigger-pipeline/plan.md`

---

## Phase 1 — ITrackingStore port amendment

- [ ] **1.1** Edit `src/cmcourier/domain/ports.py`: add
  `list_txn_nums_for_batch(batch_id: str) -> set[str]` as an
  `@abstractmethod` on `ITrackingStore`, with a docstring noting that
  unknown batch ids MUST return an empty set.
- [ ] **1.2** Edit `tests/unit/domain/test_ports.py`: the test that
  enumerates `ITrackingStore` abstract methods MUST include
  `"list_txn_nums_for_batch"`.
- [ ] **1.3** Edit `src/cmcourier/adapters/tracking/sqlite.py`: implement
  `list_txn_nums_for_batch` per plan §4.8 (synchronous SELECT DISTINCT
  on the reader connection; wrap `sqlite3.Error` in `TrackingError`).
- [ ] **1.4** Edit `tests/integration/adapters/test_sqlite_tracking_store.py`:
  add two tests:
  - `test_list_txn_nums_for_batch_returns_distinct_txns`
  - `test_list_txn_nums_for_batch_unknown_batch_returns_empty_set`
- [ ] **1.5** Run `pytest tests/unit/domain/test_ports.py tests/integration/adapters/test_sqlite_tracking_store.py -v`. Confirm green.

---

## Phase 2 — Pipeline fixtures + tests RED

- [ ] **2.1 (R)** Create `tests/fixtures/pipeline/triggers.csv` with 4
  triggers chosen to map to existing fixtures (rvabrep_index_sample.csv +
  modelo_documental.csv + metadata sources). Reuse synthetic identities
  like `JUANPEREZ01`, `PEPELOPEZ03`, etc. so PII grep stays clean.
- [ ] **2.2 (R)** Create `tests/fixtures/pipeline/triggers_unmapped.csv`
  — 1 trigger whose doc resolves to an `id_rvi` NOT in the Modelo
  Documental fixture (for the S2 failure scenario).
- [ ] **2.3 (R)** Create `tests/integration/pipeline/conftest.py`:
  - A `pipeline_harness` fixture (`pytest.fixture(scope="function")`)
    that:
    1. Builds `TabularDataSource` adapters for trigger CSV, modelo
       documental, RVABREP scan, and metadata sources (clients /
       accounts / cards).
    2. Builds `CsvTriggerStrategy`, `IndexingService`, `MappingService`,
       `MetadataService`, `PdfAssembler` (source_root=assembly fixtures
       dir), `CmisUploader` (config with `_BASE_URL`), and a fresh
       `SQLiteTrackingStore` in `tmp_path / "tracking.db"`.
    3. Wires them into a `CsvTriggerPipeline`.
    4. Returns a dataclass `PipelineHarness` exposing `.pipeline`,
       `.tracking_store`, `.uploader_config`, plus a method
       `register_cmis(self, docs)` that calls `responses.add(...)` for
       warmup, folder creation, and a successful upload per doc.
- [ ] **2.4 (R)** Create `tests/integration/pipeline/test_csv_trigger_pipeline.py`:
  - Module docstring.
  - `pytestmark = [pytest.mark.integration, pytest.mark.slow]`.
  - Imports from `cmcourier.orchestrators.csv_trigger`
    (yet-to-exist `CsvTriggerPipeline`, `RunReport`).
- [ ] **2.5 (R)** Write the 9 test groups per plan §5.2 (~20 tests):
  - `TestParameterValidation` (4): batch_size<1, from_stage<1,
    from_stage>5, from_stage>1 without batch_id.
  - `TestFreshFullRun` (3): happy-path RunReport shape;
    complete_batch called; migration_log has one row per doc at S5_DONE.
  - `TestS1ErrorHandling` (2): not-found trigger → WARNING + no row;
    IndexingError → ERROR + no row.
  - `TestCrossBatchSkip` (2): doc already at S5_DONE in prior batch
    skipped + counter; INFO log carries `reason="cross_batch_uploaded"`.
  - `TestStageFailures` (4): unmapped id_rvi (S2_FAILED); metadata
    source failure (S3_FAILED); missing page file (S4_FAILED); CMIS
    400 (S5_FAILED).
  - `TestResume` (3): from_stage=3 after first run reached S2_DONE
    → second run produces final S5_DONE without re-doing S2 work
    (assert via call-count instrumented uploader OR mapping service);
    from_stage=3 with doc-out-of-scope → INFO + dropped; from_stage=1
    on completed batch → idempotent re-run, zero upload calls.
  - `TestHeterogeneous` (1): 4 docs with 1 success + 3 different
    stage failures.
  - `TestS0Failure` (1): S0Strategy raises → exception propagates;
    `complete_batch` is NOT called (assert via raw SQL or method
    spy).
  - `TestHealedCIF` (1): trigger.cif=None → metadata CIF self-healing
    fills it → uploader receives the healed value.
- [ ] **2.6 (R)** Run `pytest tests/integration/pipeline/test_csv_trigger_pipeline.py -v`. Confirm collection ImportError.

---

## Phase 3 — Implementation GREEN

- [ ] **3.1 (G)** Create `src/cmcourier/orchestrators/csv_trigger.py`
  with module docstring, `__all__`, imports.
- [ ] **3.2 (G)** Implement `RunReport` frozen dataclass per plan §3.1.
- [ ] **3.3 (G)** Implement `_StageItem` mutable dataclass per plan §3.2.
- [ ] **3.4 (G)** Implement `CsvTriggerPipeline.__init__`,
  `_validate_parameters`, `_resolve_batch_id`, and `_build_record`.
- [ ] **3.5 (G)** Implement `_stage_s0_s1` per plan §4.2.
- [ ] **3.6 (G)** Implement `_stage_s2` per plan §4.3.
- [ ] **3.7 (G)** Implement `_stage_s3` per plan §4.4 (including
  `healed_trigger` propagation).
- [ ] **3.8 (G)** Implement `_stage_s4` per plan §4.5.
- [ ] **3.9 (G)** Implement `_stage_s5` per plan §4.6.
- [ ] **3.10 (G)** Implement public `run` per plan §4.1.
- [ ] **3.11 (G)** Update `src/cmcourier/orchestrators/__init__.py`
  to re-export `CsvTriggerPipeline` and `RunReport`.
- [ ] **3.12 (G)** Run `pytest tests/integration/pipeline/test_csv_trigger_pipeline.py -v`. Iterate until all green.
- [ ] **3.13 (Rf)** Refactor for clarity. Verify every method ≤ 50 lines.

---

## Phase 4 — Verification

- [ ] **4.1** `ruff check src/ tests/` — clean.
- [ ] **4.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **4.3** `mypy src/cmcourier/` — clean.
- [ ] **4.4** `pytest --cov=src/cmcourier --cov-report=term-missing` —
  coverage on `orchestrators/csv_trigger.py` ≥ 85%, total ≥ 80%.
- [ ] **4.5** `pre-commit run --all-files` — clean.

---

## Phase 5 — Docs + commit + merge FF

- [ ] **5.1** Update `CHANGELOG.md`:
  - "Planned for next release" → "CLI Click command + Pydantic config
    loader for the csv-trigger-pipeline" (012+).
  - Add `[0.13.0] — 2026-05-10` entry: Added / Changed / Verification /
    Rationale. Call out the milestone: **FIRST MVP PIPELINE END-TO-END**.
- [ ] **5.2** Update `README.md` Status checklist: tick "Eleventh
  change: CsvTriggerPipeline orchestrator (S0..S6 end-to-end)" AND
  tick "MVP: rvabrep-pipeline end-to-end" only if appropriate — likely
  NOT yet because the actual `rvabrep-pipeline` is a different
  composition. Add a sub-checklist for the CSV pipeline.
- [ ] **5.3** PII grep on new files. Synthetic placeholders only.
- [ ] **5.4** Stage all files. Expected status:
  ```
  modified: CHANGELOG.md
  modified: README.md
  modified: src/cmcourier/domain/ports.py
  modified: src/cmcourier/adapters/tracking/sqlite.py
  modified: src/cmcourier/orchestrators/__init__.py
  added:    src/cmcourier/orchestrators/csv_trigger.py
  modified: tests/integration/adapters/test_sqlite_tracking_store.py
  modified: tests/unit/domain/test_ports.py
  added:    tests/fixtures/pipeline/triggers.csv
  added:    tests/fixtures/pipeline/triggers_unmapped.csv
  added:    tests/integration/pipeline/conftest.py
  added:    tests/integration/pipeline/test_csv_trigger_pipeline.py
  added:    specs/011-csv-trigger-pipeline/{spec,plan,tasks}.md
  ```
- [ ] **5.5** Commit `feat(orchestrators): add CsvTriggerPipeline (S0..S6 end-to-end)` (full body per template).
- [ ] **5.6** `git checkout main && git merge --ff-only feat/011-csv-trigger-pipeline && git branch -d feat/011-csv-trigger-pipeline`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..002 (port amendment) | 1.1, 1.3, 1.4 |
| REQ-003..007 (construction + run signature) | 3.4 + TestParameterValidation |
| REQ-008..009 (S0) | 3.5 + TestS0Failure |
| REQ-010..011 (S1 + cross-batch) | 3.5 + TestS1ErrorHandling + TestCrossBatchSkip |
| REQ-012..013 (resume) | 3.5..3.10 + TestResume |
| REQ-014..018 (S2..S5) | 3.6..3.9 + TestStageFailures + TestFreshFullRun |
| REQ-019..020 (finalization) | 3.10 + TestS0Failure + TestHeterogeneous |
| REQ-021..022 (RunReport) | 3.2 + every test |
| REQ-023..024 (logging) | 3.5..3.9 + caplog assertions |
| NFR-003 (coverage) | 4.4 |
| NFR-004 (50-line cap) | 3.13 |

---

## Estimated effort

- Phase 1 (port amendment): 30 min
- Phase 2 (fixtures + RED): 150 min
- Phase 3 (GREEN): 120 min
- Phase 4 (verification): 25 min
- Phase 5 (docs + commit + merge): 20 min
- **Total**: ~5h 25min — the largest single change.

---

## Notes for the implementor

- The orchestrator imports many things. Do all imports at the top of
  `csv_trigger.py` for explicitness; this is a wiring module, the
  imports ARE part of the public contract.
- The `_build_record` helper is called multiple times per stage. Keep
  it cheap — no SQL, no I/O.
- `responses.add(...)` registrations consume in order. For each test
  registering CMIS stubs, register them in this order:
  1. GET repositoryInfo (warmup)
  2. POST root (createFolder for the first segment)
  3. POST root/<segment...> (createFolder for nested segments, if any)
  4. POST root/<cm_folder> (createDocument with the JSON containing
     succinctProperties.cmis:objectId)
- For the cross-batch skip test (TestCrossBatchSkip), the simplest
  setup is to:
  1. Run a fresh pipeline to completion (1 doc, ends at S5_DONE).
  2. Run again with a new SQLiteTrackingStore on the SAME .db file
     (the cross-batch lookup uses the persistent index).
  3. Assert the second run's RunReport.s1_skipped_cross_batch == 1.
- For TestResume, instrument the mapping service or uploader via a
  call-counting decorator to PROVE that work was skipped (not just
  that the final state is correct).
- The orchestrator should `flush()` before any read that depends on
  pending writes — particularly the `is_uploaded` cross-batch lookup,
  and any test's side-channel SELECT.
- The `time.monotonic()` clock for `elapsed_seconds` should NOT be
  monkey-patched in tests — assert with a relaxed `>= 0.0`.

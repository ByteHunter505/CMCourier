# Tasks — 008-indexing-service

**Status**: Draft
**Spec**: `specs/008-indexing-service/spec.md`
**Plan**: `specs/008-indexing-service/plan.md`

---

## Phase 1 — Tests RED

- [ ] **1.1 (R)** Create `tests/fixtures/services/rvabrep_index_sample.csv`
  with ~12 synthetic rows. Friendly column names (`shortname`, `system_id`,
  `txn_num`, `delete_code`, `index2..7`, `image_type`, `image_path`,
  `file_name`, `creation_date`, `last_view_date`, `total_pages`). Rows
  cover: vanilla single match, multi-match (≥3 rows same shortname),
  fully-deleted shortname, mixed deleted (1 active + 2 deleted), duplicate
  `txn_num`, `system_id=5` for filter test, `last_view_date='0'` and `''`,
  PDF + paged variants, `total_pages='1'` and `'540'`.
- [ ] **1.2 (R)** Create `tests/unit/services/test_indexing.py`:
  - Module docstring.
  - Imports from `cmcourier.services.indexing` (yet-to-exist).
  - `_FIXTURES`, `_SAMPLE_CSV` constants.
  - `pytestmark = pytest.mark.unit`.
  - `_friendly_config()` helper returning an `IndexingColumnsConfig`
    with every column overridden to the CSV's friendly name.
  - `_CallCountingSource` helper class wrapping a `TabularDataSource`
    and counting `get_by_fields` / `get_by_fields_in` invocations.
- [ ] **1.3 (R)** Write the 7 test groups per plan §5.1 (~22 tests):
  - `TestConstruction` (3): construction succeeds, lazy (no queries), defaults match the spec.
  - `TestSingleTriggerLookup` (5): vanilla, not found, all deleted, mixed deleted, CIF ignored.
  - `TestDuplicateHandling` (2): WARNING emitted + first-wins, no exception raised.
  - `TestBatchedLookup` (5): N triggers / call count, missing yields `[]`, same shortname different system_id, input-order preserved, repeated trigger yields twice.
  - `TestRowCoercion` (4): CYYMMDD round-trip, `last_view_date='0'` → `None`, `last_view_date=''` → `None`, `total_pages=''` → `0`.
  - `TestErrorWrapping` (2): adapter exception → `IndexingError` with `__cause__`, duplicate path does NOT raise.
  - `TestLoggingDiscipline` (1): caplog inspection — duplicate WARNING contains `shortname` / `duplicate_count` but NOT `cif` or `index2..6` values.
- [ ] **1.4 (R)** Run `pytest tests/unit/services/test_indexing.py -v`. Confirm collection ImportError on `cmcourier.services.indexing`.

---

## Phase 2 — Implementation GREEN

- [ ] **2.1 (G)** Create `src/cmcourier/services/indexing.py` with module
  docstring, `__all__`, imports, logger, and `IndexingColumnsConfig`
  dataclass (defaults from the spec).
- [ ] **2.2 (G)** Implement `IndexingService.__init__(source, config, batch_size=50)`. Lazy: no queries.
- [ ] **2.3 (G)** Implement `_row_to_document(row)` per plan §4.4. Handle
  `last_view_date in {'', None, '0'}` → `None`, `total_pages` coercion.
- [ ] **2.4 (G)** Implement `_classify(rows, trigger)` per plan §4.3. Delete-filter, duplicate-detect with WARNING, dict→doc conversion.
- [ ] **2.5 (G)** Implement `find_documents(trigger)` per plan §4.1. Wrap adapter exceptions in `IndexingError`. Raise `RVABREPNotFoundError` / `RVABREPDeletedError` per spec.
- [ ] **2.6 (G)** Implement `find_documents_batch(triggers)` per plan §4.2. Single `get_by_fields_in` per chunk; group rows by `(shortname, system_id)` in Python.
- [ ] **2.7 (G)** Re-export `IndexingService` and `IndexingColumnsConfig` from `src/cmcourier/services/__init__.py`.
- [ ] **2.8 (G)** Run `pytest tests/unit/services/test_indexing.py -v`. Iterate until all green.
- [ ] **2.9 (Rf)** Refactor for clarity. Confirm every method ≤ 50 lines.

---

## Phase 3 — Verification

- [ ] **3.1** `ruff check src/ tests/` — clean.
- [ ] **3.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **3.3** `mypy src/cmcourier/` — clean.
- [ ] **3.4** `pytest --cov=src/cmcourier --cov-report=term-missing` — coverage on `services/indexing.py` ≥ 95%, total ≥ 80%.
- [ ] **3.5** `pre-commit run --all-files` — clean.

---

## Phase 4 — Docs + commit + merge FF

- [ ] **4.1** Update `CHANGELOG.md`:
  - Move "Planned for next release" stub forward (next change = MVP orchestrator).
  - Add `[0.10.0] — 2026-05-10` entry with Added / Changed / Verification / Rationale.
- [ ] **4.2** Update `README.md` Status checklist: tick "Eighth change: IndexingService (S1)".
- [ ] **4.3** PII grep on new files (`rg -i 'juanperez|123456' tests/unit/services/test_indexing.py tests/fixtures/services/rvabrep_index_sample.csv src/cmcourier/services/indexing.py`). Synthetic only.
- [ ] **4.4** Stage all files. Expected git status:
  ```
  modified: CHANGELOG.md
  modified: README.md
  modified: src/cmcourier/services/__init__.py
  added:    src/cmcourier/services/indexing.py
  added:    tests/unit/services/test_indexing.py
  added:    tests/fixtures/services/rvabrep_index_sample.csv
  added:    specs/008-indexing-service/{spec,plan,tasks}.md
  ```
- [ ] **4.5** Commit:
  ```
  feat(services): add IndexingService for stage S1 (RVABREP lookup)

  IndexingService closes the service triangle (Mapping + Metadata +
  Indexing) every CMCourier pipeline depends on. Given a TriggerRecord,
  returns every non-deleted RVABREPDocument matching (shortname,
  system_id). CIF is intentionally ignored at this stage — its
  resolution is the job of S3 (Metadata) per the spec.

  Two public APIs:
  - find_documents(trigger) → list[RVABREPDocument] with typed-error
    semantics (RVABREPNotFoundError, RVABREPDeletedError). For the
    single-doc pipeline and ad-hoc operator calls.
  - find_documents_batch(triggers) → Iterator[(trigger, list)] that
    chunks the input into IN-list batches of 50 and
    emits empty lists for missing triggers (orchestrator decides
    semantics). One get_by_fields_in call per chunk.

  Duplicate txn_num within a single trigger's result: WARNING log +
  first-wins, mirroring MappingService's the spec precedent. No
  exception is raised — data quality issues surface in logs, not in
  the pipeline's error path.

  IndexingColumnsConfig (frozen+slots) defaults match RVABREP physical
  column names from the spec (ABABCD, ABAACD, ABAANB, ABACST,
  ABAHCD = id_rvi, …). Tests override every column to the CSV's
  friendly names so the same service code exercises both AS400-style
  and CSV-style column maps.

  Verification:
  - pytest -v: all tests pass (~270 total)
  - coverage on services/indexing.py: XX% branch (target ≥95%)
  - ruff / mypy: clean
  - pre-commit: clean

  Constitution Principle I: services/indexing.py imports only
  cmcourier.domain.* (no third-party). Principle VIII: logs identify
  column names and shortnames; never log VALUES of cif or index2..6.

  Closes specs/008-indexing-service/.
  ```
- [ ] **4.6** `git checkout main && git merge --ff-only feat/008-indexing-service && git branch -d feat/008-indexing-service`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..003 (construction) | 2.1, 2.2 + Construction tests (1.3) |
| REQ-004..009 (single-trigger) | 2.5 + SingleTriggerLookup + DuplicateHandling |
| REQ-010..014 (batched) | 2.6 + BatchedLookup |
| REQ-015..018 (coercion) | 2.3 + RowCoercion |
| REQ-019..020 (error wrap) | 2.5 + ErrorWrapping |
| REQ-021 (logging) | 2.4 + LoggingDiscipline |
| NFR-001..003 (perf) | 2.5, 2.6 + BatchedLookup call-count tests |
| NFR-004 (coverage) | 3.4 |
| NFR-005 (50-line cap) | 2.9 |

---

## Estimated effort

- Phase 1 (RED): 75 min
- Phase 2 (GREEN): 75 min
- Phase 3 (verification): 15 min
- Phase 4 (docs + commit + merge): 15 min
- **Total**: ~3 h

---

## Notes for the implementor

- Constitution Principle I: no third-party imports in `services/indexing.py`.
  `pandas` lives behind `TabularDataSource`; the service is pure stdlib +
  domain.
- The `_classify` helper is the natural home for the duplicate WARN +
  delete filter. Keep it private.
- `RVABREPDuplicateError` is intentionally NOT raised here. The exception
  exists for callers that want fail-loud semantics (e.g., a `doctor`
  command). The service chose first-wins because it's the pragmatic match
  for real-world RVABREP data quality.
- `_CallCountingSource` is test-only. Do NOT promote it to production code.

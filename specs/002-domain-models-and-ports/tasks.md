# Tasks — 002-domain-models-and-ports

**Status**: Draft (under review)
**Created**: 2026-05-09
**Spec reference**: `specs/002-domain-models-and-ports/spec.md`
**Plan reference**: `specs/002-domain-models-and-ports/plan.md`

> Atomic implementation checklist. Strict TDD: every model, port, and exception lands as a Red test FIRST, then the minimum implementation, then refactor while green.

---

## How to read this file

- Tasks are numbered hierarchically: `<phase>.<task>`.
- Each phase ends in a meaningful intermediate state (a green pytest run, a clean ruff/mypy).
- Strict TDD prefix per code task:
  - **`(R)`** — write the failing test
  - **`(G)`** — write the minimum code to make it pass
  - **`(Rf)`** — refactor while green
- Tasks without a prefix are non-code (configs, docs).

The dependency graph between phases:

```
Phase 1 (exceptions)  ── leaves, no model deps
Phase 2 (StageStatus) ── depended on by MigrationRecord and ITrackingStore
Phase 3 (helpers + simple models) ── independent of complex models
Phase 4 (complex models) ── uses StageStatus and helpers
Phase 5 (ports) ── uses all models above
Phase 6 (re-exports + final docs)
Phase 7 (verification + commit)
```

---

## Phase 1 — Exception hierarchy

Leaves first. Nothing else depends on exceptions, but everything else may raise them.

- [ ] **1.1 (R)** Create `tests/unit/domain/test_exceptions.py` with the test class `TestHierarchy` and a parametrized test asserting every subclass relationship per `plan.md §5.1`. Run `pytest -m unit tests/unit/domain/test_exceptions.py` and confirm it fails with `ImportError` (target classes do not exist yet).
- [ ] **1.2 (G)** Create `src/cmcourier/domain/exceptions.py`. Define `CMCourierError` per `plan.md §5.2`. Define every subclass per `plan.md §5.1`. For subclasses with structured context (e.g., `IDRViNotMappedError`, `RetriesExhaustedError`), define explicit named parameters per `plan.md §5.3`.
- [ ] **1.3 (R)** Add `TestStructuredContext` test class to `test_exceptions.py` covering: `IDRViNotMappedError(id_rvi="ZZ99").id_rvi == "ZZ99"`, `"ZZ99" in str(exc)`, `RetriesExhaustedError(txn_num="123", attempts=3)` exposes both attributes. Run pytest, confirm fails (or partially passes).
- [ ] **1.4 (G)** Implement structured context per `plan.md §5.2` so the tests pass.
- [ ] **1.5 (Rf)** Run `ruff check src/cmcourier/domain/exceptions.py tests/unit/domain/test_exceptions.py` and `mypy src/cmcourier/domain/exceptions.py`. Fix any issues. Re-run pytest.

**Phase 1 done when**: `pytest -m unit tests/unit/domain/test_exceptions.py` is green and ruff/mypy pass on those files.

---

## Phase 2 — `StageStatus` enum

Depended on by `MigrationRecord` (Phase 4) and `ITrackingStore` (Phase 5). Worth landing in isolation.

- [ ] **2.1 (R)** Create `tests/unit/domain/test_models.py` (we will populate it across phases 2-4). Add `TestStageStatus` class with tests for `value_equals_name`, `terminal_for_stage(1)` returns `(S1_DONE, S1_FAILED)`, and `terminal_for_stage(7)` raises `ValueError`. Run pytest, confirm fails (`StageStatus` doesn't exist).
- [ ] **2.2 (G)** Create `src/cmcourier/domain/models.py` with the module docstring and the imports listed in `plan.md §3.1`. Implement `StageStatus` per `plan.md §3.5`. Run pytest, confirm green.
- [ ] **2.3 (Rf)** Confirm ruff and mypy clean.

**Phase 2 done when**: `pytest -m unit tests/unit/domain/test_models.py::TestStageStatus` is green.

---

## Phase 3 — Helpers + simple models

Helpers (`parse_cymmdd`, `is_pdf_filename`, `compute_cm_folder`, `compute_cm_object_type`) and the simplest dataclasses (`TriggerRecord`, `StagedFile`, `ResolvedMetadata`).

- [ ] **3.1 (R)** Add `TestParseCymmdd` to `test_models.py` covering canonical example, too-short, non-digit, invalid month (`"1251301"`), invalid day (`"1252231"`). Confirm fails.
- [ ] **3.2 (G)** Implement `parse_cymmdd` per `plan.md §3.2`. Confirm green.
- [ ] **3.3 (R)** Add `TestIsPdfFilename` covering `"0AAAUI0K.PDF"` (true), `"DAAAH9X4.001"` (false), case insensitivity. Confirm fails.
- [ ] **3.4 (G)** Implement `is_pdf_filename`. Confirm green.
- [ ] **3.5 (R)** Add `TestComputeCmFolder` and `TestComputeCmObjectType` covering the REBIRTH §4.2 example (`"01.02.04.01.01"` → `"/$type/BAC_01_02_04_01_01"` and `"$t!-2_BAC_01_02_04_01_01v-1"`). Confirm fails.
- [ ] **3.6 (G)** Implement `compute_cm_folder` and `compute_cm_object_type`. Confirm green.
- [ ] **3.7 (R)** Add `TestTriggerRecord` covering: construction with valid inputs, empty `shortname` raises `ValueError`, empty `system_id` raises `ValueError`, `cif=None` allowed, frozen-ness (assignment raises `FrozenInstanceError`).
- [ ] **3.8 (G)** Implement `TriggerRecord` per `plan.md §3.1` with a `__post_init__` that validates non-empty `shortname` and `system_id`. Confirm green.
- [ ] **3.9 (R)** Add `TestStagedFile` covering construction, negative `size_bytes` raises, negative `page_count` raises, frozen-ness.
- [ ] **3.10 (G)** Implement `StagedFile` with `__post_init__` validation. Confirm green.
- [ ] **3.11 (R)** Add `TestResolvedMetadata` covering: `from_dict({"BAC_CIF": "123"})` constructs, `__getitem__`, `__contains__`, `__iter__`, `__len__`, mutating the underlying source dict does NOT mutate the `ResolvedMetadata`'s view (proves immutability via copy).
- [ ] **3.12 (G)** Implement `ResolvedMetadata` per `plan.md §3.4`. Confirm green.
- [ ] **3.13 (Rf)** Run ruff + mypy on `src/cmcourier/domain/models.py` and `tests/unit/domain/test_models.py`. Fix any issues.

**Phase 3 done when**: all tests added in phase 3 pass and tooling is green.

---

## Phase 4 — Complex models

Models with computed properties or that depend on other domain types.

- [ ] **4.1 (R)** Add `TestRVABREPDocument` covering: full construction with all 16 fields, `is_pdf` true for `"FOO.PDF"`, `is_pdf` true for `"foo.pdf"` (case insensitive), `is_pdf` false for `"FOO.001"`, `is_deleted` true for `delete_code="D"`, `is_deleted` false for `delete_code=""`, frozen-ness, `creation_date` is a `datetime` (not str).
- [ ] **4.2 (G)** Implement `RVABREPDocument` per `plan.md §3.1` with `is_pdf` and `is_deleted` as `@property` accessors. Confirm green.
- [ ] **4.3 (R)** Add `TestCMMapping` covering: construction with `clase_id`, `id_rvi`, `id_corto`, `clase_name`, `required_metadata_fields=()`, `cm_folder` computed correctly, `cm_object_type` computed correctly, frozen-ness.
- [ ] **4.4 (G)** Implement `CMMapping` per `plan.md §3.1` with computed `cm_folder` and `cm_object_type` `@property` accessors. Confirm green.
- [ ] **4.5 (R)** Add `TestMigrationRecord` covering: construction with required fields only (defaults apply to optional fields), `cm_object_id=None` valid, `status` accepts a `StageStatus`, frozen-ness.
- [ ] **4.6 (G)** Implement `MigrationRecord` per `plan.md §3.6`. Confirm green.
- [ ] **4.7 (Rf)** Ruff + mypy clean on the touched files.

**Phase 4 done when**: every model exists, every test green.

---

## Phase 5 — Ports

Abstract interfaces. They depend on every model from phases 2–4.

- [ ] **5.1 (R)** Create `tests/unit/domain/test_ports.py` with the parametrized `test_port_is_abstract` per `plan.md §6.3` listing all five ports. Confirm fails (ImportError, ports don't exist).
- [ ] **5.2 (G)** Create `src/cmcourier/domain/ports.py` per `plan.md §4.1`. Implement every port as `abc.ABC` with `@abstractmethod` decorated methods. No method bodies — only `...`. Confirm green.
- [ ] **5.3 (R)** Add a per-port test that lists the expected abstract method names against `port.__abstractmethods__` to catch accidental drift if someone forgets `@abstractmethod`. Example: `assert IDataSource.__abstractmethods__ == frozenset({"query", "query_stream", "get_by_fields", "get_by_fields_in", "get_all", "count", "close"})`.
- [ ] **5.4 (G)** Confirm test green (since 5.2 already implemented all methods).
- [ ] **5.5 (Rf)** Ruff + mypy on the new files. Particular attention to `mypy --strict` since `cmcourier.domain.*` is a strict-mode override.

**Phase 5 done when**: ports exist as abstract classes, tests green.

---

## Phase 6 — `domain/__init__.py` re-exports

Replace the current docstring-only `domain/__init__.py` with the full re-export per `plan.md §3.8`.

- [ ] **6.1 (R)** Add `tests/unit/domain/test_imports.py` with a single test asserting `from cmcourier.domain import TriggerRecord, RVABREPDocument, CMMapping, ResolvedMetadata, StagedFile, StageStatus, MigrationRecord, parse_cymmdd, compute_cm_folder, compute_cm_object_type, is_pdf_filename, IDataSource, ITrackingStore, IAssembler, IUploader, S0Strategy, CMCourierError, MappingError, IDRViNotMappedError, MetadataError, AssemblyError, UploadError, CMISClientError, CMISServerError, RetriesExhaustedError, TrackingError, IndexingError, RVABREPNotFoundError, RVABREPDeletedError, RVABREPDuplicateError, ConfigurationError, TriggerError, SourceFailedError, DefaultValidationFailedError, SourceFileMissingError, PDFAssemblyFailedError`. Confirm fails (most names not yet re-exported).
- [ ] **6.2 (G)** Replace `src/cmcourier/domain/__init__.py` with the full re-export block per `plan.md §3.8`. Define `__all__` listing every name in alphabetical order. Confirm green.
- [ ] **6.3 (Rf)** Ruff: ensure `__all__` matches the re-exports and no unused imports remain. Mypy clean.

**Phase 6 done when**: every public name is importable directly from `cmcourier.domain`.

---

## Phase 7 — Verification + commit

- [ ] **7.1** Run the full unit suite for the domain layer:
  ```bash
  source .venv/bin/activate
  pytest -m unit -v tests/unit/domain/
  ```
  Confirm all tests pass.
- [ ] **7.2** Run the full coverage report on the domain layer:
  ```bash
  pytest -m unit --cov=src/cmcourier/domain --cov-report=term-missing tests/unit/domain/
  ```
  Confirm coverage ≥ 95% (per spec REQ acceptance criterion 4.9).
- [ ] **7.3** Run the full project lint + type-check:
  ```bash
  ruff check src/ tests/
  ruff format --check src/ tests/
  mypy src/cmcourier/
  ```
  All green.
- [ ] **7.4** Run pre-commit on all files:
  ```bash
  pre-commit run --all-files
  ```
  All green.
- [ ] **7.5** PII grep:
  ```bash
  grep -rEn '\b\d{6}\b' src/cmcourier/domain/ tests/unit/domain/
  grep -rEni '(juan|maria|carlos|jose|laura|martin)\s?(perez|gomez|rodriguez|gonzalez|sanchez|martinez)' src/cmcourier/domain/ tests/unit/domain/
  ```
  Synthetic-only identifiers are acceptable (`JUANPEREZ01`, `123456`); real-looking pairs of name+CIF are not.
- [ ] **7.6** Update `CHANGELOG.md`: add a `[0.4.0]` block per `plan.md §7`, adjust `[Unreleased]` "Planned for next release" to point to 003 (next adapter change).
- [ ] **7.7** Update `README.md` Status checklist: tick `Second change: domain models, ports, exceptions` if not already.
- [ ] **7.8** Stage all files, confirm `git status` matches the expected list:
  ```
  modified: README.md
  modified: CHANGELOG.md
  modified: src/cmcourier/domain/__init__.py
  modified: src/cmcourier/domain/models.py
  modified: src/cmcourier/domain/ports.py
  modified: src/cmcourier/domain/exceptions.py
  added: tests/unit/domain/test_models.py
  added: tests/unit/domain/test_ports.py
  added: tests/unit/domain/test_exceptions.py
  added: tests/unit/domain/test_imports.py
  added: specs/002-domain-models-and-ports/{spec,plan,tasks}.md
  ```
- [ ] **7.9** Create the implementation commit on the feature branch:
  ```
  feat(domain): add models, ports, and exception hierarchy

  Populate the empty domain layer left by 001 with frozen dataclasses,
  abstract interfaces, and the typed exception tree. Every public type
  arrived via Strict TDD (red test → green code → refactor). Coverage
  on src/cmcourier/domain/ is XX% (target ≥95%).

  Models (REBIRTH §3, §4, §6, §9): TriggerRecord, RVABREPDocument
  (with is_pdf / is_deleted properties), CMMapping (with computed
  cm_folder + cm_object_type), ResolvedMetadata (read-only mapping
  via MappingProxyType), StagedFile, MigrationRecord, plus the
  StageStatus enum encoding the per-stage state machine from §10.3.
  Helpers parse_cymmdd, is_pdf_filename, compute_cm_folder,
  compute_cm_object_type live alongside the models so services and
  pre-flight validation share one source of truth.

  Ports (REBIRTH §14.3 + §10): IDataSource, ITrackingStore (with the
  stage-aware methods mark_stage_pending / mark_stage_done /
  mark_stage_failed plus the cross-batch is_uploaded idempotency
  anchor), IAssembler, IUploader, and S0Strategy (the new abstraction
  for the four trigger source modes from §5.1). All abstract; concrete
  implementations land in 003+.

  Exceptions: CMCourierError as root, organized by stage (TriggerError
  S0, IndexingError S1, MappingError S2, MetadataError S3,
  AssemblyError S4, UploadError S5, TrackingError S6) plus
  ConfigurationError. Every exception accepts structured context
  (txn_num, id_rvi, batch_id, etc.) for downstream PII-safe logging
  per Constitution Principle VIII.

  domain/__init__.py re-exports every public name so callers write
  `from cmcourier.domain import IDataSource`. __all__ alphabetized.

  Verification:
  - pytest -m unit tests/unit/domain/: XX/XX pass
  - coverage on src/cmcourier/domain/: XX%
  - ruff check / format: clean
  - mypy --strict on cmcourier.domain.*: clean
  - pre-commit run --all-files: clean

  No I/O. No third-party imports inside domain/. Constitution
  Principle I held throughout.

  Closes specs/002-domain-models-and-ports/.
  ```

---

## Verification mapping (spec REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..002 | 3.7, 3.8 |
| REQ-003..004 | 4.1, 4.2 |
| REQ-005 | 3.1, 3.2 |
| REQ-006 | 3.3, 3.4 |
| REQ-007..008 | 4.3, 4.4 |
| REQ-009 | 3.5, 3.6 |
| REQ-010 | 3.11, 3.12 |
| REQ-011 | 3.9, 3.10 |
| REQ-012..013 | 2.1, 2.2 |
| REQ-014..015 | 4.5, 4.6 |
| REQ-016 | every "frozen-ness" subtest in phases 3-4 |
| REQ-017 | enforced by Phase 1-6 import discipline; verified by mypy + ruff in Phase 7 |
| REQ-018 | 6.1, 6.2 |
| REQ-019 | 5.2 (IDataSource block) |
| REQ-020 | 5.2 (ITrackingStore block) |
| REQ-021 | 5.2 (IAssembler block) |
| REQ-022 | 5.2 (IUploader block) |
| REQ-023 | 5.2 (S0Strategy block) |
| REQ-024 | 5.3 (`__abstractmethods__` checks) |
| REQ-025..026 | 6.1, 6.2 |
| REQ-027..035 | 1.1..1.5 |
| REQ-036 | every (R) and (G) task in phases 2-4 |
| REQ-037 | 5.1, 5.3 |
| REQ-038 | 1.1, 1.3 |
| REQ-039 | 7.1 (timing assertion in test discovery) |
| REQ-040 | 7.3 (mypy step) |
| REQ-041 | the (R) → (G) → (Rf) ordering in every code task |

| Acceptance scenario | Tasks |
|---------------------|-------|
| 4.1 (domain pure) | 7.3 (mypy + the import discipline of phases 1-6) |
| 4.2 (CYYMMDD round-trip) | 3.1, 3.2 |
| 4.3 (CM folder/object type) | 3.5, 3.6 |
| 4.4 (frozen rejection) | 3.7-3.8 + similar in every model |
| 4.5 (ports abstract) | 5.1, 5.2 |
| 4.6 (exception hierarchy filtering) | 1.1, 1.3 |
| 4.7 (tests pass clean) | 7.1, 7.3 |
| 4.8 (no PII) | 7.5 |
| 4.9 (coverage ≥95%) | 7.2 |

---

## Estimated effort

- Phase 1 (exceptions): 30 min
- Phase 2 (StageStatus): 10 min
- Phase 3 (helpers + simple models): 60 min
- Phase 4 (complex models): 45 min
- Phase 5 (ports): 30 min
- Phase 6 (re-exports): 10 min
- Phase 7 (verification + commit): 20 min
- **Total**: ~3 hours and 25 minutes of focused work for one contributor pair-programming with an agent.

The strict-TDD overhead is real but pays off immediately — every test that flips green is documented behavior, and the coverage target falls out naturally.

---

## Notes for the implementor

- Constitution Principle I is binding: NO third-party imports inside `src/cmcourier/domain/`. If a test file under `tests/unit/domain/` accidentally imports `pydantic` or similar, it is a code smell — the test belongs elsewhere.
- The 50-line function cap holds. The longest function in this change is `parse_cymmdd` at ~10 lines. Helper functions and `__post_init__` validators stay under 15 lines each.
- `__all__` in `domain/__init__.py` is the source of truth for what is "public". Anything not in `__all__` should be considered private to the module.
- If during implementation a model gains a method that requires logic beyond a one-liner, stop and reconsider — most behavior should live in services, not models. Models are data + tiny derivations.
- Strict TDD does not mean "write 100 tests upfront". It means "for each public behavior, write the failing test before the code that satisfies it". The test files in this change end up at roughly 300-400 lines combined; nothing extreme.

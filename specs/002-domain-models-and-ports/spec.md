# Spec — 002-domain-models-and-ports

**Status**: Draft (under review)
**Created**: 2026-05-09
**Author**: bitBreaker
**Constitution version at draft time**: v1.0.0
**Depends on**: 001-bootstrap-python-skeleton (merged)

> The **what** of this change. Populates the empty domain layer with models, ports, and the typed exception hierarchy. The **how** lives in `plan.md`. The implementation checklist lives in `tasks.md`.

---

## 1. Intent

Populate `src/cmcourier/domain/` with the **dataclasses, abstract interfaces, and exception hierarchy** that every other layer of CMCourier will build on. After this change merges, the next change can begin writing concrete adapters and services against stable domain contracts.

The change ships:
- **Models** in `models.py` — frozen dataclasses for `TriggerRecord`, `RVABREPDocument`, `CMMapping`, `ResolvedMetadata`, `StagedFile`, `MigrationRecord`, plus the `StageStatus` enum.
- **Ports** in `ports.py` — abstract interfaces for `IDataSource`, `ITrackingStore`, `IAssembler`, `IUploader`, and `S0Strategy` (per stage architecture).
- **Exceptions** in `exceptions.py` — typed exception hierarchy rooted at `CMCourierError`, organized by stage and failure mode.
- **Helper functions** strictly in support of the models: `parse_cymmdd()` (REBIRTH §3.3), `compute_cm_folder()` and `compute_cm_object_type()` (REBIRTH §4.2), `is_pdf_filename()` (REBIRTH §3.4).

All under Constitution Principle I (zero external deps in `domain/`) and Strict TDD (Red → Green per type).

---

## 2. Why now

- The bootstrap skeleton placed empty `models.py`, `ports.py`, `exceptions.py` files. Nothing imports them; nothing can be implemented against them.
- All concrete adapters (CSV, AS400, SQLite, CMIS, PDF assembly) need `IDataSource`, `ITrackingStore`, `IAssembler`, `IUploader` to exist as abstractions before they have something to implement.
- All services (`mapping`, `metadata`, `trigger`, `document`) need the data structures (`RVABREPDocument`, `CMMapping`, `ResolvedMetadata`) to be defined before they have something to manipulate.
- Stage S2 (Document Class Mapping) needs `MappingError` to surface specifically; stage S3 (Metadata Resolution) needs `MetadataError`. These exception types must exist before the services raise them.
- 002 is the **shortest path** from "skeleton ready" to "first concrete adapter possible" (which is 003).

---

## 3. Requirements

### 3.1 Domain models (REQ-001 through REQ-018)

- **REQ-001** — A `TriggerRecord` dataclass MUST exist exposing `shortname: str`, `cif: str | None`, `system_id: str`. It MUST be frozen, slotted, and accept a non-empty `shortname` and non-empty `system_id` (raised as `ValueError` otherwise). `cif` MAY be `None` to support the CIF self-healing rule (REBIRTH §6.5).
- **REQ-002** — An `RVABREPDocument` dataclass MUST exist exposing every RVABREP column listed in REBIRTH §3.2 (`system_code`, `txn_num`, `index1` … `index7`, `image_type`, `image_path`, `file_name`, `creation_date`, `last_view_date`, `total_pages`, `delete_code`). Field types MUST follow REBIRTH (e.g., `creation_date` is a `datetime`, `total_pages` is an `int`, `delete_code` is a `str`). It MUST be frozen and slotted.
- **REQ-003** — `RVABREPDocument` MUST expose a `is_pdf: bool` property derived from `file_name.upper().endswith('.PDF')` (REBIRTH §3.4).
- **REQ-004** — `RVABREPDocument` MUST expose an `is_deleted: bool` property that returns `True` when `delete_code` is non-empty (REBIRTH §3.2).
- **REQ-005** — A module-level helper `parse_cymmdd(date_str: str) -> datetime` MUST exist that parses the AS400 7-digit `CYYMMDD` format (REBIRTH §3.3). Invalid inputs MUST raise `ValueError`. The function lives in `domain/models.py` because it is intrinsic to the model.
- **REQ-006** — A module-level helper `is_pdf_filename(name: str) -> bool` MUST exist returning `name.upper().endswith('.PDF')` so `RVABREPDocument.is_pdf` and other call sites can share a single source of truth.
- **REQ-007** — A `CMMapping` dataclass MUST exist exposing `clase_id: str`, `id_rvi: str`, `id_corto: str`, `clase_name: str`, `required_metadata_fields: tuple[str, ...]`. It MUST be frozen and slotted.
- **REQ-008** — `CMMapping` MUST expose computed read-only properties `cm_folder: str` and `cm_object_type: str`, derived per REBIRTH §4.2 (`f"/$type/BAC_{normalized}"` and `f"$t!-2_BAC_{normalized}v-1"` where `normalized = clase_id.replace('.', '_')`).
- **REQ-009** — Module-level helpers `compute_cm_folder(clase_id)` and `compute_cm_object_type(clase_id)` MUST exist so the same logic is reusable outside the model (e.g., for pre-flight validation).
- **REQ-010** — A `ResolvedMetadata` dataclass MUST exist exposing `properties: Mapping[str, str]` (a read-only view; the underlying type is a `dict[str, str]` but stored as a `MappingProxyType` for safety). It MUST be frozen and slotted. It MUST expose `__getitem__`, `__contains__`, `__iter__`, `__len__` as a read-only mapping.
- **REQ-011** — A `StagedFile` dataclass MUST exist exposing `path: Path`, `size_bytes: int`, `page_count: int`. It MUST be frozen and slotted. `size_bytes` and `page_count` MUST be non-negative (raise `ValueError` otherwise).
- **REQ-012** — A `StageStatus` enum MUST exist with the per-stage state machine values from REBIRTH §10.3: `S1_PENDING`, `S1_DONE`, `S1_FAILED`, `S2_PENDING`, `S2_DONE`, `S2_FAILED`, `S3_PENDING`, `S3_DONE`, `S3_FAILED`, `S4_PENDING`, `S4_DONE`, `S4_FAILED`, `S5_PENDING`, `S5_DONE`, `S5_FAILED`, plus `SKIPPED` (idempotency: already uploaded). Each value MUST be a string equal to its name (e.g., `StageStatus.S1_DONE.value == "S1_DONE"`) so persistence layers can store it directly.
- **REQ-013** — `StageStatus` MUST expose a class method `terminal_for_stage(stage: int) -> tuple["StageStatus", "StageStatus"]` returning `(Sn_DONE, Sn_FAILED)` for the given stage number. Invalid stage MUST raise `ValueError`.
- **REQ-014** — A `MigrationRecord` dataclass MUST exist exposing the fields documented in REBIRTH §9.2 (`trigger_shortname`, `trigger_cif`, `trigger_system_id`, `rvabrep_txn_num`, `rvabrep_file_name`, `cm_object_id` (`str | None`), `cm_folder` (`str | None`), `cm_object_type` (`str | None`), `status: StageStatus`, `error_message: str | None`, `source_file_path: str | None`, `page_count: int | None`, `file_size_bytes: int | None`, `started_at: datetime | None`, `completed_at: datetime | None`, `retry_count: int`, `created_at: datetime`).
- **REQ-015** — `MigrationRecord` MUST be frozen and slotted. Required fields are `trigger_shortname`, `trigger_cif`, `trigger_system_id`, `rvabrep_txn_num`, `rvabrep_file_name`, `status`, `created_at`. All others have explicit `None` / zero defaults.
- **REQ-016** — All dataclasses MUST be frozen (immutable) and slotted (`@dataclass(frozen=True, slots=True)`) to make accidental mutation impossible and to keep memory footprint small at scale (200,000 documents in flight is plausible).
- **REQ-017** — `domain/models.py` MUST import nothing outside the Python standard library. No `pydantic`, no `pandas`, no third-party module of any kind. The only `from` imports allowed are `dataclasses`, `datetime`, `enum`, `pathlib`, `types`, `collections.abc`, and standard typing.
- **REQ-018** — `domain/models.py` and `domain/__init__.py` MUST re-export every public name (`TriggerRecord`, `RVABREPDocument`, `CMMapping`, `ResolvedMetadata`, `StagedFile`, `StageStatus`, `MigrationRecord`, `parse_cymmdd`, `is_pdf_filename`, `compute_cm_folder`, `compute_cm_object_type`) so callers write `from cmcourier.domain import TriggerRecord` not `from cmcourier.domain.models import TriggerRecord`.

### 3.2 Ports — abstract interfaces (REQ-019 through REQ-026)

- **REQ-019** — `IDataSource` (abstract base class) MUST exist with the methods listed in REBIRTH §14.3: `query`, `query_stream`, `get_by_fields`, `get_by_fields_in`, `get_all`, `count`, `close`. Signatures match REBIRTH exactly.
- **REQ-020** — `ITrackingStore` (abstract base class) MUST exist with stage-aware methods that match the new architecture in REBIRTH §10.3: `is_stage_done(txn_num: str, batch_id: str, stage: StageStatus) -> bool`, `mark_stage_pending(record: MigrationRecord, stage: StageStatus) -> None`, `mark_stage_done(txn_num: str, batch_id: str, stage: StageStatus) -> None`, `mark_stage_failed(txn_num: str, batch_id: str, stage: StageStatus, error: str) -> None`, plus batch lifecycle methods `start_batch(total_records: int) -> str`, `complete_batch(batch_id: str) -> None`, `is_uploaded(txn_num: str) -> bool` (idempotency anchor across batches), `close() -> None`.
- **REQ-021** — `IAssembler` MUST exist with `assemble(document: RVABREPDocument) -> StagedFile` (raises `AssemblyError` on failure).
- **REQ-022** — `IUploader` MUST exist with `ensure_folder(folder_path: str) -> None`, `upload(file: StagedFile, folder_path: str, object_type_id: str, document_name: str, mime_type: str, properties: Mapping[str, str]) -> str` (returns CM `objectId`; raises `UploadError` on failure), and `test_connection() -> Mapping[str, str]`.
- **REQ-023** — `S0Strategy` (abstract base class) MUST exist with `acquire(source_descriptor: str) -> Iterator[TriggerRecord]`. Concrete strategies map to the four trigger source modes from REBIRTH §5.1 (`csv:`, `as400:`, `direct_rvabrep`, `local_scan`). Implementation of those concrete strategies is NOT in this change — only the interface.
- **REQ-024** — Every port MUST be defined as an `abc.ABC` with `@abstractmethod` decorators. Concrete subclasses (built in 003+) implement them.
- **REQ-025** — `domain/ports.py` MUST import nothing outside the standard library plus `cmcourier.domain.models` (for type hints). No `pydantic`, no `requests`, no `pyodbc`.
- **REQ-026** — `domain/__init__.py` MUST re-export every port name so callers write `from cmcourier.domain import IDataSource`.

### 3.3 Exception hierarchy (REQ-027 through REQ-035)

- **REQ-027** — `CMCourierError` MUST be the root of the project's typed exception hierarchy. It inherits from `Exception`. No code outside `domain/` may inherit directly from `Exception` for project-specific errors — everyone subclasses `CMCourierError`.
- **REQ-028** — `ConfigurationError(CMCourierError)` MUST exist for invalid configuration discovered at startup (raised by `config/` in 005).
- **REQ-029** — `TriggerError(CMCourierError)` MUST exist for stage S0 failures (source unreachable, malformed input).
- **REQ-030** — `IndexingError(CMCourierError)` MUST exist for stage S1 failures, with three subclasses: `RVABREPNotFoundError`, `RVABREPDeletedError`, `RVABREPDuplicateError`.
- **REQ-031** — `MappingError(CMCourierError)` MUST exist for stage S2 failures, with subclass `IDRViNotMappedError(MappingError)` (the most common case: `id_rvi` not in Modelo Documental).
- **REQ-032** — `MetadataError(CMCourierError)` MUST exist for stage S3 failures, with subclasses `SourceFailedError(MetadataError)` and `DefaultValidationFailedError(MetadataError)`.
- **REQ-033** — `AssemblyError(CMCourierError)` MUST exist for stage S4 failures, with subclasses `SourceFileMissingError(AssemblyError)` and `PDFAssemblyFailedError(AssemblyError)`.
- **REQ-034** — `UploadError(CMCourierError)` MUST exist for stage S5 failures, with subclasses `CMISClientError(UploadError)` (HTTP 4xx, fail-fast), `CMISServerError(UploadError)` (HTTP 5xx, retry), and `RetriesExhaustedError(UploadError)`.
- **REQ-035** — `TrackingError(CMCourierError)` MUST exist for tracking store failures (S6). It is **never** raised in a way that blocks the pipeline — it is logged and tracked separately, per REBIRTH §10.1's stage S6 description.

Each exception class MUST accept an optional structured context (e.g., `txn_num`, `batch_id`, `id_rvi`) as keyword arguments and store them on the instance for downstream logging. The base `CMCourierError.__init__` formats the context into the message; subclasses inherit this behavior.

### 3.4 Tests (REQ-036 through REQ-041)

- **REQ-036** — Every model in §3.1 MUST have unit tests in `tests/unit/domain/test_models.py` covering: construction with valid inputs, validation rejection of invalid inputs, frozen-ness (mutation raises `FrozenInstanceError`), every computed property, every helper function (`parse_cymmdd` happy path + edge cases of CYYMMDD format, `compute_cm_folder`, `compute_cm_object_type`).
- **REQ-037** — Every port in §3.2 MUST have a unit test in `tests/unit/domain/test_ports.py` confirming it is an abstract class (`abc.ABC` instance check) and that its abstract methods cannot be instantiated without implementation.
- **REQ-038** — The exception hierarchy in §3.3 MUST have unit tests in `tests/unit/domain/test_exceptions.py` covering: `isinstance(MappingError(), CMCourierError)`, every subclass relationship, and that the structured context kwargs (e.g., `txn_num`, `id_rvi`) are stored on the instance and reflected in `str(exc)`.
- **REQ-039** — All tests MUST pass under `pytest -m unit` and complete in under 5 seconds total.
- **REQ-040** — All tests MUST pass under `mypy --strict` (the domain/ override applies to tests/unit/domain/ as well via inheritance from the project mypy config; tests are type-checked).
- **REQ-041** — Strict TDD applies: every model / port / exception class lands as a Red test FIRST, then the implementation. Tasks in `tasks.md` enforce this ordering.

---

## 4. Acceptance Scenarios

### 4.1 Domain layer is pure

- **Given** the change is merged
- **When** a contributor runs `python -c "import cmcourier.domain; import cmcourier.domain.models; import cmcourier.domain.ports; import cmcourier.domain.exceptions"`
- **Then** all imports succeed without triggering any third-party imports
- **And** running `grep -E '^(import|from)' src/cmcourier/domain/*.py | grep -vE '(stdlib_only_pattern|cmcourier\.)'` returns no third-party module names

### 4.2 Round-trip CYYMMDD

- **Given** the CYYMMDD example from REBIRTH §3.3 (`"1251117"`)
- **When** the contributor calls `parse_cymmdd("1251117")`
- **Then** the result is `datetime(2025, 11, 17)`

### 4.3 CM folder and object type

- **Given** a `clase_id` of `"01.02.04.01.01"` (REBIRTH §4.2 example)
- **When** a `CMMapping(clase_id="01.02.04.01.01", ...)` is constructed
- **Then** its `cm_folder` is `"/$type/BAC_01_02_04_01_01"`
- **And** its `cm_object_type` is `"$t!-2_BAC_01_02_04_01_01v-1"`

### 4.4 Frozen dataclasses reject mutation

- **Given** a constructed `TriggerRecord(shortname="JUANPEREZ01", cif=None, system_id="1")`
- **When** the contributor attempts `record.cif = "123456"`
- **Then** a `dataclasses.FrozenInstanceError` is raised

### 4.5 Ports are abstract

- **Given** the merged change
- **When** the contributor attempts `IDataSource()` (with no concrete subclass)
- **Then** Python raises `TypeError: Can't instantiate abstract class IDataSource with abstract methods …`

### 4.6 Exception hierarchy works for `except` filtering

- **Given** the merged change
- **When** code raises `IDRViNotMappedError(id_rvi="ZZ99")` and a handler does `except MappingError as e:`
- **Then** the handler catches it
- **And** `str(e)` contains the `id_rvi="ZZ99"` context

### 4.7 Tests pass clean

- **Given** the merged change
- **When** the contributor runs `pytest -m unit -v`
- **Then** the unit suite completes in under 5 seconds with all tests passing
- **And** `mypy src/cmcourier/domain/ tests/unit/domain/` reports no errors
- **And** `ruff check src/cmcourier/domain/ tests/unit/domain/` reports no errors

### 4.8 No PII

- **Given** the merged change
- **When** the contributor greps for known PII patterns under `src/cmcourier/domain/` and `tests/unit/domain/`
- **Then** no matches are found beyond clearly-synthetic identifiers (`JUANPEREZ01`, `123456` in tests but only in identifier-shape testing, never paired with real names)

### 4.9 Coverage reasonable

- **Given** the merged change
- **When** the contributor runs `pytest -m unit --cov=src/cmcourier/domain --cov-report=term-missing`
- **Then** branch coverage of `src/cmcourier/domain/` is **at least 95%** (this layer is small enough that high coverage is feasible without contortion)

---

## 5. Out of Scope

- Concrete adapter implementations (CSV, AS400, SQLite, CMIS, PDF assembly). Each lands in its own change (003+).
- Service layer code (`services/`). Lands in 004+.
- Configuration schema (`config/schema.py` with Pydantic). Lands in 005.
- The Click CLI commands beyond the `app.py` placeholder. Lands per pipeline change.
- Docker compose for Alfresco. Lands when the CMIS adapter is built.
- A `docs/explanation/` document about the domain — the existing `docs/domain/CMCOURIER_REBIRTH.md` covers it. We may add a focused `docs/explanation/stage-architecture.md` later.
- A real CHANGELOG entry version like `0.4.0` until this change actually merges. Until then, the entry stays under `[Unreleased]`.

---

## 6. Constraints from Constitution

- **Principle I**: domain has zero external deps. REQ-017 enforces this for `models.py`; REQ-025 for `ports.py`. `exceptions.py` is bound by the same rule (only stdlib).
- **Principle III**: SRP. Three files, three responsibilities (models / ports / exceptions). 50-line function cap binds — the longest function is likely `parse_cymmdd` and it stays well under 20 lines. Helper functions for CM folder/type are one-liners.
- **Principle V**: no env reads. None of these files read environment variables.
- **Principle VI**: real test pyramid. All tests in this change are unit tests with no I/O. Integration tests for adapters (which use these ports) come in 003+.
- **Principle VII**: spec-before-code. This file (and `plan.md`, `tasks.md`) are committed before any implementation.
- **Principle VIII**: no PII. Test fixtures use synthetic identifiers explicitly.
- **Principle IX**: every model has a one-sentence purpose written before its tests are written. The plan explicitly documents the *why* per type.

---

## 7. Risks & Open Questions

### 7.1 Known risks

- **Frozen dataclasses with `slots=True`** require Python 3.10+ for the slots feature. We are on 3.11+ per Constitution, so this is safe.
- **`Mapping[str, str]` vs `dict[str, str]` for `ResolvedMetadata.properties`**: a `dict` would be mutable; we use `MappingProxyType` to guarantee read-only at runtime while keeping the type hint as `Mapping[str, str]`. Documented in plan §X.
- **CYYMMDD edge cases**: `"0000000"` (the date is "year 1900-00-00") is technically invalid. The spec requires `parse_cymmdd` to raise `ValueError` for any unparseable input. Tests cover this.
- **Storing `datetime` in a frozen dataclass at scale (200,000 records)**: each `datetime` is roughly 50 bytes; 200k records is 10 MB. Acceptable. If memory pressure surfaces post-MVP, we revisit.
- **`StageStatus` enum vs string**: storing as string in SQLite trades type safety for portability across backends. We use `StageStatus.value` (a string) for persistence — see plan §X.

### 7.2 Open questions (resolve in plan.md)

- Should `MigrationRecord` use `dataclasses.field(default_factory=…)` for the `created_at` default, or pass it explicitly? Plan decides (recommendation: explicit constructor; no `field(default_factory=datetime.now)` because that re-evaluates on every default-build and tangles testability).
- Should `ResolvedMetadata` also expose `keys()` and `values()` methods explicitly, or rely on the implicit `Mapping` ABC behavior? Plan decides.
- Should the exception classes' structured context use `**kwargs` (loose) or explicit named parameters per subclass (strict)? Plan decides — recommendation is explicit per subclass to surface at type-check time.
- `S0Strategy.acquire` signature: `source_descriptor: str` or a structured object? Plan decides — recommendation is `str` for now (parsed by the strategy itself), revisit if it gets brittle.

---

## 8. Verification Strategy

| REQ block | Verification |
|-----------|--------------|
| REQ-001..018 (models) | unit tests in `tests/unit/domain/test_models.py`; mypy --strict; ruff |
| REQ-019..026 (ports) | unit tests in `tests/unit/domain/test_ports.py` (`abc.ABC` checks); mypy --strict |
| REQ-027..035 (exceptions) | unit tests in `tests/unit/domain/test_exceptions.py`; mypy --strict |
| REQ-036..041 (tests) | the very fact that tests pass under `pytest -m unit` + coverage ≥95% on domain/ + 0 mypy errors |
| Scenarios 4.1..4.9 | each maps to one or more named tests + the verification commands listed |

---

## 9. Cross-References

- Spec Kit conventions: `.specify/memory/constitution.md`, `CONTRIBUTING.md`
- Domain ground truth: `docs/domain/CMCOURIER_REBIRTH.md` (especially §3 RVABREP, §4 Modelo Documental, §6 Metadata Resolution, §9 Tracking, §10 Stages, §14.3 Port Definitions)
- Constitution Principles I, III, VI, VII, VIII, IX bind this change
- Plan: `specs/002-domain-models-and-ports/plan.md`
- Tasks: `specs/002-domain-models-and-ports/tasks.md`
- Predecessor change: `specs/001-bootstrap-python-skeleton/`

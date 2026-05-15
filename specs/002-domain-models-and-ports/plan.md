# Plan — 002-domain-models-and-ports

**Status**: Draft (under review)
**Created**: 2026-05-09
**Spec reference**: `specs/002-domain-models-and-ports/spec.md`
**Constitution version at draft time**: v1.0.0

> The **how** of this change. Describes architectural decisions for the domain types, the exception hierarchy structure, and the test approach. Implementation breakdown lives in `tasks.md`.

---

## 1. Approach Summary

Three Python files (`models.py`, `ports.py`, `exceptions.py`) populated under Strict TDD. Every public type lands as a failing test first, then the minimum code to make it pass, then refactor while green. The whole change is small enough (under ~600 lines of code total, including tests) that aggressive paralysis-by-design is the bigger risk than under-design.

The change is **boring on purpose**: dataclasses, abstract methods, exception subclasses. No clever metaclasses, no descriptors, no runtime type-introspection. Every line should be obvious to a reader who has not seen the code before.

---

## 2. Why dataclasses, not Pydantic

Constitution Principle I forbids `pydantic` in `domain/`. Period. So the choice is: stdlib `dataclasses`, `typing.NamedTuple`, or `attrs`.

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| `dataclasses` (stdlib, frozen+slots) | Standard library; well-known; supports frozen, slots, defaults, factories; mypy understands them perfectly | None worth listing | ✅ chosen |
| `typing.NamedTuple` | Tuple semantics (truthy comparison, unpack); slot-like by default | No `frozen=True` semantics for adding logic later; `__init__` validation requires `__new__`; awkward subclassing | rejected |
| `attrs` (third-party) | More features (slot detection, validators, converters) | Third-party — violates Principle I | rejected |

`@dataclass(frozen=True, slots=True)` for every model. Validation happens in a custom `__post_init__`.

---

## 3. Model File — `src/cmcourier/domain/models.py`

### 3.1 Top-level shape

```python
"""Domain models — pure stdlib, frozen dataclasses, the spec-§10 source of truth."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType

# Helpers (the spec) ---------------------------------

def parse_cymmdd(date_str: str) -> datetime: ...
def is_pdf_filename(name: str) -> bool: ...
def compute_cm_folder(clase_id: str) -> str: ...
def compute_cm_object_type(clase_id: str) -> str: ...

# Models -------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TriggerRecord: ...

@dataclass(frozen=True, slots=True)
class RVABREPDocument: ...

@dataclass(frozen=True, slots=True)
class CMMapping: ...

@dataclass(frozen=True, slots=True)
class ResolvedMetadata: ...

@dataclass(frozen=True, slots=True)
class StagedFile: ...

class StageStatus(str, Enum): ...

@dataclass(frozen=True, slots=True)
class MigrationRecord: ...
```

### 3.2 `parse_cymmdd`

The reference implementation in the domain spec:

```python
def parse_cymmdd(date_str: str) -> datetime:
    if not isinstance(date_str, str) or len(date_str) != 7 or not date_str.isdigit():
        raise ValueError(f"CYYMMDD requires 7 digits, got {date_str!r}")
    century = int(date_str[0])
    year = (1900 + century * 100) + int(date_str[1:3])
    month = int(date_str[3:5])
    day = int(date_str[5:7])
    return datetime(year, month, day)  # raises ValueError on bad m/d
```

Tests cover the canonical example (`"1251117"` → 2025-11-17) plus edge cases: too-short, non-digit, invalid month, invalid day.

### 3.3 Computed CM fields

```python
def compute_cm_folder(clase_id: str) -> str:
    return f"/$type/BAC_{clase_id.replace('.', '_')}"

def compute_cm_object_type(clase_id: str) -> str:
    return f"$t!-2_BAC_{clase_id.replace('.', '_')}v-1"
```

`CMMapping.cm_folder` and `CMMapping.cm_object_type` are `@property` accessors that delegate to these helpers, so the conversion is documented in one place.

### 3.4 `ResolvedMetadata`

The contract is "read-only mapping of `BAC_*` properties to string values". Internally:

```python
@dataclass(frozen=True, slots=True)
class ResolvedMetadata:
    properties: Mapping[str, str]

    @classmethod
    def from_dict(cls, d: Mapping[str, str]) -> "ResolvedMetadata":
        return cls(properties=MappingProxyType(dict(d)))

    def __getitem__(self, key: str) -> str: return self.properties[key]
    def __contains__(self, key: object) -> bool: return key in self.properties
    def __iter__(self) -> Iterator[str]: return iter(self.properties)
    def __len__(self) -> int: return len(self.properties)
```

`from_dict` is the only constructor encouraged. Callers never pass a raw `dict` directly (the type hint is `Mapping[str, str]`, but the runtime behavior of `MappingProxyType` ensures immutability).

### 3.5 `StageStatus`

```python
class StageStatus(str, Enum):
    S1_PENDING = "S1_PENDING"
    S1_DONE   = "S1_DONE"
    S1_FAILED = "S1_FAILED"
    # … same shape for S2..S5
    SKIPPED   = "SKIPPED"

    @classmethod
    def terminal_for_stage(cls, stage: int) -> tuple["StageStatus", "StageStatus"]:
        if not 1 <= stage <= 5:
            raise ValueError(f"stage must be 1..5, got {stage!r}")
        return (cls[f"S{stage}_DONE"], cls[f"S{stage}_FAILED"])
```

Inheriting from `str, Enum` makes `StageStatus.S1_DONE.value == "S1_DONE"` and `str(StageStatus.S1_DONE) == "StageStatus.S1_DONE"`. Persistence layers store `.value` as the SQL column.

### 3.6 `MigrationRecord` defaults

```python
@dataclass(frozen=True, slots=True)
class MigrationRecord:
    trigger_shortname: str
    trigger_cif: str
    trigger_system_id: str
    rvabrep_txn_num: str
    rvabrep_file_name: str
    status: StageStatus
    created_at: datetime

    cm_object_id: str | None = None
    cm_folder: str | None = None
    cm_object_type: str | None = None
    error_message: str | None = None
    source_file_path: str | None = None
    page_count: int | None = None
    file_size_bytes: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0
```

**Open question resolved (spec §7.2)**: `created_at` is a **required** parameter, not a default factory. Reasons:
1. Tests need to pass deterministic datetimes; `default_factory=datetime.now` re-evaluates per call and breaks fixture reuse.
2. The persistence layer is the source of `created_at` (it knows when the row was inserted), not the model class.
3. Explicit > implicit (Python zen).

### 3.7 Frozen-ness validation

`@dataclass(frozen=True)` already raises `dataclasses.FrozenInstanceError` on attribute assignment. No extra code needed for REQ-016.

`@dataclass(slots=True)` adds `__slots__` to the generated class, which:
- Reduces per-instance memory by ~30-50%.
- Prevents accidental `record.unknown_attr = ...` (raises `AttributeError`).
- Is mandatory for instances stored at scale (200k+ documents per migration).

### 3.8 Module-level re-exports

`domain/__init__.py` currently has only a docstring. After this change:

```python
"""Domain layer — pure Python, zero external dependencies (Constitution Principle I)."""

from cmcourier.domain.exceptions import (
    AssemblyError, CMCourierError, CMISClientError, CMISServerError,
    ConfigurationError, DefaultValidationFailedError, IDRViNotMappedError,
    IndexingError, MappingError, MetadataError, PDFAssemblyFailedError,
    RVABREPDeletedError, RVABREPDuplicateError, RVABREPNotFoundError,
    RetriesExhaustedError, SourceFailedError, SourceFileMissingError,
    TrackingError, TriggerError, UploadError,
)
from cmcourier.domain.models import (
    CMMapping, MigrationRecord, ResolvedMetadata, RVABREPDocument,
    StageStatus, StagedFile, TriggerRecord,
    compute_cm_folder, compute_cm_object_type, is_pdf_filename, parse_cymmdd,
)
from cmcourier.domain.ports import (
    IAssembler, IDataSource, ITrackingStore, IUploader, S0Strategy,
)

__all__ = [...]
```

`__all__` lists every name above, in alphabetical order. Pre-commit's ruff catches drift between imports and `__all__` (rule `F405` family).

---

## 4. Ports File — `src/cmcourier/domain/ports.py`

### 4.1 Top-level shape

```python
"""Abstract interfaces (ports) implemented by adapters in 003+."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from typing import Any

from cmcourier.domain.models import (
    MigrationRecord, RVABREPDocument, StageStatus, StagedFile, TriggerRecord,
)


class IDataSource(ABC):
    @abstractmethod
    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def query_stream(self, sql: str, params: list[Any] | None = None) -> Iterator[dict[str, Any]]: ...

    @abstractmethod
    def get_by_fields(self, filters: Mapping[str, Any]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_by_fields_in(
        self, field: str, values: list[Any], fixed_filters: Mapping[str, Any]
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_all(self) -> Iterator[dict[str, Any]]: ...

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def close(self) -> None: ...


class ITrackingStore(ABC):
    # idempotency anchor across batches
    @abstractmethod
    def is_uploaded(self, txn_num: str) -> bool: ...

    # per-stage state machine
    @abstractmethod
    def is_stage_done(self, txn_num: str, batch_id: str, stage: StageStatus) -> bool: ...

    @abstractmethod
    def mark_stage_pending(self, record: MigrationRecord, stage: StageStatus) -> None: ...

    @abstractmethod
    def mark_stage_done(self, txn_num: str, batch_id: str, stage: StageStatus) -> None: ...

    @abstractmethod
    def mark_stage_failed(
        self, txn_num: str, batch_id: str, stage: StageStatus, error: str
    ) -> None: ...

    # batch lifecycle
    @abstractmethod
    def start_batch(self, total_records: int) -> str: ...

    @abstractmethod
    def complete_batch(self, batch_id: str) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class IAssembler(ABC):
    @abstractmethod
    def assemble(self, document: RVABREPDocument) -> StagedFile: ...


class IUploader(ABC):
    @abstractmethod
    def ensure_folder(self, folder_path: str) -> None: ...

    @abstractmethod
    def upload(
        self,
        file: StagedFile,
        folder_path: str,
        object_type_id: str,
        document_name: str,
        mime_type: str,
        properties: Mapping[str, str],
    ) -> str: ...

    @abstractmethod
    def test_connection(self) -> Mapping[str, str]: ...


class S0Strategy(ABC):
    @abstractmethod
    def acquire(self, source_descriptor: str) -> Iterator[TriggerRecord]: ...
```

### 4.2 Decision: `Any` for `IDataSource` row values

Database row values are heterogeneous (`str | int | datetime | None | Decimal | bytes`). Forcing a tighter type would force adapters to coerce in places that are properly the responsibility of the service layer. The service layer reads the dict by known column name and constructs the typed model from it.

`Any` here is intentional and documented. mypy --strict accepts it because we declare it explicitly.

### 4.3 Decision: `Mapping[str, Any]` over `dict[str, Any]` for `filters` parameters

`Mapping` is the read-only protocol; adapters must not mutate the caller's dict. Static, intentional contract.

### 4.4 Decision: `S0Strategy.acquire` returns `Iterator`, not `list`

Trigger lists can be huge (hundreds of thousands of rows). the spec ("trigger lists are iterated, never fully loaded into memory") demands streaming.

---

## 5. Exception File — `src/cmcourier/domain/exceptions.py`

### 5.1 Hierarchy

```
CMCourierError
├── ConfigurationError
├── TriggerError                  (S0)
├── IndexingError                 (S1)
│   ├── RVABREPNotFoundError
│   ├── RVABREPDeletedError
│   └── RVABREPDuplicateError
├── MappingError                  (S2)
│   └── IDRViNotMappedError
├── MetadataError                 (S3)
│   ├── SourceFailedError
│   └── DefaultValidationFailedError
├── AssemblyError                 (S4)
│   ├── SourceFileMissingError
│   └── PDFAssemblyFailedError
├── UploadError                   (S5)
│   ├── CMISClientError           (HTTP 4xx — fail fast)
│   ├── CMISServerError           (HTTP 5xx — retry)
│   └── RetriesExhaustedError
└── TrackingError                 (S6 — never blocks pipeline)
```

### 5.2 Base class — structured context

```python
class CMCourierError(Exception):
    """Root of the CMCourier exception hierarchy."""

    def __init__(self, message: str = "", **context: object) -> None:
        self.context: dict[str, object] = dict(context)
        if context:
            ctx_str = ", ".join(f"{k}={v!r}" for k, v in context.items())
            full = f"{message} [{ctx_str}]" if message else ctx_str
        else:
            full = message
        super().__init__(full)
```

Subclasses inherit this. They define **explicit** named parameters when there are well-known context keys (e.g., `IDRViNotMappedError(id_rvi=...)`).

**Open question resolved (spec §7.2)**: explicit named parameters per subclass, not loose `**kwargs`. Reason: type-checkers catch typos in production code (`raise IDRViNotMappedError(id_rvi="X")` vs `raise IDRViNotMappedError(idrvi="X")`).

### 5.3 Subclass example

```python
class IDRViNotMappedError(MappingError):
    """The ID RVI is not present in the Modelo Documental."""

    def __init__(self, *, id_rvi: str, txn_num: str | None = None) -> None:
        super().__init__(
            "ID RVI not mapped in Modelo Documental",
            id_rvi=id_rvi,
            txn_num=txn_num,
        )
        self.id_rvi = id_rvi
        self.txn_num = txn_num
```

The instance carries strongly-typed attributes (`exc.id_rvi`) for handlers, plus the `context` dict for structured logging.

### 5.4 Why we don't use `cmcourier.errors` or similar

The domain layer is the home of the project's vocabulary. Errors are part of the vocabulary. Putting them in `domain/exceptions.py` (next to the models that raise them and the ports that document them) keeps the dependency graph clean. No circular imports — exceptions are leaves.

---

## 6. Test Strategy

### 6.1 Files

```
tests/unit/domain/
├── __init__.py            (already exists)
├── test_models.py         NEW
├── test_ports.py          NEW
└── test_exceptions.py     NEW
```

### 6.2 `test_models.py` shape

One test class per model. Within each class, methods follow the Red → Green → Refactor flow:

```python
class TestTriggerRecord:
    def test_construction_with_valid_inputs(self) -> None: ...
    def test_construction_with_empty_shortname_raises(self) -> None: ...
    def test_construction_with_empty_system_id_raises(self) -> None: ...
    def test_cif_can_be_none(self) -> None: ...
    def test_is_frozen(self) -> None: ...

class TestRVABREPDocument:
    # construction with all fields
    # is_pdf for *.PDF, *.001, *.tif
    # is_deleted for empty / "D"
    # frozen
    ...

class TestParseCymmdd:
    def test_canonical_example(self) -> None:
        assert parse_cymmdd("1251117") == datetime(2025, 11, 17)
    def test_too_short(self) -> None: ...
    def test_non_digit(self) -> None: ...
    def test_invalid_month(self) -> None: ...
    def test_invalid_day(self) -> None: ...

class TestCMMapping:
    # construction
    # cm_folder (the spec example)
    # cm_object_type (the spec example)
    ...

class TestResolvedMetadata: ...
class TestStagedFile: ...
class TestStageStatus:
    def test_value_equals_name(self) -> None: ...
    def test_terminal_for_stage(self) -> None: ...
    def test_terminal_for_stage_invalid(self) -> None: ...

class TestMigrationRecord: ...
```

### 6.3 `test_ports.py` shape

```python
import abc
from cmcourier.domain.ports import IDataSource, ITrackingStore, IAssembler, IUploader, S0Strategy

@pytest.mark.parametrize("port_cls", [IDataSource, ITrackingStore, IAssembler, IUploader, S0Strategy])
def test_port_is_abstract(port_cls: type) -> None:
    assert issubclass(port_cls, abc.ABC)
    with pytest.raises(TypeError):
        port_cls()  # type: ignore[abstract]

# also a test per port that lists abstract methods to detect accidental drift
```

### 6.4 `test_exceptions.py` shape

```python
class TestHierarchy:
    @pytest.mark.parametrize("exc_cls,parent", [
        (ConfigurationError, CMCourierError),
        (TriggerError, CMCourierError),
        (IndexingError, CMCourierError),
        (RVABREPNotFoundError, IndexingError),
        # ... full table
    ])
    def test_subclass_relationship(self, exc_cls, parent) -> None:
        assert issubclass(exc_cls, parent)

class TestStructuredContext:
    def test_context_in_str(self) -> None:
        exc = IDRViNotMappedError(id_rvi="ZZ99")
        assert "ZZ99" in str(exc)
        assert exc.id_rvi == "ZZ99"
```

### 6.5 Coverage target

≥ 95% branch coverage on `src/cmcourier/domain/`. Achievable because the layer is small and every branch in `parse_cymmdd` and `__post_init__` is testable.

---

## 7. CHANGELOG entry shape

After this change merges:

```markdown
## [0.4.0] — 2026-05-XX

### Added

- `cmcourier.domain.models`: frozen dataclasses for `TriggerRecord`, `RVABREPDocument`, `CMMapping`, `ResolvedMetadata`, `StagedFile`, `MigrationRecord`. The `StageStatus` enum encodes the per-stage state machine from the spec. Helper functions `parse_cymmdd`, `is_pdf_filename`, `compute_cm_folder`, `compute_cm_object_type` are exposed for direct use by services.
- `cmcourier.domain.ports`: abstract interfaces `IDataSource`, `ITrackingStore`, `IAssembler`, `IUploader`, and `S0Strategy`. Concrete implementations land in 003+.
- `cmcourier.domain.exceptions`: typed exception hierarchy rooted at `CMCourierError`, with stage-specific subclasses and structured context fields for logging.
- `tests/unit/domain/{test_models,test_ports,test_exceptions}.py`: full unit coverage of the domain layer (≥95% branches).

### Rationale

- Provides the stable contract that every adapter (003+) and service (004+) will build against. Without this layer, no concrete code can be written without inventing types ad-hoc.
- All dataclasses are `frozen=True, slots=True` to make accidental mutation impossible and reduce per-instance memory footprint at scale.
- Exceptions carry structured context (`txn_num`, `id_rvi`, `batch_id`) for structured logging in the observability layer.
```

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `parse_cymmdd` edge cases miss exotic AS400 dates | Exhaustive table-driven tests including `"0000000"`, `"1991301"` (invalid month), etc. |
| `MappingProxyType` confuses mypy in some contexts | Tested with `mypy --strict`; the `Mapping[str, str]` annotation is what mypy sees, the runtime type is internal |
| Adding a new stage later breaks `StageStatus.terminal_for_stage` | Documented in plan; the function is one screen long; trivial to extend with bound check change |
| Exception subclass count grows unwieldy | Hierarchy is intentionally shallow (max depth 3); each subclass has a clear stage owner |
| `domain/__init__.py` re-export drift | Pre-commit ruff catches unused-import / unused-name issues; `__all__` is explicit |
| Tests get duplicated across the project | This change ships the **only** unit tests for the domain; later changes test their own layer against these models, never re-test the models |

---

## 9. Phases (mirrored in `tasks.md`)

1. **Exceptions** — leaves of the dependency graph; tests + code.
2. **`StageStatus` enum** — pure stdlib; needed by `MigrationRecord` and ports.
3. **Helpers + simple models** — `parse_cymmdd`, `is_pdf_filename`, `compute_cm_folder/_object_type`, `TriggerRecord`, `StagedFile`, `ResolvedMetadata`.
4. **Complex models** — `RVABREPDocument` (with `is_pdf`/`is_deleted` properties), `CMMapping` (with computed properties), `MigrationRecord` (with status field referring to `StageStatus`).
5. **Ports** — abstract interfaces using all the models above.
6. **`domain/__init__.py` re-exports** — final step before verification.
7. **Verification + commit**.

Phases 1-5 are **strict TDD per type**: red test → green code → refactor.

---

## 10. Cross-References

- Spec: `specs/002-domain-models-and-ports/spec.md`
- Tasks: `specs/002-domain-models-and-ports/tasks.md`
- Constitution: `.specify/memory/constitution.md` (Principles I, III, VI, VII, VIII, IX)
- Domain ground truth: the project's domain spec §3, §4, §6, §9, §10, §14.3
- Predecessor change: `specs/001-bootstrap-python-skeleton/`

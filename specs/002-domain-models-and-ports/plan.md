# Plan — 002-domain-models-and-ports

**Status**: Borrador (en revisión)
**Creado**: 2026-05-09
**Referencia al spec**: `specs/002-domain-models-and-ports/spec.md`
**Versión de la constitución al momento del borrador**: v1.0.0

> El **cómo** de este cambio. Describe decisiones arquitectónicas para los tipos del dominio, la estructura de la jerarquía de excepciones, y el enfoque de tests. El desglose de implementación vive en `tasks.md`.

---

## 1. Resumen del Enfoque

Tres archivos Python (`models.py`, `ports.py`, `exceptions.py`) poblados bajo `Strict TDD`. Cada tipo público aterriza como un test que falla primero, después el mínimo código para hacerlo pasar, después refactor mientras está en verde. El cambio completo es lo suficientemente chico (menos de ~600 líneas de código en total, incluyendo tests) como para que la parálisis por sobre-diseño sea el riesgo más grande que el sub-diseño.

El cambio es **aburrido a propósito**: `dataclasses`, métodos abstractos, subclases de excepciones. Sin metaclases inteligentes, sin `descriptors`, sin introspección de tipos en `runtime`. Cada línea debería ser obvia para alguien que nunca vio el código antes.

---

## 2. Por qué dataclasses, no Pydantic

El Principio I de la Constitución prohíbe `pydantic` en `domain/`. Punto. Así que la elección es: `dataclasses` de la `stdlib`, `typing.NamedTuple`, o `attrs`.

| Opción | Pros | Contras | Veredicto |
|--------|------|---------|-----------|
| `dataclasses` (stdlib, frozen+slots) | Librería estándar; bien conocida; soporta `frozen`, `slots`, `defaults`, `factories`; mypy las entiende perfectamente | Ninguno digno de listar | ✅ elegida |
| `typing.NamedTuple` | Semántica de tupla (comparación `truthy`, `unpack`); tipo `slot-like` por default | Sin semántica `frozen=True` para agregar lógica después; la validación en `__init__` requiere `__new__`; `subclassing` incómodo | rechazada |
| `attrs` (third-party) | Más features (detección de `slots`, validadores, conversores) | Third-party — viola el Principio I | rechazada |

`@dataclass(frozen=True, slots=True)` para cada modelo. La validación sucede en un `__post_init__` custom.

---

## 3. Archivo de Modelos — `src/cmcourier/domain/models.py`

### 3.1 Forma de top-level

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

La implementación de referencia en la `domain spec`:

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

Los tests cubren el ejemplo canónico (`"1251117"` → 2025-11-17) más casos `edge`: demasiado corto, no-dígito, mes inválido, día inválido.

### 3.3 Campos CM computados

```python
def compute_cm_folder(clase_id: str) -> str:
    return f"/$type/BAC_{clase_id.replace('.', '_')}"

def compute_cm_object_type(clase_id: str) -> str:
    return f"$t!-2_BAC_{clase_id.replace('.', '_')}v-1"
```

`CMMapping.cm_folder` y `CMMapping.cm_object_type` son `@property` `accessors` que delegan a estos helpers, así la conversión queda documentada en un solo lugar.

### 3.4 `ResolvedMetadata`

El contrato es "mapping `read-only` de propiedades `BAC_*` a valores `string`". Internamente:

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

`from_dict` es el único constructor recomendado. Quienes lo usen nunca pasan un `dict` crudo directamente (el `type hint` es `Mapping[str, str]`, pero el comportamiento en `runtime` de `MappingProxyType` asegura inmutabilidad).

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

Heredar de `str, Enum` hace que `StageStatus.S1_DONE.value == "S1_DONE"` y `str(StageStatus.S1_DONE) == "StageStatus.S1_DONE"`. Las capas de persistencia almacenan `.value` como la columna SQL.

### 3.6 Defaults de `MigrationRecord`

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

**Pregunta abierta resuelta (spec §7.2)**: `created_at` es un parámetro **requerido**, no un `default factory`. Razones:
1. Los tests necesitan pasar `datetimes` determinísticos; `default_factory=datetime.now` re-evalúa por llamada y rompe la reusabilidad de `fixtures`.
2. La capa de persistencia es la fuente de `created_at` (sabe cuándo se insertó la fila), no la clase del modelo.
3. Explícito > implícito (Python zen).

### 3.7 Validación de frozen-ness

`@dataclass(frozen=True)` ya levanta `dataclasses.FrozenInstanceError` al asignar atributos. No se necesita código extra para REQ-016.

`@dataclass(slots=True)` agrega `__slots__` a la clase generada, lo que:
- Reduce la memoria por instancia en ~30-50%.
- Previene `record.unknown_attr = ...` accidental (levanta `AttributeError`).
- Es obligatorio para instancias almacenadas a escala (200k+ documentos por migración).

### 3.8 Re-exports a nivel de módulo

`domain/__init__.py` actualmente tiene solamente un `docstring`. Después de este cambio:

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

`__all__` lista cada nombre de arriba, en orden alfabético. El `ruff` del `pre-commit` captura el `drift` entre imports y `__all__` (familia de reglas `F405`).

---

## 4. Archivo de Ports — `src/cmcourier/domain/ports.py`

### 4.1 Forma de top-level

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

### 4.2 Decisión: `Any` para los valores de fila de `IDataSource`

Los valores de filas de base de datos son heterogéneos (`str | int | datetime | None | Decimal | bytes`). Forzar un tipo más estricto forzaría a los adaptadores a hacer `coerce` en lugares que son propiamente responsabilidad de la capa de servicios. La capa de servicios lee el `dict` por nombre de columna conocido y construye el modelo tipado a partir de él.

`Any` acá es intencional y documentado. `mypy --strict` lo acepta porque lo declaramos explícitamente.

### 4.3 Decisión: `Mapping[str, Any]` sobre `dict[str, Any]` para parámetros `filters`

`Mapping` es el protocolo `read-only`; los adaptadores no deben mutar el `dict` del `caller`. Contrato estático e intencional.

### 4.4 Decisión: `S0Strategy.acquire` retorna `Iterator`, no `list`

Las listas de `triggers` pueden ser enormes (cientos de miles de filas). El `spec` ("las listas de trigger se iteran, nunca se cargan completamente en memoria") demanda `streaming`.

---

## 5. Archivo de Excepciones — `src/cmcourier/domain/exceptions.py`

### 5.1 Jerarquía

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

### 5.2 Clase base — contexto estructurado

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

Las subclases heredan esto. Definen parámetros nombrados **explícitos** cuando hay claves de contexto bien conocidas (por ejemplo, `IDRViNotMappedError(id_rvi=...)`).

**Pregunta abierta resuelta (spec §7.2)**: parámetros nombrados explícitos por subclase, no `**kwargs` laxos. Razón: los `type-checkers` capturan `typos` en código de producción (`raise IDRViNotMappedError(id_rvi="X")` vs `raise IDRViNotMappedError(idrvi="X")`).

### 5.3 Ejemplo de subclase

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

La instancia lleva atributos fuertemente tipados (`exc.id_rvi`) para los `handlers`, más el `dict` `context` para `logging` estructurado.

### 5.4 Por qué no usamos `cmcourier.errors` o similar

La capa de dominio es el hogar del vocabulario del proyecto. Los errores son parte del vocabulario. Ponerlos en `domain/exceptions.py` (al lado de los modelos que los levantan y los `ports` que los documentan) mantiene el grafo de dependencias limpio. Sin imports circulares — las excepciones son hojas.

---

## 6. Estrategia de Tests

### 6.1 Archivos

```
tests/unit/domain/
├── __init__.py            (already exists)
├── test_models.py         NEW
├── test_ports.py          NEW
└── test_exceptions.py     NEW
```

### 6.2 Forma de `test_models.py`

Una clase de test por modelo. Dentro de cada clase, los métodos siguen el flujo `Red → Green → Refactor`:

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

### 6.3 Forma de `test_ports.py`

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

### 6.4 Forma de `test_exceptions.py`

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

### 6.5 Objetivo de coverage

≥ 95% de `branch coverage` en `src/cmcourier/domain/`. Alcanzable porque la capa es chica y cada `branch` en `parse_cymmdd` y `__post_init__` es testeable.

---

## 7. Forma de la entrada del CHANGELOG

Después de que este cambio se mergee:

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

## 8. Riesgos y Mitigaciones

| Riesgo | Mitigación |
|--------|------------|
| Los casos `edge` de `parse_cymmdd` no capturan fechas AS400 exóticas | Tests exhaustivos dirigidos por tabla incluyendo `"0000000"`, `"1991301"` (mes inválido), etc. |
| `MappingProxyType` confunde a mypy en algunos contextos | Testeado con `mypy --strict`; la anotación `Mapping[str, str]` es lo que mypy ve, el tipo en `runtime` es interno |
| Agregar un `stage` nuevo después rompe `StageStatus.terminal_for_stage` | Documentado en el `plan`; la función ocupa una pantalla; trivial extender con cambio en el chequeo de límites |
| El conteo de subclases de excepciones se vuelve inmanejable | La jerarquía es intencionalmente plana (profundidad máxima 3); cada subclase tiene un `stage` owner claro |
| `Drift` de re-exports en `domain/__init__.py` | El `ruff` del `pre-commit` captura `unused-import` / `unused-name`; `__all__` es explícito |
| Los tests se duplican a lo largo del proyecto | Este cambio entrega los **únicos** `unit tests` para el dominio; los cambios posteriores testean su propia capa contra estos modelos, nunca re-testean los modelos |

---

## 9. Fases (espejadas en `tasks.md`)

1. **Excepciones** — hojas del grafo de dependencias; tests + código.
2. **Enum `StageStatus`** — `stdlib` puro; necesario para `MigrationRecord` y los `ports`.
3. **Helpers + modelos simples** — `parse_cymmdd`, `is_pdf_filename`, `compute_cm_folder/_object_type`, `TriggerRecord`, `StagedFile`, `ResolvedMetadata`.
4. **Modelos complejos** — `RVABREPDocument` (con propiedades `is_pdf`/`is_deleted`), `CMMapping` (con propiedades computadas), `MigrationRecord` (con campo `status` que referencia `StageStatus`).
5. **Ports** — interfaces abstractas usando todos los modelos de arriba.
6. **Re-exports en `domain/__init__.py`** — paso final antes de la verificación.
7. **Verificación + commit**.

Las fases 1-5 son **`Strict TDD` por tipo**: test red → código verde → refactor.

---

## 10. Referencias Cruzadas

- Spec: `specs/002-domain-models-and-ports/spec.md`
- Tasks: `specs/002-domain-models-and-ports/tasks.md`
- Constitución: `.specify/memory/constitution.md` (Principios I, III, VI, VII, VIII, IX)
- Fuente de verdad del dominio: la `domain spec` del proyecto §3, §4, §6, §9, §10, §14.3
- Cambio predecesor: `specs/001-bootstrap-python-skeleton/`

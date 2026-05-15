# Spec — 002-domain-models-and-ports

**Status**: Borrador (en revisión)
**Creado**: 2026-05-09
**Autor**: bitBreaker
**Versión de la constitución al momento del borrador**: v1.0.0
**Depende de**: 001-bootstrap-python-skeleton (mergeado)

> El **qué** de este cambio. Llena la capa de dominio vacía con modelos, `ports` y la jerarquía tipada de excepciones. El **cómo** vive en `plan.md`. El checklist de implementación vive en `tasks.md`.

---

## 1. Intención

Llenar `src/cmcourier/domain/` con los **`dataclasses`, interfaces abstractas y jerarquía de excepciones** sobre los que se va a construir cada otra capa de CMCourier. Una vez que este cambio se mergee, el siguiente cambio puede empezar a escribir adaptadores concretos y servicios contra contratos de dominio estables.

El cambio entrega:
- **Modelos** en `models.py` — `dataclasses` `frozen` para `TriggerRecord`, `RVABREPDocument`, `CMMapping`, `ResolvedMetadata`, `StagedFile`, `MigrationRecord`, más el enum `StageStatus`.
- **Ports** en `ports.py` — interfaces abstractas para `IDataSource`, `ITrackingStore`, `IAssembler`, `IUploader`, y `S0Strategy` (según la arquitectura por `stage`).
- **Excepciones** en `exceptions.py` — jerarquía tipada de excepciones con raíz en `CMCourierError`, organizada por `stage` y modo de falla.
- **Funciones helper** estrictamente en soporte de los modelos: `parse_cymmdd()`, `compute_cm_folder()` y `compute_cm_object_type()`, `is_pdf_filename()`.

Todo bajo el Principio I de la Constitución (cero deps externas en `domain/`) y `Strict TDD` (`Red → Green` por tipo).

---

## 2. Por qué ahora

- El esqueleto del `bootstrap` colocó archivos vacíos `models.py`, `ports.py`, `exceptions.py`. Nada los importa; nada se puede implementar contra ellos.
- Todos los adaptadores concretos (CSV, AS400, SQLite, CMIS, ensamblado de PDF) necesitan que `IDataSource`, `ITrackingStore`, `IAssembler`, `IUploader` existan como abstracciones antes de que tengan algo que implementar.
- Todos los servicios (`mapping`, `metadata`, `trigger`, `document`) necesitan que las estructuras de datos (`RVABREPDocument`, `CMMapping`, `ResolvedMetadata`) estén definidas antes de que tengan algo que manipular.
- El `stage` S2 (Document Class Mapping) necesita que `MappingError` aparezca específicamente; el `stage` S3 (Metadata Resolution) necesita `MetadataError`. Estos tipos de excepciones deben existir antes de que los servicios los levanten.
- 002 es el **camino más corto** desde "esqueleto listo" hasta "primer adaptador concreto posible" (que es 003).

---

## 3. Requisitos

### 3.1 Modelos de dominio (REQ-001 a REQ-018)

- **REQ-001** — DEBE existir un `dataclass` `TriggerRecord` exponiendo `shortname: str`, `cif: str | None`, `system_id: str`. DEBE ser `frozen`, `slotted`, y aceptar un `shortname` no vacío y un `system_id` no vacío (caso contrario se levanta `ValueError`). `cif` PUEDE ser `None` para soportar la regla de `CIF self-healing`.
- **REQ-002** — DEBE existir un `dataclass` `RVABREPDocument` exponiendo cada columna RVABREP listada en el `spec` (`system_code`, `txn_num`, `index1` … `index7`, `image_type`, `image_path`, `file_name`, `creation_date`, `last_view_date`, `total_pages`, `delete_code`). Los tipos de los campos DEBEN seguir la `domain spec` (por ejemplo, `creation_date` es un `datetime`, `total_pages` es un `int`, `delete_code` es un `str`). DEBE ser `frozen` y `slotted`.
- **REQ-003** — `RVABREPDocument` DEBE exponer una propiedad `is_pdf: bool` derivada de `file_name.upper().endswith('.PDF')`.
- **REQ-004** — `RVABREPDocument` DEBE exponer una propiedad `is_deleted: bool` que retorna `True` cuando `delete_code` no está vacío.
- **REQ-005** — DEBE existir un helper a nivel de módulo `parse_cymmdd(date_str: str) -> datetime` que parsea el formato `CYYMMDD` de 7 dígitos de AS400. Entradas inválidas DEBEN levantar `ValueError`. La función vive en `domain/models.py` porque es intrínseca al modelo.
- **REQ-006** — DEBE existir un helper a nivel de módulo `is_pdf_filename(name: str) -> bool` que retorna `name.upper().endswith('.PDF')` para que `RVABREPDocument.is_pdf` y otros `call sites` puedan compartir una sola fuente de verdad.
- **REQ-007** — DEBE existir un `dataclass` `CMMapping` exponiendo `clase_id: str`, `id_rvi: str`, `id_corto: str`, `clase_name: str`, `required_metadata_fields: tuple[str, ...]`. DEBE ser `frozen` y `slotted`.
- **REQ-008** — `CMMapping` DEBE exponer propiedades computadas `read-only` `cm_folder: str` y `cm_object_type: str`, derivadas según el `spec`, (`f"/$type/BAC_{normalized}"` y `f"$t!-2_BAC_{normalized}v-1"` donde `normalized = clase_id.replace('.', '_')`).
- **REQ-009** — DEBEN existir helpers a nivel de módulo `compute_cm_folder(clase_id)` y `compute_cm_object_type(clase_id)` para que la misma lógica sea reusable fuera del modelo (por ejemplo, para validación `pre-flight`).
- **REQ-010** — DEBE existir un `dataclass` `ResolvedMetadata` exponiendo `properties: Mapping[str, str]` (una vista `read-only`; el tipo subyacente es un `dict[str, str]` pero almacenado como `MappingProxyType` por seguridad). DEBE ser `frozen` y `slotted`. DEBE exponer `__getitem__`, `__contains__`, `__iter__`, `__len__` como un `mapping` `read-only`.
- **REQ-011** — DEBE existir un `dataclass` `StagedFile` exponiendo `path: Path`, `size_bytes: int`, `page_count: int`. DEBE ser `frozen` y `slotted`. `size_bytes` y `page_count` DEBEN ser no-negativos (caso contrario levantar `ValueError`).
- **REQ-012** — DEBE existir un enum `StageStatus` con los valores de la máquina de estados por `stage` del `spec`: `S1_PENDING`, `S1_DONE`, `S1_FAILED`, `S2_PENDING`, `S2_DONE`, `S2_FAILED`, `S3_PENDING`, `S3_DONE`, `S3_FAILED`, `S4_PENDING`, `S4_DONE`, `S4_FAILED`, `S5_PENDING`, `S5_DONE`, `S5_FAILED`, más `SKIPPED` (idempotencia: ya subido). Cada valor DEBE ser un `string` igual a su nombre (por ejemplo, `StageStatus.S1_DONE.value == "S1_DONE"`) para que las capas de persistencia puedan almacenarlo directamente.
- **REQ-013** — `StageStatus` DEBE exponer un método de clase `terminal_for_stage(stage: int) -> tuple["StageStatus", "StageStatus"]` que retorna `(Sn_DONE, Sn_FAILED)` para el número de `stage` dado. Un `stage` inválido DEBE levantar `ValueError`.
- **REQ-014** — DEBE existir un `dataclass` `MigrationRecord` exponiendo los campos documentados en el `spec` (`trigger_shortname`, `trigger_cif`, `trigger_system_id`, `rvabrep_txn_num`, `rvabrep_file_name`, `cm_object_id` (`str | None`), `cm_folder` (`str | None`), `cm_object_type` (`str | None`), `status: StageStatus`, `error_message: str | None`, `source_file_path: str | None`, `page_count: int | None`, `file_size_bytes: int | None`, `started_at: datetime | None`, `completed_at: datetime | None`, `retry_count: int`, `created_at: datetime`).
- **REQ-015** — `MigrationRecord` DEBE ser `frozen` y `slotted`. Los campos requeridos son `trigger_shortname`, `trigger_cif`, `trigger_system_id`, `rvabrep_txn_num`, `rvabrep_file_name`, `status`, `created_at`. Todos los demás tienen `defaults` explícitos de `None` / cero.
- **REQ-016** — Todos los `dataclasses` DEBEN ser `frozen` (inmutables) y `slotted` (`@dataclass(frozen=True, slots=True)`) para hacer imposible la mutación accidental y para mantener el `memory footprint` chico a escala (200.000 documentos en vuelo es plausible).
- **REQ-017** — `domain/models.py` NO DEBE importar nada fuera de la librería estándar de Python. Sin `pydantic`, sin `pandas`, sin ningún módulo `third-party` de ningún tipo. Los únicos imports `from` permitidos son `dataclasses`, `datetime`, `enum`, `pathlib`, `types`, `collections.abc`, y typing estándar.
- **REQ-018** — `domain/models.py` y `domain/__init__.py` DEBEN re-exportar cada nombre público (`TriggerRecord`, `RVABREPDocument`, `CMMapping`, `ResolvedMetadata`, `StagedFile`, `StageStatus`, `MigrationRecord`, `parse_cymmdd`, `is_pdf_filename`, `compute_cm_folder`, `compute_cm_object_type`) para que quienes lo usan escriban `from cmcourier.domain import TriggerRecord` y no `from cmcourier.domain.models import TriggerRecord`.

### 3.2 Ports — interfaces abstractas (REQ-019 a REQ-026)

- **REQ-019** — DEBE existir `IDataSource` (clase base abstracta) con los métodos listados en el `spec`: `query`, `query_stream`, `get_by_fields`, `get_by_fields_in`, `get_all`, `count`, `close`. Las firmas coinciden con la `domain spec` exactamente.
- **REQ-020** — DEBE existir `ITrackingStore` (clase base abstracta) con métodos `stage-aware` que coinciden con la nueva arquitectura en el `spec`: `is_stage_done(txn_num: str, batch_id: str, stage: StageStatus) -> bool`, `mark_stage_pending(record: MigrationRecord, stage: StageStatus) -> None`, `mark_stage_done(txn_num: str, batch_id: str, stage: StageStatus) -> None`, `mark_stage_failed(txn_num: str, batch_id: str, stage: StageStatus, error: str) -> None`, más los métodos del ciclo de vida del `batch` `start_batch(total_records: int) -> str`, `complete_batch(batch_id: str) -> None`, `is_uploaded(txn_num: str) -> bool` (ancla de idempotencia entre `batches`), `close() -> None`.
- **REQ-021** — DEBE existir `IAssembler` con `assemble(document: RVABREPDocument) -> StagedFile` (levanta `AssemblyError` ante falla).
- **REQ-022** — DEBE existir `IUploader` con `ensure_folder(folder_path: str) -> None`, `upload(file: StagedFile, folder_path: str, object_type_id: str, document_name: str, mime_type: str, properties: Mapping[str, str]) -> str` (retorna el `objectId` de CM; levanta `UploadError` ante falla), y `test_connection() -> Mapping[str, str]`.
- **REQ-023** — DEBE existir `S0Strategy` (clase base abstracta) con `acquire(source_descriptor: str) -> Iterator[TriggerRecord]`. Las estrategias concretas mapean a los cuatro modos de fuente de `trigger` del `spec` (`csv:`, `as400:`, `direct_rvabrep`, `local_scan`). La implementación de esas estrategias concretas NO está en este cambio — solamente la interfaz.
- **REQ-024** — Cada `port` DEBE definirse como `abc.ABC` con decoradores `@abstractmethod`. Las subclases concretas (construidas en 003+) las implementan.
- **REQ-025** — `domain/ports.py` NO DEBE importar nada fuera de la librería estándar más `cmcourier.domain.models` (para `type hints`). Sin `pydantic`, sin `requests`, sin `pyodbc`.
- **REQ-026** — `domain/__init__.py` DEBE re-exportar cada nombre de `port` para que quienes lo usan escriban `from cmcourier.domain import IDataSource`.

### 3.3 Jerarquía de excepciones (REQ-027 a REQ-035)

- **REQ-027** — `CMCourierError` DEBE ser la raíz de la jerarquía tipada de excepciones del proyecto. Hereda de `Exception`. Ningún código fuera de `domain/` puede heredar directamente de `Exception` para errores específicos del proyecto — todos hacen `subclass` de `CMCourierError`.
- **REQ-028** — DEBE existir `ConfigurationError(CMCourierError)` para configuración inválida descubierta al `startup` (levantada por `config/` en 005).
- **REQ-029** — DEBE existir `TriggerError(CMCourierError)` para fallas del `stage` S0 (`source` inalcanzable, entrada malformada).
- **REQ-030** — DEBE existir `IndexingError(CMCourierError)` para fallas del `stage` S1, con tres subclases: `RVABREPNotFoundError`, `RVABREPDeletedError`, `RVABREPDuplicateError`.
- **REQ-031** — DEBE existir `MappingError(CMCourierError)` para fallas del `stage` S2, con la subclase `IDRViNotMappedError(MappingError)` (el caso más común: `id_rvi` no en `Modelo Documental`).
- **REQ-032** — DEBE existir `MetadataError(CMCourierError)` para fallas del `stage` S3, con subclases `SourceFailedError(MetadataError)` y `DefaultValidationFailedError(MetadataError)`.
- **REQ-033** — DEBE existir `AssemblyError(CMCourierError)` para fallas del `stage` S4, con subclases `SourceFileMissingError(AssemblyError)` y `PDFAssemblyFailedError(AssemblyError)`.
- **REQ-034** — DEBE existir `UploadError(CMCourierError)` para fallas del `stage` S5, con subclases `CMISClientError(UploadError)` (HTTP 4xx, `fail-fast`), `CMISServerError(UploadError)` (HTTP 5xx, reintentar), y `RetriesExhaustedError(UploadError)`.
- **REQ-035** — DEBE existir `TrackingError(CMCourierError)` para fallas del `tracking store` (S6). **Nunca** se levanta de una forma que bloquee el `pipeline` — se loguea y se trackea por separado, según la descripción del `stage` S6 en el `spec`.

Cada clase de excepción DEBE aceptar un contexto estructurado opcional (por ejemplo, `txn_num`, `batch_id`, `id_rvi`) como argumentos `keyword` y almacenarlos en la instancia para `logging` aguas abajo. El `CMCourierError.__init__` base formatea el contexto en el mensaje; las subclases heredan este comportamiento.

### 3.4 Tests (REQ-036 a REQ-041)

- **REQ-036** — Cada modelo en §3.1 DEBE tener `unit tests` en `tests/unit/domain/test_models.py` cubriendo: construcción con entradas válidas, rechazo de validación de entradas inválidas, `frozen-ness` (la mutación levanta `FrozenInstanceError`), cada propiedad computada, cada función helper (`parse_cymmdd` con `happy path` + casos `edge` del formato CYYMMDD, `compute_cm_folder`, `compute_cm_object_type`).
- **REQ-037** — Cada `port` en §3.2 DEBE tener un `unit test` en `tests/unit/domain/test_ports.py` confirmando que es una clase abstracta (chequeo de instancia `abc.ABC`) y que sus métodos abstractos no pueden instanciarse sin implementación.
- **REQ-038** — La jerarquía de excepciones en §3.3 DEBE tener `unit tests` en `tests/unit/domain/test_exceptions.py` cubriendo: `isinstance(MappingError(), CMCourierError)`, cada relación de subclase, y que los kwargs de contexto estructurado (por ejemplo, `txn_num`, `id_rvi`) están almacenados en la instancia y reflejados en `str(exc)`.
- **REQ-039** — Todos los tests DEBEN pasar bajo `pytest -m unit` y completarse en menos de 5 segundos en total.
- **REQ-040** — Todos los tests DEBEN pasar bajo `mypy --strict` (el override `domain/` aplica también a `tests/unit/domain/` vía herencia del config de mypy del proyecto; los tests son `type-checked`).
- **REQ-041** — `Strict TDD` aplica: cada clase de modelo / `port` / excepción aterriza como un test `Red` PRIMERO, después la implementación. Las tareas en `tasks.md` aplican este ordenamiento.

---

## 4. Escenarios de Aceptación

### 4.1 La capa de dominio es pura

- **Given** el cambio se mergeó
- **When** un contribuyente corre `python -c "import cmcourier.domain; import cmcourier.domain.models; import cmcourier.domain.ports; import cmcourier.domain.exceptions"`
- **Then** todos los imports tienen éxito sin disparar ningún import `third-party`
- **And** correr `grep -E '^(import|from)' src/cmcourier/domain/*.py | grep -vE '(stdlib_only_pattern|cmcourier\.)'` no retorna nombres de módulos `third-party`

### 4.2 Round-trip de CYYMMDD

- **Given** el ejemplo de CYYMMDD del `spec` (`"1251117"`)
- **When** el contribuyente llama a `parse_cymmdd("1251117")`
- **Then** el resultado es `datetime(2025, 11, 17)`

### 4.3 CM folder y object type

- **Given** un `clase_id` de `"01.02.04.01.01"` (el ejemplo del `spec`)
- **When** se construye un `CMMapping(clase_id="01.02.04.01.01", ...)`
- **Then** su `cm_folder` es `"/$type/BAC_01_02_04_01_01"`
- **And** su `cm_object_type` es `"$t!-2_BAC_01_02_04_01_01v-1"`

### 4.4 Los dataclasses frozen rechazan mutación

- **Given** un `TriggerRecord(shortname="JUANPEREZ01", cif=None, system_id="1")` construido
- **When** el contribuyente intenta `record.cif = "123456"`
- **Then** se levanta `dataclasses.FrozenInstanceError`

### 4.5 Los ports son abstractos

- **Given** el cambio mergeado
- **When** el contribuyente intenta `IDataSource()` (sin subclase concreta)
- **Then** Python levanta `TypeError: Can't instantiate abstract class IDataSource with abstract methods …`

### 4.6 La jerarquía de excepciones funciona para filtrado con `except`

- **Given** el cambio mergeado
- **When** el código levanta `IDRViNotMappedError(id_rvi="ZZ99")` y un `handler` hace `except MappingError as e:`
- **Then** el `handler` la captura
- **And** `str(e)` contiene el contexto `id_rvi="ZZ99"`

### 4.7 Los tests pasan limpios

- **Given** el cambio mergeado
- **When** el contribuyente corre `pytest -m unit -v`
- **Then** la suite `unit` se completa en menos de 5 segundos con todos los tests pasando
- **And** `mypy src/cmcourier/domain/ tests/unit/domain/` no reporta errores
- **And** `ruff check src/cmcourier/domain/ tests/unit/domain/` no reporta errores

### 4.8 Sin PII

- **Given** el cambio mergeado
- **When** el contribuyente busca con `grep` patrones de PII conocidos bajo `src/cmcourier/domain/` y `tests/unit/domain/`
- **Then** no se encuentran coincidencias más allá de identificadores claramente sintéticos (`JUANPEREZ01`, `123456` en tests pero solamente en testeo de forma de identificadores, nunca pareados con nombres reales)

### 4.9 Coverage razonable

- **Given** el cambio mergeado
- **When** el contribuyente corre `pytest -m unit --cov=src/cmcourier/domain --cov-report=term-missing`
- **Then** el `branch coverage` de `src/cmcourier/domain/` es **de al menos 95%** (esta capa es lo suficientemente chica como para que un coverage alto sea factible sin contorsiones)

---

## 5. Fuera de Alcance

- Implementaciones concretas de adaptadores (CSV, AS400, SQLite, CMIS, ensamblado de PDF). Cada uno aterriza en su propio cambio (003+).
- Código de la capa de servicios (`services/`). Aterriza en 004+.
- Schema de configuración (`config/schema.py` con Pydantic). Aterriza en 005.
- Los comandos de la CLI Click más allá del `placeholder` de `app.py`. Aterriza por cambio de `pipeline`.
- `docker compose` para Alfresco. Aterriza cuando se construya el adaptador CMIS.
- Un documento de `docs/explanation/` sobre el dominio — la `domain spec` existente del proyecto lo cubre. Podemos agregar un `docs/explanation/stage-architecture.md` enfocado más adelante.
- Una entrada real de CHANGELOG con versión tipo `0.4.0` hasta que este cambio realmente se mergee. Hasta entonces, la entrada queda bajo `[Unreleased]`.

---

## 6. Restricciones de la Constitución

- **Principio I**: `domain` tiene cero deps externas. REQ-017 lo aplica para `models.py`; REQ-025 para `ports.py`. `exceptions.py` está ligado por la misma regla (solamente `stdlib`).
- **Principio III**: SRP. Tres archivos, tres responsabilidades (modelos / `ports` / excepciones). El límite de 50 líneas por función liga — la función más larga es probablemente `parse_cymmdd` y queda bien por debajo de las 20 líneas. Los helpers para `CM folder/type` son `one-liners`.
- **Principio V**: sin lectura de env. Ninguno de estos archivos lee variables de entorno.
- **Principio VI**: pirámide de tests real. Todos los tests en este cambio son `unit tests` sin I/O. Los `integration tests` para adaptadores (que usan estos `ports`) vienen en 003+.
- **Principio VII**: `spec-before-code`. Este archivo (y `plan.md`, `tasks.md`) se commitean antes que cualquier implementación.
- **Principio VIII**: sin PII. Los `fixtures` de test usan identificadores sintéticos explícitamente.
- **Principio IX**: cada modelo tiene un propósito de una oración escrito antes de que se escriban sus tests. El `plan` documenta explícitamente el *porqué* por tipo.

---

## 7. Riesgos y Preguntas Abiertas

### 7.1 Riesgos conocidos

- **Los `dataclasses` `frozen` con `slots=True`** requieren Python 3.10+ para la feature de `slots`. Estamos en 3.11+ según la Constitución, así que es seguro.
- **`Mapping[str, str]` vs `dict[str, str]` para `ResolvedMetadata.properties`**: un `dict` sería mutable; usamos `MappingProxyType` para garantizar `read-only` en `runtime` mientras mantenemos el `type hint` como `Mapping[str, str]`. Documentado en `plan` §X.
- **Casos `edge` de CYYMMDD**: `"0000000"` (la fecha es "year 1900-00-00") es técnicamente inválido. El `spec` requiere que `parse_cymmdd` levante `ValueError` para cualquier entrada no parseable. Los tests lo cubren.
- **Almacenar `datetime` en un `dataclass` `frozen` a escala (200.000 registros)**: cada `datetime` es aproximadamente 50 bytes; 200k registros son 10 MB. Aceptable. Si surge presión de memoria post-MVP, lo revisamos.
- **Enum `StageStatus` vs string**: almacenar como string en SQLite intercambia seguridad de tipos por portabilidad entre `backends`. Usamos `StageStatus.value` (un string) para persistencia — ver `plan` §X.

### 7.2 Preguntas abiertas (resolver en plan.md)

- ¿Debería `MigrationRecord` usar `dataclasses.field(default_factory=…)` para el `default` de `created_at`, o pasarlo explícitamente? El `plan` decide (recomendación: constructor explícito; sin `field(default_factory=datetime.now)` porque eso re-evalúa en cada `default-build` y enmaraña la testeabilidad).
- ¿Debería `ResolvedMetadata` también exponer los métodos `keys()` y `values()` explícitamente, o confiar en el comportamiento implícito del ABC `Mapping`? El `plan` decide.
- ¿Debería el contexto estructurado de las clases de excepciones usar `**kwargs` (laxo) o parámetros nombrados explícitos por subclase (estricto)? El `plan` decide — la recomendación es explícito por subclase para que aparezca al momento de `type-check`.
- Firma de `S0Strategy.acquire`: `source_descriptor: str` u objeto estructurado? El `plan` decide — la recomendación es `str` por ahora (parseado por la estrategia misma), revisitar si se vuelve frágil.

---

## 8. Estrategia de Verificación

| Bloque REQ | Verificación |
|------------|--------------|
| REQ-001..018 (modelos) | `unit tests` en `tests/unit/domain/test_models.py`; `mypy --strict`; `ruff` |
| REQ-019..026 (ports) | `unit tests` en `tests/unit/domain/test_ports.py` (chequeos de `abc.ABC`); `mypy --strict` |
| REQ-027..035 (excepciones) | `unit tests` en `tests/unit/domain/test_exceptions.py`; `mypy --strict` |
| REQ-036..041 (tests) | el simple hecho de que los tests pasen bajo `pytest -m unit` + coverage ≥95% en `domain/` + 0 errores de mypy |
| Escenarios 4.1..4.9 | cada uno mapea a uno o más tests nombrados + los comandos de verificación listados |

---

## 9. Referencias Cruzadas

- Convenciones de Spec Kit: `.specify/memory/constitution.md`, `CONTRIBUTING.md`
- Fuente de verdad del dominio: la `domain spec` del proyecto (especialmente §3 RVABREP, §4 Modelo Documental, §6 Metadata Resolution, §9 Tracking, §10 Stages, §14.3 Port Definitions)
- Los Principios I, III, VI, VII, VIII, IX de la Constitución ligan este cambio
- Plan: `specs/002-domain-models-and-ports/plan.md`
- Tasks: `specs/002-domain-models-and-ports/tasks.md`
- Cambio predecesor: `specs/001-bootstrap-python-skeleton/`

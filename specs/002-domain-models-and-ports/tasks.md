# Tasks — 002-domain-models-and-ports

**Status**: Borrador (en revisión)
**Creado**: 2026-05-09
**Referencia al spec**: `specs/002-domain-models-and-ports/spec.md`
**Referencia al plan**: `specs/002-domain-models-and-ports/plan.md`

> Checklist atómico de implementación. `Strict TDD`: cada modelo, `port` y excepción aterriza como un test `Red` PRIMERO, después la implementación mínima, después refactor mientras está en verde.

---

## Cómo leer este archivo

- Las tareas están numeradas jerárquicamente: `<fase>.<tarea>`.
- Cada fase termina en un estado intermedio significativo (una corrida verde de `pytest`, `ruff`/`mypy` limpios).
- Prefijo de `Strict TDD` por tarea de código:
  - **`(R)`** — escribir el test que falla
  - **`(G)`** — escribir el mínimo código para hacerlo pasar
  - **`(Rf)`** — refactor mientras está en verde
- Las tareas sin prefijo no son de código (configs, docs).

El grafo de dependencias entre fases:

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

## Fase 1 — Jerarquía de excepciones

Hojas primero. Nada más depende de excepciones, pero todo lo demás puede levantarlas.

- [ ] **1.1 (R)** Crear `tests/unit/domain/test_exceptions.py` con la clase de test `TestHierarchy` y un test parametrizado afirmando cada relación de subclase según `plan.md §5.1`. Correr `pytest -m unit tests/unit/domain/test_exceptions.py` y confirmar que falla con `ImportError` (las clases objetivo todavía no existen).
- [ ] **1.2 (G)** Crear `src/cmcourier/domain/exceptions.py`. Definir `CMCourierError` según `plan.md §5.2`. Definir cada subclase según `plan.md §5.1`. Para subclases con contexto estructurado (por ejemplo, `IDRViNotMappedError`, `RetriesExhaustedError`), definir parámetros nombrados explícitos según `plan.md §5.3`.
- [ ] **1.3 (R)** Agregar la clase de test `TestStructuredContext` a `test_exceptions.py` cubriendo: `IDRViNotMappedError(id_rvi="ZZ99").id_rvi == "ZZ99"`, `"ZZ99" in str(exc)`, `RetriesExhaustedError(txn_num="123", attempts=3)` expone ambos atributos. Correr `pytest`, confirmar que falla (o pasa parcialmente).
- [ ] **1.4 (G)** Implementar el contexto estructurado según `plan.md §5.2` para que los tests pasen.
- [ ] **1.5 (Rf)** Correr `ruff check src/cmcourier/domain/exceptions.py tests/unit/domain/test_exceptions.py` y `mypy src/cmcourier/domain/exceptions.py`. Arreglar cualquier issue. Volver a correr `pytest`.

**Fase 1 lista cuando**: `pytest -m unit tests/unit/domain/test_exceptions.py` está verde y `ruff`/`mypy` pasan sobre esos archivos.

---

## Fase 2 — Enum `StageStatus`

Dependencia de `MigrationRecord` (Fase 4) e `ITrackingStore` (Fase 5). Vale la pena aterrizarlo en aislamiento.

- [ ] **2.1 (R)** Crear `tests/unit/domain/test_models.py` (lo vamos a poblar a lo largo de las fases 2-4). Agregar la clase `TestStageStatus` con tests para `value_equals_name`, `terminal_for_stage(1)` retorna `(S1_DONE, S1_FAILED)`, y `terminal_for_stage(7)` levanta `ValueError`. Correr `pytest`, confirmar que falla (`StageStatus` no existe).
- [ ] **2.2 (G)** Crear `src/cmcourier/domain/models.py` con el `docstring` de módulo y los imports listados en `plan.md §3.1`. Implementar `StageStatus` según `plan.md §3.5`. Correr `pytest`, confirmar verde.
- [ ] **2.3 (Rf)** Confirmar que `ruff` y `mypy` están limpios.

**Fase 2 lista cuando**: `pytest -m unit tests/unit/domain/test_models.py::TestStageStatus` está verde.

---

## Fase 3 — Helpers + modelos simples

Helpers (`parse_cymmdd`, `is_pdf_filename`, `compute_cm_folder`, `compute_cm_object_type`) y los `dataclasses` más simples (`TriggerRecord`, `StagedFile`, `ResolvedMetadata`).

- [ ] **3.1 (R)** Agregar `TestParseCymmdd` a `test_models.py` cubriendo ejemplo canónico, demasiado corto, no-dígito, mes inválido (`"1251301"`), día inválido (`"1252231"`). Confirmar que falla.
- [ ] **3.2 (G)** Implementar `parse_cymmdd` según `plan.md §3.2`. Confirmar verde.
- [ ] **3.3 (R)** Agregar `TestIsPdfFilename` cubriendo `"0AAAUI0K.PDF"` (true), `"DAAAH9X4.001"` (false), `case insensitivity`. Confirmar que falla.
- [ ] **3.4 (G)** Implementar `is_pdf_filename`. Confirmar verde.
- [ ] **3.5 (R)** Agregar `TestComputeCmFolder` y `TestComputeCmObjectType` cubriendo el ejemplo del `spec` (`"01.02.04.01.01"` → `"/$type/BAC_01_02_04_01_01"` y `"$t!-2_BAC_01_02_04_01_01v-1"`). Confirmar que falla.
- [ ] **3.6 (G)** Implementar `compute_cm_folder` y `compute_cm_object_type`. Confirmar verde.
- [ ] **3.7 (R)** Agregar `TestTriggerRecord` cubriendo: construcción con entradas válidas, `shortname` vacío levanta `ValueError`, `system_id` vacío levanta `ValueError`, `cif=None` permitido, `frozen-ness` (la asignación levanta `FrozenInstanceError`).
- [ ] **3.8 (G)** Implementar `TriggerRecord` según `plan.md §3.1` con un `__post_init__` que valida `shortname` y `system_id` no vacíos. Confirmar verde.
- [ ] **3.9 (R)** Agregar `TestStagedFile` cubriendo construcción, `size_bytes` negativo levanta, `page_count` negativo levanta, `frozen-ness`.
- [ ] **3.10 (G)** Implementar `StagedFile` con validación en `__post_init__`. Confirmar verde.
- [ ] **3.11 (R)** Agregar `TestResolvedMetadata` cubriendo: `from_dict({"BAC_CIF": "123"})` construye, `__getitem__`, `__contains__`, `__iter__`, `__len__`, mutar el `dict` `source` subyacente NO muta la vista del `ResolvedMetadata` (prueba inmutabilidad vía copia).
- [ ] **3.12 (G)** Implementar `ResolvedMetadata` según `plan.md §3.4`. Confirmar verde.
- [ ] **3.13 (Rf)** Correr `ruff` + `mypy` sobre `src/cmcourier/domain/models.py` y `tests/unit/domain/test_models.py`. Arreglar issues.

**Fase 3 lista cuando**: todos los tests agregados en la fase 3 pasan y el `tooling` está verde.

---

## Fase 4 — Modelos complejos

Modelos con propiedades computadas o que dependen de otros tipos de dominio.

- [ ] **4.1 (R)** Agregar `TestRVABREPDocument` cubriendo: construcción completa con los 16 campos, `is_pdf` true para `"FOO.PDF"`, `is_pdf` true para `"foo.pdf"` (case insensitive), `is_pdf` false para `"FOO.001"`, `is_deleted` true para `delete_code="D"`, `is_deleted` false para `delete_code=""`, `frozen-ness`, `creation_date` es un `datetime` (no `str`).
- [ ] **4.2 (G)** Implementar `RVABREPDocument` según `plan.md §3.1` con `is_pdf` e `is_deleted` como `accessors` `@property`. Confirmar verde.
- [ ] **4.3 (R)** Agregar `TestCMMapping` cubriendo: construcción con `clase_id`, `id_rvi`, `id_corto`, `clase_name`, `required_metadata_fields=()`, `cm_folder` computado correctamente, `cm_object_type` computado correctamente, `frozen-ness`.
- [ ] **4.4 (G)** Implementar `CMMapping` según `plan.md §3.1` con `accessors` `@property` computados `cm_folder` y `cm_object_type`. Confirmar verde.
- [ ] **4.5 (R)** Agregar `TestMigrationRecord` cubriendo: construcción solo con campos requeridos (los `defaults` aplican a los campos opcionales), `cm_object_id=None` válido, `status` acepta un `StageStatus`, `frozen-ness`.
- [ ] **4.6 (G)** Implementar `MigrationRecord` según `plan.md §3.6`. Confirmar verde.
- [ ] **4.7 (Rf)** `Ruff` + `mypy` limpios sobre los archivos tocados.

**Fase 4 lista cuando**: cada modelo existe, cada test verde.

---

## Fase 5 — Ports

Interfaces abstractas. Dependen de cada modelo de las fases 2–4.

- [ ] **5.1 (R)** Crear `tests/unit/domain/test_ports.py` con el `test_port_is_abstract` parametrizado según `plan.md §6.3` listando los cinco `ports`. Confirmar que falla (`ImportError`, los `ports` no existen).
- [ ] **5.2 (G)** Crear `src/cmcourier/domain/ports.py` según `plan.md §4.1`. Implementar cada `port` como `abc.ABC` con métodos decorados con `@abstractmethod`. Sin cuerpos de métodos — solamente `...`. Confirmar verde.
- [ ] **5.3 (R)** Agregar un test por `port` que liste los nombres de los métodos abstractos esperados contra `port.__abstractmethods__` para capturar `drift` accidental si alguien se olvida de `@abstractmethod`. Ejemplo: `assert IDataSource.__abstractmethods__ == frozenset({"query", "query_stream", "get_by_fields", "get_by_fields_in", "get_all", "count", "close"})`.
- [ ] **5.4 (G)** Confirmar test verde (ya que 5.2 implementó todos los métodos).
- [ ] **5.5 (Rf)** `Ruff` + `mypy` sobre los archivos nuevos. Particular atención a `mypy --strict` ya que `cmcourier.domain.*` es un `override` de modo `strict`.

**Fase 5 lista cuando**: los `ports` existen como clases abstractas, los tests están verdes.

---

## Fase 6 — Re-exports en `domain/__init__.py`

Reemplazar el `domain/__init__.py` actual de solo `docstring` con la re-exportación completa según `plan.md §3.8`.

- [ ] **6.1 (R)** Agregar `tests/unit/domain/test_imports.py` con un único test que afirma `from cmcourier.domain import TriggerRecord, RVABREPDocument, CMMapping, ResolvedMetadata, StagedFile, StageStatus, MigrationRecord, parse_cymmdd, compute_cm_folder, compute_cm_object_type, is_pdf_filename, IDataSource, ITrackingStore, IAssembler, IUploader, S0Strategy, CMCourierError, MappingError, IDRViNotMappedError, MetadataError, AssemblyError, UploadError, CMISClientError, CMISServerError, RetriesExhaustedError, TrackingError, IndexingError, RVABREPNotFoundError, RVABREPDeletedError, RVABREPDuplicateError, ConfigurationError, TriggerError, SourceFailedError, DefaultValidationFailedError, SourceFileMissingError, PDFAssemblyFailedError`. Confirmar que falla (la mayoría de los nombres todavía no están re-exportados).
- [ ] **6.2 (G)** Reemplazar `src/cmcourier/domain/__init__.py` con el bloque completo de re-exportación según `plan.md §3.8`. Definir `__all__` listando cada nombre en orden alfabético. Confirmar verde.
- [ ] **6.3 (Rf)** `Ruff`: asegurar que `__all__` coincide con las re-exportaciones y no quedan imports no usados. `Mypy` limpio.

**Fase 6 lista cuando**: cada nombre público es importable directamente desde `cmcourier.domain`.

---

## Fase 7 — Verificación + commit

- [ ] **7.1** Correr la suite `unit` completa para la capa de dominio:
  ```bash
  source .venv/bin/activate
  pytest -m unit -v tests/unit/domain/
  ```
  Confirmar que todos los tests pasan.
- [ ] **7.2** Correr el reporte completo de coverage sobre la capa de dominio:
  ```bash
  pytest -m unit --cov=src/cmcourier/domain --cov-report=term-missing tests/unit/domain/
  ```
  Confirmar coverage ≥ 95% (según el criterio de aceptación REQ del `spec` 4.9).
- [ ] **7.3** Correr el `lint` + `type-check` completo del proyecto:
  ```bash
  ruff check src/ tests/
  ruff format --check src/ tests/
  mypy src/cmcourier/
  ```
  Todo verde.
- [ ] **7.4** Correr `pre-commit` sobre todos los archivos:
  ```bash
  pre-commit run --all-files
  ```
  Todo verde.
- [ ] **7.5** `Grep` de PII:
  ```bash
  grep -rEn '\b\d{6}\b' src/cmcourier/domain/ tests/unit/domain/
  grep -rEni '(juan|maria|carlos|jose|laura|martin)\s?(perez|gomez|rodriguez|gonzalez|sanchez|martinez)' src/cmcourier/domain/ tests/unit/domain/
  ```
  Solamente identificadores sintéticos son aceptables (`JUANPEREZ01`, `123456`); los pares con aspecto real de nombre+CIF no.
- [ ] **7.6** Actualizar `CHANGELOG.md`: agregar un bloque `[0.4.0]` según `plan.md §7`, ajustar `[Unreleased]` "Planned for next release" para apuntar a 003 (siguiente cambio de adaptador).
- [ ] **7.7** Actualizar el checklist de Status de `README.md`: tildar `Second change: domain models, ports, exceptions` si no lo está ya.
- [ ] **7.8** Hacer `stage` de todos los archivos, confirmar que `git status` coincide con la lista esperada:
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
- [ ] **7.9** Crear el `commit` de implementación en el branch de feature:
  ```
  feat(domain): add models, ports, and exception hierarchy

  Populate the empty domain layer left by 001 with frozen dataclasses,
  abstract interfaces, and the typed exception tree. Every public type
  arrived via Strict TDD (red test → green code → refactor). Coverage
  on src/cmcourier/domain/ is XX% (target ≥95%).

  Models (the spec): TriggerRecord, RVABREPDocument
  (with is_pdf / is_deleted properties), CMMapping (with computed
  cm_folder + cm_object_type), ResolvedMetadata (read-only mapping
  via MappingProxyType), StagedFile, MigrationRecord, plus the
  StageStatus enum encoding the per-stage state machine from §10.3.
  Helpers parse_cymmdd, is_pdf_filename, compute_cm_folder,
  compute_cm_object_type live alongside the models so services and
  pre-flight validation share one source of truth.

  Ports (the spec + §10): IDataSource, ITrackingStore (with the
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

## Mapeo de verificación (spec REQ → tasks)

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
| REQ-016 | cada subtest de "frozen-ness" en las fases 3-4 |
| REQ-017 | aplicado por la disciplina de imports de las Fases 1-6; verificado por `mypy` + `ruff` en la Fase 7 |
| REQ-018 | 6.1, 6.2 |
| REQ-019 | 5.2 (bloque IDataSource) |
| REQ-020 | 5.2 (bloque ITrackingStore) |
| REQ-021 | 5.2 (bloque IAssembler) |
| REQ-022 | 5.2 (bloque IUploader) |
| REQ-023 | 5.2 (bloque S0Strategy) |
| REQ-024 | 5.3 (chequeos de `__abstractmethods__`) |
| REQ-025..026 | 6.1, 6.2 |
| REQ-027..035 | 1.1..1.5 |
| REQ-036 | cada tarea (R) y (G) en las fases 2-4 |
| REQ-037 | 5.1, 5.3 |
| REQ-038 | 1.1, 1.3 |
| REQ-039 | 7.1 (afirmación de tiempo en el descubrimiento de tests) |
| REQ-040 | 7.3 (paso de `mypy`) |
| REQ-041 | el ordenamiento (R) → (G) → (Rf) en cada tarea de código |

| Escenario de aceptación | Tasks |
|-------------------------|-------|
| 4.1 (dominio puro) | 7.3 (`mypy` + la disciplina de imports de las fases 1-6) |
| 4.2 (round-trip CYYMMDD) | 3.1, 3.2 |
| 4.3 (CM folder/object type) | 3.5, 3.6 |
| 4.4 (rechazo frozen) | 3.7-3.8 + similar en cada modelo |
| 4.5 (ports abstract) | 5.1, 5.2 |
| 4.6 (filtrado de jerarquía de excepciones) | 1.1, 1.3 |
| 4.7 (tests pasan limpios) | 7.1, 7.3 |
| 4.8 (sin PII) | 7.5 |
| 4.9 (coverage ≥95%) | 7.2 |

---

## Esfuerzo estimado

- Fase 1 (excepciones): 30 min
- Fase 2 (StageStatus): 10 min
- Fase 3 (helpers + modelos simples): 60 min
- Fase 4 (modelos complejos): 45 min
- Fase 5 (ports): 30 min
- Fase 6 (re-exports): 10 min
- Fase 7 (verificación + commit): 20 min
- **Total**: ~3 horas y 25 minutos de trabajo enfocado para un contribuyente haciendo `pair-programming` con un agente.

El `overhead` de `strict-TDD` es real pero rinde de inmediato — cada test que se pone verde es comportamiento documentado, y el objetivo de coverage cae naturalmente.

---

## Notas para quien implementa

- El Principio I de la Constitución es vinculante: SIN imports `third-party` dentro de `src/cmcourier/domain/`. Si un archivo de test bajo `tests/unit/domain/` accidentalmente importa `pydantic` o similar, es un `code smell` — el test pertenece a otro lugar.
- El límite de 50 líneas por función se sostiene. La función más larga en este cambio es `parse_cymmdd` con ~10 líneas. Los helpers y los validadores `__post_init__` se mantienen bajo las 15 líneas cada uno.
- `__all__` en `domain/__init__.py` es la fuente de verdad de lo que es "público". Cualquier cosa que no esté en `__all__` debería considerarse privada al módulo.
- Si durante la implementación un modelo gana un método que requiere lógica más allá de un `one-liner`, parar y reconsiderar — la mayoría del comportamiento debería vivir en servicios, no en modelos. Los modelos son datos + derivaciones diminutas.
- `Strict TDD` no significa "escribir 100 tests por adelantado". Significa "por cada comportamiento público, escribir el test que falla antes que el código que lo satisface". Los archivos de test en este cambio terminan en aproximadamente 300-400 líneas combinadas; nada extremo.

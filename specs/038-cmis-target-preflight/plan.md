# 038 — Plan

Cinco fases, ~10-12h en total. RED→GREEN por fase, commit por fase,
FF en el último commit.

Las fases se ordenan para que cada una sea fusionable de forma
independiente: la fase 1 deja esquema + plomería de servicio sin
cambio de comportamiento, la fase 2 deja el refactor del puerto
aislado, la fase 3 deja los dos checks del doctor sobre las fases
1+2, la fase 4 deja la observabilidad, la fase 5 docs + bump.

## Fase 1 — Columnas `CMISFolder` + `CMISPropertyId` a lo largo del stack (~2.5h)

### Archivos

- `src/cmcourier/config/schema.py`
  - `MappingConfig.rvi_cm_cmis_folder_column: str = "CMISFolder"`.
  - `MappingConfig.metadatos_cmis_property_id_column: str = "CMISPropertyId"`.
  - Frozen, sin override por env — son decisiones de forma del
    archivo.
- `src/cmcourier/domain/models.py`
  - `CMMapping.cmis_folder: str | None = None`.
- `src/cmcourier/services/mapping.py`
  - Cuando el CSV tiene la columna `CMISFolder` configurada,
    poblar `cmis_folder` (`None` para celdas vacías). De lo
    contrario, dejar `None`.
  - Compat hacia atrás: columna ausente es un no-op.
- `src/cmcourier/services/metadata.py`
  - `MetadataService` lee `metadatos_cmis_property_id_column`
    desde las filas unidas de `MetadatosCM`. Cuando está presente
    y no vacía, `resolve_properties` clavea el dict de salida por
    el ID de propiedad CMIS; de lo contrario, por el nombre
    amigable (comportamiento existente).
- `src/cmcourier/orchestrators/staged.py`
  - El constructor de URL de S5 consume `mapping.cmis_folder`:
    `f"{base}/{repo}/root/{cmis_folder}"` cuando está definido,
    `f"{base}/{repo}/root"` cuando es `None`. **Ninguna llamada a
    `ensure_folder` se agrega o modifica en esta fase** (eso es
    fase 2).

### Tests

- `tests/unit/config/test_schema.py`
  - Valores por defecto: ambos nombres de columna toman los
    valores de la spec.
- `tests/unit/services/test_mapping.py`
  - CSV con `CMISFolder` poblado → `cmis_folder` se propaga.
  - CSV con celda `CMISFolder` vacía → `cmis_folder is None`.
  - CSV sin la columna `CMISFolder` → `cmis_folder is None` para
    cada fila (sin excepción).
- `tests/unit/services/test_metadata.py`
  - Con `CMISPropertyId` poblado → las claves del dict de
    propiedades resueltas son IDs CMIS.
  - Con `CMISPropertyId` vacío → cae a los nombres amigables.
  - Columna faltante → cae globalmente.
- `tests/integration/orchestrators/test_staged_pipeline.py`
  - Los tests existentes pasan sin cambios.
  - Test nuevo: una fila de mapeo con `cmis_folder="$type/X"`
    produce una URL de subida que contiene `/$type/X`.

### Commit

```
feat(config,mapping,metadata,pipeline): CMISFolder + CMISPropertyId columns (038 Phase 1)
```

## Fase 2 — `IUploader.verify_folder_exists` + remover superficie de creación (~2h)

### Archivos

- `src/cmcourier/domain/ports.py`
  - Renombrar `ensure_folder` → `verify_folder_exists`.
  - Devolver `bool`. Docstring: devuelve `True` si y solo si la
    carpeta existe Y tiene `cmis:baseTypeId == cmis:folder`.
- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - Reemplazar el cuerpo de `ensure_folder` por una implementación
    de solo-verificación que haga
    `GET ?cmisselector=object&objectId=<path>`.
  - Mapeo de respuesta:
    - 200 + `baseTypeId` folder → `True`
    - 200 + `baseTypeId` no-folder → `False`
    - 404 → `False`
    - otra → lanzar excepción de conectividad / `auth` (clases
      existentes)
  - Eliminar el método privado `_create_folder_segment`.
- `src/cmcourier/orchestrators/staged.py`
  - Remover la llamada existente `uploader.ensure_folder(...)` de
    S5 (la que está dentro de la subida por documento). El nuevo
    comportamiento es: S5 confía en que el operador corrió
    `doctor --check cm-targets`.

### Tests

- `tests/integration/adapters/test_cmis_uploader.py`
  - Reemplazar `ensure_folder_creates_when_missing` y similares
    por `verify_folder_exists_returns_true_for_existing`,
    `verify_folder_exists_returns_false_on_404`,
    `verify_folder_exists_returns_false_when_not_folder`.
  - Eliminar cualquier test que dependiera de
    `_create_folder_segment`.
- `tests/integration/orchestrators/test_staged_pipeline.py`
  - Agregar aserción: una corrida del `pipeline` de 10 documentos
    contra un `stub` uploader registra **cero** llamadas a
    `verify_folder_exists` en el camino feliz (S5 ya no toca la
    verificación de carpeta — eso es trabajo del `doctor`).

### Commit

```
refactor(uploader,pipeline): verify_folder_exists (read-only) + remove S5 folder-creation surface (038 Phase 2)
```

## Fase 3 — Checks del doctor `cmis_folders_exist` + `cmis_properties_alignment` (~2.5h)

### Archivos

- `src/cmcourier/cli/doctor.py`
  - `_check_cmis_folders_exist(config, secrets) -> CheckResult`:
    - Construir `mapping service`, recolectar `cmis_folder`
      únicos no vacíos.
    - Construir el uploader una vez (helper existente
      `_build_uploader`).
    - Por cada carpeta, llamar a `verify_folder_exists`;
      recolectar faltantes.
    - SKIP si no hay `cmis_folder` poblado en ningún lado.
    - FAIL con detalle `missing_folders`; instrucción en el
      mensaje.
  - `_check_cmis_properties_alignment(config, secrets) -> CheckResult`:
    - Construir `mapping` + `metadata` services.
    - Por cada par único `(cm_object_type, cmis_property_id)`
      (salteando filas donde alguno sea `None`), llamar a
      `get_type_definition(cm_object_type)` (memoizado por tipo).
    - Recolectar pares cuyo `cmis_property_id` no está en
      `propertyDefinitions` del tipo.
    - SKIP si no hay `cmis_property_id` poblado en ningún lado.
    - FAIL agrupando las propiedades faltantes por tipo.
  - `_CHECK_GROUPS["cm-targets"] = frozenset({"cm_type_alignment",
    "cmis_folders_exist", "cmis_properties_alignment"})`.
  - `run_doctor` invoca los checks nuevos cuando el grupo activo
    los incluye.

### Tests

- `tests/unit/cli/test_doctor.py`
  - `cmis_folders_exist`: camino PASS (todas existen), camino FAIL
    (algunas faltantes, listado determinista), camino SKIP
    (columna vacía).
  - `cmis_properties_alignment`: PASS, FAIL agrupado, SKIP.
  - Membresía de `_CHECK_GROUPS["cm-targets"]`.
- `tests/integration/cli/test_doctor_cm_targets.py` (nuevo)
  - Contra un `stub` uploader que devuelve respuestas predecibles
    de `verify_folder_exists` / `get_type_definition`, ejercitar
    `run_doctor(config, secrets, group="cm-targets")` completo y
    verificar que los 3 checks regresen en orden.

### Commit

```
feat(doctor): cmis_folders_exist + cmis_properties_alignment + cm-targets group (038 Phase 3)
```

## Fase 4 — Eventos `s5_upload_attempt` / `s5_upload_failed` + `unmask_pii` (~2h)

### Archivos

- `src/cmcourier/config/schema.py`
  - `ObservabilityConfig.unmask_pii: bool = Field(default=False)`.
- `src/cmcourier/observability/pii.py`
  - Confirmar que `mask_value(field_name, value)` existe y cubre
    los campos que emitimos (CIF, Nombre_Cliente,
    NUM_CUENTA_TARJETA, NUM_CUENTA, NUM_PRESTAMO, NUM_AFILIADO,
    Short_Name).
  - Agregar conveniencia
    `mask_dict(properties: Mapping[str, str], *, unmask: bool)`.
- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - Antes de cada intento de POST, emitir `s5_upload_attempt` vía
    el `logger` estructurado:
    - `url`, `object_type_id`, propiedades enmascaradas, índice de
      intento, `content_bytes`, `mime_type`.
  - En respuesta no-201, emitir `s5_upload_failed` extendiendo el
    evento de intento con `status_code`, `response_body`
    truncado, y un `string` `curl_equivalent`. Construir el curl
    con los valores **enmascarados** a menos que
    `observability.unmask_pii=True`.
- `src/cmcourier/cli/doctor.py`
  - Al arranque, cuando `unmask_pii=True`, agregar una línea
    `WARNING` al resumen del `doctor` (separada de los resultados
    de los checks).

### Tests

- `tests/unit/observability/test_pii.py`
  - `Round-trip`: nombres de campo conocidos enmascarados,
    desconocidos pasan, el flag `unmask` devuelve crudo.
  - Comportamiento de `mask_dict`.
- `tests/integration/adapters/test_cmis_uploader.py`
  - Respuesta 201 mockeada → `s5_upload_attempt` escrito una vez.
  - Respuesta 400 mockeada → `s5_upload_attempt` +
    `s5_upload_failed` escritos; el evento de falla tiene
    `curl_equivalent` con enmascarado aplicado.
  - `unmask_pii=True` → los valores aparecen crudos en los eventos.
- `tests/integration/cli/test_doctor_warnings.py` (nuevo)
  - Con `observability.unmask_pii=True`, la salida del `doctor`
    contiene la línea de warning de `unmask`.

### Commit

```
feat(observability,uploader): s5_upload_attempt + s5_upload_failed events + unmask_pii toggle (038 Phase 4)
```

## Fase 5 — Docs + CHANGELOG 0.41.0 + FF (~1h)

### Archivos

- `docs/how-to/cmis-target-preflight.md` (nuevo) — `runbook` del
  operador:
  - Llenar `CMISFolder` y `CMISPropertyId` en los CSV de muestra.
  - Correr `cmcourier doctor --check cm-targets` y leer la salida.
  - El toggle `unmask-pii` y cuándo usarlo.
- `docs/how-to/validation-checklist.md` — agregar una nueva §X
  "Pre-flight CMIS target" con los 3 checks.
- `scripts/staging/README.md` — agregar la sección
  doctor-luego-correr al quick start.
- `CHANGELOG.md` — entrada `[0.41.0]`. Secciones:
  - Added: columnas `CMISFolder` + `CMISPropertyId`; grupo
    `cm-targets` del doctor + 2 nuevos checks; eventos
    `s5_upload_attempt` + `s5_upload_failed`; toggle `unmask_pii`.
  - Changed: `IUploader.ensure_folder` → `verify_folder_exists`
    (BREAKING para implementadores del adaptador).
  - Removed: `CmisUploader._create_folder_segment`;
    auto-creación de carpetas en S5.
- `README.md` — tildar la fila de feature correspondiente.
- `pyproject.toml` — bump `version = "0.41.0"`.

### Tests

- Suite completa en verde.
- `mypy --strict src/cmcourier/{domain,services,orchestrators}`
  limpio.
- `ruff check` + `ruff format --check` limpios.
- Smoke contra el Alfresco de staging:
  - `cmcourier doctor --check cm-targets` PASS tras pre-crear
    `/cmcourier-staging/CN01`.
  - `cmcourier csv-trigger-pipeline run --total 5 --no-tui`
    escribe 5 eventos `s5_upload_attempt`.

### Commit

```
docs(038): cmis-target-preflight how-to + CHANGELOG 0.41.0 + IUploader contract bump (038 Phase 5)
```

### Merge FF + eliminar la rama.

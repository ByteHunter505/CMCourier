# 035 — Plan

## Fase 1 — Esquema, servicio, cableado (~2h)

### Archivos

- `src/cmcourier/config/schema.py`
  - `MappingConfig`: agregar `csv_path: FilePath | None = None`,
    `rvi_cm_csv_path: FilePath | None = None`,
    `metadatos_csv_path: FilePath | None = None`,
    `cmis_type_column: str = "CMISType"`,
    `rvi_cm_id_rvi_column: str = "IDRVI"`,
    `rvi_cm_id_cm_column: str = "IDCM"`,
    `rvi_cm_clase_id_column: str = "IDClaseDocumental"`,
    `rvi_cm_cmis_type_column: str = "CMISType"`,
    `metadatos_id_corto_column: str = "IDCorto"`,
    `metadatos_metadata_column: str = "Metadato"`,
    `metadatos_required_column: str = "Requerido"`,
    `required_marker: str = "Yes"`.
  - `@model_validator(mode="after") _exactly_one_mode`:
    lanza error si están definidos a la vez consolidado + dividido O
    ninguno O solo una de las rutas del par dividido.

- `src/cmcourier/services/mapping.py`
  - `MappingColumnsConfig`: agregar los campos de nombre de columna
    del modo dividido + `col_required_marker`.
  - `MappingService.__init__`: opcional
    `metadata_source: IDataSource | None = None`.
    Cuando es `None` → camino consolidado (comportamiento actual).
    Cuando se define → camino dividido:
    - Leer `metadata_source.get_all()` una vez, construir
      `dict[id_corto, list[str]]` de metadata requerida.
    - Leer `source.get_all()` una vez, construir el caché. Cada fila →
      `CMMapping(clase_id=row[col_rvi_cm_clase_id], id_rvi=row[col_rvi_cm_id_rvi],
       id_corto=row[col_rvi_cm_id_cm], clase_name=clase_id,
       required_metadata_fields=tuple(required_index[id_corto]),
       cmis_type=row[col_rvi_cm_cmis_type] or "")`.
  - `required_columns()`: devuelve la tupla apropiada según el modo.
    (Detectado vía un flag `_split` almacenado en construcción.)

- `src/cmcourier/config/wiring.py`
  - Agregar `build_mapping_service(mapping_config: MappingConfigModel) -> MappingService`.
    Construye `TabularDataSource`(s), `MappingColumnsConfig`,
    despacha a consolidado o dividido.
  - `wire_services_from_config` llama a `build_mapping_service` en
    lugar de construir `MappingService` en línea.

- `src/cmcourier/cli/doctor.py:421,484`
  - Reemplazar `MappingService(source)` / `MappingService(mapping_src)`
    por `build_mapping_service(config.mapping)`.

- `src/cmcourier/cli/commands/inspect.py:118,161`
  - Reemplazar `MappingService(mapping_src, _mapping_columns_from_schema(config.mapping))`
    por `build_mapping_service(config.mapping)`.

### Tests (RED primero, luego GREEN)

- `tests/unit/config/test_schema.py`
  - `test_mapping_config_consolidated_mode_only`: solo `csv_path` →
    válido.
  - `test_mapping_config_split_mode_both_paths`: ambas rutas
    divididas → válido.
  - `test_mapping_config_rejects_both_modes`: `csv_path` + ruta
    `rvi_cm` → `ValidationError`.
  - `test_mapping_config_rejects_neither_mode`: nada →
    `ValidationError`.
  - `test_mapping_config_rejects_partial_split`: solo una del par
    dividido → `ValidationError`.

- `tests/unit/services/test_mapping_split.py` (archivo nuevo)
  - `test_split_mode_joins_two_sources`: alimentar una fuente
    `rvi-cm` falsa y una fuente `metadatos` falsa, verificar que el
    caché de `CMMapping` contiene los `id_rvi → clase_id`, `id_corto`,
    `cmis_type`, `required_metadata_fields` correctos.
  - `test_split_mode_uses_clase_id_as_clase_name`: verificar que
    `mapping.clase_name == mapping.clase_id`.
  - `test_split_mode_filters_non_required_metadata`: una fila con
    `Requerido != "Yes"` se excluye de `required_metadata_fields`.
  - `test_split_mode_handles_case_insensitive_required`: "YES",
    "yes", "Sí", "1", "True" todos cuentan como requeridos.
  - `test_split_mode_missing_id_corto_in_metadata_yields_empty_tuple`:
    un `IDRVI` cuyo `IDCM` no tiene filas en `MetadatosCM` → tupla
    vacía.
  - `test_split_mode_empty_cmis_type_is_empty_string`.
  - `test_split_mode_strips_whitespace_in_metadata_fields` (el CSV
    real tiene " Short_Name" con espacio inicial).

- `tests/integration/config/test_wiring.py`
  - `test_build_mapping_service_consolidated`: TOML con `csv_path` →
    `MappingService` funciona sobre el fixture consolidado.
  - `test_build_mapping_service_split`: TOML con rutas divididas →
    `MappingService` funciona sobre un fixture dividido pequeño.

### Commit

```
feat(mapping,config): two-mode MappingConfig (consolidated|split) + service join (035 Phase 1)
```

## Fase 2 — Muestra + docs + CHANGELOG + FF (~1h)

### Archivos

- `docs/samples/csv/MapeoRVI_CM.csv`: agregar `,CMISType` al
  encabezado, agregar `,` (vacío) a cada fila de datos existente.
- `docs/how-to/as400-sync.md`: eliminar la nota de limitación
  conocida de 035; agregar un breve recuadro "Mapping CSV split
  (035)" bajo configuración.
- `docs/configuration-guide.md` (o `docs/how-to/configuration.md`):
  mostrar ambos modos de `MappingConfig` en los ejemplos TOML.
- `CHANGELOG.md`: nueva sección `[0.36.0]`. Mover la entrada de 035
  fuera de Unreleased.
- `docs/POST-MVP-roadmap.md` (o donde corresponda): marcar 035 como
  SHIPPED.
- `README.md`: tildar el checkbox de 035 si está presente.

### Validación

- `uv run pytest -q` → pasan las 857+ pruebas + las nuevas.
- `uv run mypy src tests` → limpio.
- `uv run ruff check .` → limpio.

### Commit

```
docs(035): sample CSV CMISType + how-to + CHANGELOG 0.36.0 + POST-MVP SHIPPED (035 Phase 2)
```

### Merge FF a main

```
git checkout main
git merge --ff-only feat/035-mapping-csv-split
git branch -d feat/035-mapping-csv-split
```

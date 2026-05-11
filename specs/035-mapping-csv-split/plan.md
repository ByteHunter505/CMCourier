# 035 — Plan

## Phase 1 — Schema, service, wiring (~2h)

### Files

- `src/cmcourier/config/schema.py`
  - `MappingConfig`: add `csv_path: FilePath | None = None`,
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
    raise if both consolidated + split paths set OR neither set OR
    only one of the split pair set.

- `src/cmcourier/services/mapping.py`
  - `MappingColumnsConfig`: add the split-mode column-name fields
    + `col_required_marker`.
  - `MappingService.__init__`: optional `metadata_source: IDataSource | None = None`.
    When `None` → consolidated path (current behavior).
    When set → split path:
    - Read `metadata_source.get_all()` once, build
      `dict[id_corto, list[str]]` of required metadata.
    - Read `source.get_all()` once, build cache. Each row →
      `CMMapping(clase_id=row[col_rvi_cm_clase_id], id_rvi=row[col_rvi_cm_id_rvi],
       id_corto=row[col_rvi_cm_id_cm], clase_name=clase_id,
       required_metadata_fields=tuple(required_index[id_corto]),
       cmis_type=row[col_rvi_cm_cmis_type] or "")`.
  - `required_columns()`: return the appropriate tuple depending on
    mode. (Detect via stored `_split` flag set at construction.)

- `src/cmcourier/config/wiring.py`
  - Add `build_mapping_service(mapping_config: MappingConfigModel) -> MappingService`.
    Builds `TabularDataSource`(s), `MappingColumnsConfig`, dispatches
    to consolidated or split.
  - `wire_services_from_config` calls `build_mapping_service` instead
    of constructing `MappingService` inline.

- `src/cmcourier/cli/doctor.py:421,484`
  - Replace `MappingService(source)` / `MappingService(mapping_src)`
    with `build_mapping_service(config.mapping)`.

- `src/cmcourier/cli/commands/inspect.py:118,161`
  - Replace `MappingService(mapping_src, _mapping_columns_from_schema(config.mapping))`
    with `build_mapping_service(config.mapping)`.

### Tests (RED first, then GREEN)

- `tests/unit/config/test_schema.py`
  - `test_mapping_config_consolidated_mode_only`: only `csv_path` →
    valid.
  - `test_mapping_config_split_mode_both_paths`: both split paths →
    valid.
  - `test_mapping_config_rejects_both_modes`: csv_path + rvi_cm path
    → ValidationError.
  - `test_mapping_config_rejects_neither_mode`: nothing → ValidationError.
  - `test_mapping_config_rejects_partial_split`: only one of the split
    pair → ValidationError.

- `tests/unit/services/test_mapping_split.py` (new file)
  - `test_split_mode_joins_two_sources`: feed a fake rvi-cm source
    and a fake metadatos source, assert CMMapping cache has correct
    id_rvi → clase_id, id_corto, cmis_type, required_metadata_fields.
  - `test_split_mode_uses_clase_id_as_clase_name`: assert
    `mapping.clase_name == mapping.clase_id`.
  - `test_split_mode_filters_non_required_metadata`: a row with
    `Requerido != "Yes"` is excluded from `required_metadata_fields`.
  - `test_split_mode_handles_case_insensitive_required`: "YES",
    "yes", "Sí", "1", "True" all count as required.
  - `test_split_mode_missing_id_corto_in_metadata_yields_empty_tuple`:
    an IDRVI whose IDCM has no rows in MetadatosCM → empty tuple.
  - `test_split_mode_empty_cmis_type_is_empty_string`.
  - `test_split_mode_strips_whitespace_in_metadata_fields` (real CSV
    has " Short_Name" with leading space).

- `tests/integration/config/test_wiring.py`
  - `test_build_mapping_service_consolidated`: TOML with `csv_path` →
    MappingService works on consolidated fixture.
  - `test_build_mapping_service_split`: TOML with split paths →
    MappingService works on a tiny split fixture.

### Commit

```
feat(mapping,config): two-mode MappingConfig (consolidated|split) + service join (035 Phase 1)
```

## Phase 2 — Sample + docs + CHANGELOG + FF (~1h)

### Files

- `docs/samples/csv/MapeoRVI_CM.csv`: append `,CMISType` to header,
  append `,` (empty) to every existing data row.
- `docs/how-to/as400-sync.md`: drop the 035 known-limitation note;
  add a brief "Mapping CSV split (035)" callout under configuration.
- `docs/configuration-guide.md` (or `docs/how-to/configuration.md`):
  show both `MappingConfig` modes in the TOML examples.
- `CHANGELOG.md`: new `[0.36.0]` section. Move 035 entry out of
  Unreleased.
- `docs/POST-MVP-roadmap.md` (or wherever): mark 035 SHIPPED.
- `README.md`: tick the 035 checkbox if present.

### Validation

- `uv run pytest -q` → all 857+ tests + new tests pass.
- `uv run mypy src tests` → clean.
- `uv run ruff check .` → clean.

### Commit

```
docs(035): sample CSV CMISType + how-to + CHANGELOG 0.36.0 + POST-MVP SHIPPED (035 Phase 2)
```

### FF merge to main

```
git checkout main
git merge --ff-only feat/035-mapping-csv-split
git branch -d feat/035-mapping-csv-split
```

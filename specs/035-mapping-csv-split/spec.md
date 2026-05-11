# 035 — Mapping CSV split + CMISType column

## Why

The bank's production mapping is **two separate CSVs**:

- `MapeoRVI_CM.csv` — `IDSistema, IDRVI, IDCM, IDClaseDocumental` (+ new `CMISType` column)
- `MetadatosCM.csv` — `IDCorto, Metadato, Requerido`

CMCourier today reads a single **consolidated** test fixture
`modelo_documental.csv` with all columns inline plus a comma-separated
`METADATOS` cell. That format does not exist in production.

034 introduced `CMMapping.cmis_type` and a default value of `""`. The
AS400 `NIARVILOG.TIPIDN` column is currently written empty until the
production CSV's `CMISType` column lands. **035 unblocks that field.**

## What

1. **`MappingConfig` two-mode support**:
   - Consolidated mode (legacy, test-fixture-friendly): single
     `csv_path` plus the existing column-name fields.
   - Split mode (production): `rvi_cm_csv_path` + `metadatos_csv_path`
     with their own column-name fields.
   - `model_validator` enforces exactly-one-of: either `csv_path` is
     set, or both split paths are set. Never both, never neither.

2. **`MappingService` split-mode loader**:
   - Optional second `IDataSource` constructor arg
     (`metadata_source`). When present, the service joins the two
     sources by `IDCorto ↔ IDCM` and builds the in-memory cache.
   - In split mode, `CMMapping.clase_name` defaults to `clase_id`
     (production CSV has no human-readable name column — confirmed by
     the bank).
   - `MetadatosCM.Requerido` is parsed case-insensitively;
     `Yes` / `Sí` / `True` / `1` mean required. Anything else is
     dropped from `required_metadata_fields`.

3. **`MappingColumnsConfig` expansion**:
   - Add split-mode column names (defaults match real CSV headers:
     `IDRVI`, `IDCM`, `IDClaseDocumental`, `CMISType`, `IDCorto`,
     `Metadato`, `Requerido`).
   - Add `col_required_marker` defaulting to `"Yes"` (the bank's
     convention — matches `docs/samples/csv/MetadatosCM.csv`).

4. **`cmis_type_column` exposed in `MappingConfig`** (gap from 034):
   The pydantic schema previously did not propagate it. After 035 the
   consolidated mode supports an explicit `cmis_type_column` override
   too.

5. **Wiring helper `build_mapping_service(MappingConfig) -> MappingService`**:
   Single factory that the four call sites
   (`config/wiring.py`, `cli/doctor.py` ×2, `cli/commands/inspect.py`
   ×2) consume. The mode dispatch lives in one place.

6. **Sample CSV update**:
   - `docs/samples/csv/MapeoRVI_CM.csv` gains a `CMISType` column with
     empty placeholder values (the bank fills them in at deployment).

7. **Docs**:
   - `docs/how-to/as400-sync.md` known-limitations entry pointing at
     035 removed (TIPIDN is no longer empty in split mode).
   - Configuration guide example showing both modes.

## Backwards compatibility

- All 857 existing tests use the consolidated test fixture
  `modelo_documental.csv`. **None of them break.** Consolidated mode
  is the default when only `csv_path` is set.
- The Java parallel migrator's read pattern of `MapeoRVI_CM.csv` is
  preserved — we only **append** the `CMISType` column; existing
  readers ignore unknown trailing columns.

## Out of scope

- Reading the production `MapeoRVI_CM.csv` with **CMISType values
  filled in**: the bank owns that file. We only ship the
  infrastructure so the file works when handed to us.
- Migrating test fixtures to split format. They stay consolidated —
  that exercises the legacy mode.
- Changing `clase_name` representation in any output (logs, inspect).
  Operators see `clase_id` in split mode; that's the documented
  trade-off.

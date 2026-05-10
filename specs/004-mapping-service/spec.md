# Spec — 004-mapping-service

**Status**: Draft (under review)
**Created**: 2026-05-09
**Author**: bitBreaker
**Constitution version at draft time**: v1.0.0
**Depends on**: 002-domain-models-and-ports, 003-tabular-data-source-adapter (both merged)

> The **what** of this change. Implements the first service-layer class — `MappingService` — over the Modelo Documental. The **how** lives in `plan.md`.

---

## 1. Intent

Implement `cmcourier.services.mapping.MappingService`: the in-memory cache and lookup over the **Modelo Documental** (REBIRTH §4). It loads the mapping table once at construction via any `IDataSource`, builds an `id_rvi → CMMapping` dict, and exposes lookups for stage S2 (Document Class Mapping).

This is the **first service** in CMCourier. It validates that the hexagonal architecture established by 001-003 works end-to-end:

- A `services/` module imports only `cmcourier.domain.*` (ports + models + exceptions).
- A real `IDataSource` adapter (`TabularDataSource`) feeds the service in tests.
- The service raises domain-defined exceptions (`IDRViNotMappedError`).

After this change merges, the next service (`MetadataService`) and the pre-flight `doctor` command can be built on top.

---

## 2. Why now

- Stage S2 of every pipeline (REBIRTH §10.1) needs a mapping lookup to convert `RVABREPDocument.id_rvi` into a `CMMapping`. Without a service implementing the lookup, no orchestrator can move past S1.
- The `doctor` command (REBIRTH §10.5) needs to enumerate all mappings to validate "every ID RVI in the upcoming batch has a mapping" — it needs `get_all`.
- The mapping is the smallest and most isolated service. Building it first surfaces architectural friction (if any) before more complex services like metadata resolution.

---

## 3. Requirements

### 3.1 Class shape (REQ-001 through REQ-008)

- **REQ-001** — A class `MappingService` MUST exist in `src/cmcourier/services/mapping.py`.
- **REQ-002** — The constructor `MappingService(source: IDataSource, columns: MappingColumnsConfig | None = None)` MUST accept any concrete `IDataSource`. If `columns` is `None`, sensible defaults matching REBIRTH §4.1 column names MUST be used.
- **REQ-003** — A dataclass `MappingColumnsConfig` MUST exist (module-level, in the same file) carrying the column-name overrides: `col_clase_id`, `col_id_rvi`, `col_id_corto`, `col_clase_name`, `col_metadata_list`. All default to the REBIRTH §4.1 strings (`"ID CLASE DOCUMENTAL"`, `"ID RVI"`, `"ID Corto"`, `"CLASE DOCUMENTAL"`, `"METADATOS"`). The dataclass MUST be `frozen=True, slots=True`.
- **REQ-004** — At construction, the service MUST iterate every row from `source.get_all()` once and build an internal `dict[str, CMMapping]` keyed by `id_rvi`.
- **REQ-005** — At construction, the service MUST validate that every required column (per `MappingColumnsConfig`) is present in the first row received from `source`. Missing column MUST raise `ConfigurationError` with the missing column name in context.
- **REQ-006** — If a row's `id_rvi` is empty or missing (`None` after `NaN` normalization, empty string), the row MUST be skipped silently (it is malformed, not a duplicate; loggers note the count of skipped rows at `INFO` level).
- **REQ-007** — If the same `id_rvi` appears in more than one row, the **first occurrence wins** (REBIRTH §4.3 hard business rule). Subsequent occurrences MUST be discarded AND a `WARNING` MUST be logged for each via the standard library `logging` module, including the `id_rvi` and a count.
- **REQ-008** — The service MUST NOT mutate the constructor-provided source after construction. Calling `source.close()` is the caller's responsibility; the service does not own its lifecycle.

### 3.2 Public API (REQ-009 through REQ-014)

- **REQ-009** — `get_mapping(id_rvi: str) -> CMMapping`: returns the `CMMapping` for the given ID RVI. If not present, raises `IDRViNotMappedError(id_rvi=id_rvi)`. Lookup is O(1).
- **REQ-010** — `get_all() -> Iterator[CMMapping]`: yields every `CMMapping` in insertion order (the order rows arrived from the source). Used for `mapping-stats` and pre-flight validation.
- **REQ-011** — `count() -> int`: returns the number of mappings cached. Equivalent to `len(list(get_all()))` but O(1).
- **REQ-012** — `__contains__(id_rvi: str) -> bool`: enables `if "FF17" in service:` lookups for callers that just need a presence check without raising.
- **REQ-013** — All methods MUST be type-annotated and pass `mypy --strict`.
- **REQ-014** — The service MUST NOT import from `cmcourier.adapters.*` (Constitution Principle I). Only `cmcourier.domain.*` and Python standard library.

### 3.3 METADATOS parsing (REQ-015 through REQ-018)

- **REQ-015** — The `METADATOS` column value MUST be split on `,`, each fragment stripped of leading/trailing whitespace, and stored as `tuple[str, ...]` in `CMMapping.required_metadata_fields`.
- **REQ-016** — Empty fragments (resulting from doubled commas, leading/trailing commas, or an empty cell after strip) MUST be filtered out so the resulting tuple has no empty strings.
- **REQ-017** — A row whose `METADATOS` cell is `None` (`NaN` normalized) MUST be treated as "no required metadata" — `required_metadata_fields = ()`. This is valid; some document classes have no required metadata.
- **REQ-018** — The service MUST NOT modify or alias the field names beyond the strip+filter; alias resolution (e.g., `CIF → BAC_CIF`) is the responsibility of `MetadataService` (later change).

### 3.4 Tests (REQ-019 through REQ-024)

- **REQ-019** — Unit tests in `tests/unit/services/test_mapping.py` MUST exercise the service against a real `TabularDataSource` reading a CSV fixture (`tests/fixtures/services/modelo_documental.csv`). No `IDataSource` mocks. The fixture is small (~5-7 mappings).
- **REQ-020** — The fixture MUST include: a vanilla mapping; a mapping with multiple required metadata fields; a mapping with no required metadata (empty `METADATOS` cell); a duplicate `ID RVI` row (to validate first-wins + warning); and a row with empty `id_rvi` (to validate skip).
- **REQ-021** — Tests MUST cover: every public method's happy path; `get_mapping` raising `IDRViNotMappedError` for unknown `id_rvi`; the `__contains__` behavior; the duplicate warning being emitted (using `caplog`); empty `id_rvi` row skipped; missing required column raising `ConfigurationError`; `METADATOS` parsing edge cases (empty cell, doubled commas, whitespace).
- **REQ-022** — Tests MUST also cover the column-override path: constructing `MappingService` with a custom `MappingColumnsConfig` against a CSV that uses different column names succeeds.
- **REQ-023** — Tests MUST be marked `@pytest.mark.unit` (the SUT — the service — does no I/O; the data source it consumes is real but lightweight, no network).
- **REQ-024** — Branch coverage on `src/cmcourier/services/mapping.py` MUST be at least 95%.

### 3.5 Tooling (REQ-025 through REQ-027)

- **REQ-025** — `mypy --strict` MUST be clean on `cmcourier.services.mapping` (covered by the existing strict-mode override per pyproject.toml).
- **REQ-026** — `ruff check` and `ruff format --check` MUST be clean.
- **REQ-027** — `pre-commit run --all-files` MUST pass.

---

## 4. Acceptance Scenarios

### 4.1 Vanilla lookup

- **Given** a CSV fixture with a row `(clase_id="01.02.04.01.01", id_rvi="FF17", id_corto="PT57", clase_name="Autorizacion SMS", metadata_list="CIF, NUM_CUENTA_TARJETA")`
- **When** `service.get_mapping("FF17")` is called
- **Then** the returned `CMMapping` has `clase_id="01.02.04.01.01"`, `id_rvi="FF17"`, and `required_metadata_fields == ("CIF", "NUM_CUENTA_TARJETA")`
- **And** its `cm_folder` is `"/$type/BAC_01_02_04_01_01"` (from the model's computed property)

### 4.2 Unknown ID RVI raises

- **Given** the same fixture
- **When** `service.get_mapping("ZZ99")` is called
- **Then** `IDRViNotMappedError` is raised with `id_rvi="ZZ99"` in context

### 4.3 Duplicate ID RVI: first wins, warning logged

- **Given** a fixture with two rows both having `id_rvi="DUP01"`, distinct other fields
- **When** the service is constructed
- **Then** `service.get_mapping("DUP01")` returns the FIRST row's data
- **And** the second row's data is discarded
- **And** the `logging` framework received a `WARNING` mentioning `"DUP01"` and "duplicate"

### 4.4 Empty id_rvi row skipped

- **Given** a fixture with one row whose `id_rvi` cell is empty (becomes `None` after `NaN` normalization)
- **When** the service is constructed
- **Then** that row is silently skipped (not stored under any key)
- **And** `service.count()` reflects the reduced count
- **And** an `INFO` log line mentions the skipped count

### 4.5 Missing required column

- **Given** a CSV fixture missing the `ID RVI` column entirely
- **When** `MappingService(source, columns=defaults)` is constructed
- **Then** `ConfigurationError` is raised mentioning `"ID RVI"`

### 4.6 Custom columns config

- **Given** a CSV fixture with column names `Code`, `RVI`, `Short`, `Name`, `Meta`
- **When** `MappingService(source, columns=MappingColumnsConfig(col_clase_id="Code", col_id_rvi="RVI", col_id_corto="Short", col_clase_name="Name", col_metadata_list="Meta"))` is constructed
- **Then** `service.get_all()` yields all rows correctly

### 4.7 METADATOS parsing edge cases

- **Given** rows with these `METADATOS` values:
  - `"CIF, NUM_CUENTA"` → `("CIF", "NUM_CUENTA")`
  - `"CIF,,NUM_CUENTA"` → `("CIF", "NUM_CUENTA")` (empty fragment filtered)
  - `"  CIF  ,  NUM_CUENTA  "` → `("CIF", "NUM_CUENTA")` (whitespace stripped)
  - `""` (empty cell) → `()` (no required metadata)
  - `None` (NaN cell) → `()` (treated identical to empty)
  - `"CIF,"` (trailing comma) → `("CIF",)`
- **When** the service is constructed
- **Then** each row's `required_metadata_fields` matches the expected tuple

### 4.8 `__contains__`

- **Given** a fixture with `id_rvi="FF17"` present
- **When** `"FF17" in service` is evaluated
- **Then** the result is `True`
- **And** `"ZZ99" in service` is `False`

### 4.9 No PII

- **Given** the merged change
- **When** the contributor greps for known PII patterns under `src/cmcourier/services/`, `tests/unit/services/`, `tests/fixtures/services/`
- **Then** no real-looking name+identifier pairs are found

---

## 5. Out of Scope

- `MetadataService` — REBIRTH §6 (metadata resolution, fallback chain, validation, CIF self-healing). Lands in 005.
- `TriggerService` (REBIRTH §5) and `DocumentService` (REBIRTH §3). Land in later changes.
- The `doctor` command's mapping-completeness check, which uses this service. Lands when the doctor command is built.
- Field aliases (REBIRTH §6.2). Mapping service exposes raw names; aliasing is metadata's job.
- AS400-backed Modelo Documental (REBIRTH §4 mentions CSV or AS400). Once the AS400 adapter ships, the same service works against it without changes — the port is the adapter-agnostic contract.
- `mapping-stats` CLI command (REBIRTH §11 `inspect mapping-stats`). Service exposes `get_all()`; the command is built later.

---

## 6. Constraints from Constitution

- **Principle I**: services depend on **ports**, never on adapters. `mapping.py` imports `IDataSource` and `CMMapping` and `IDRViNotMappedError` from `cmcourier.domain`. It does NOT import `cmcourier.adapters.sources.tabular`. The test file imports `TabularDataSource` because tests are wiring code, not the SUT.
- **Principle III**: 50-line function cap. Constructor is the longest method (~30 lines including validation, iteration, dict build, warning emission). Other methods are <10 lines each.
- **Principle V**: no env reads.
- **Principle VI**: tests use a REAL `TabularDataSource` against a CSV fixture. AS400 not mocked (none used).
- **Principle VII**: spec/plan/tasks committed before implementation.
- **Principle VIII**: synthetic identifiers in fixtures. PII grep clean.
- **Principle IX**: every method in the public API has a one-sentence docstring stating its role.

---

## 7. Risks & Open Questions

### 7.1 Known risks

- **`NaN` normalization happens at the adapter layer**, not the service. The service trusts that `source.get_all()` already returns `None` for missing values. If a future `IDataSource` implementation forgets to normalize, the service's `if not row[col_id_rvi]:` check still works (because `bool(np.nan) == True`, but `np.nan != ""`). Safer to be explicit: the service treats `None`, empty string, and missing-key the same way.
- **Logger configuration**: `services/mapping.py` calls `logging.getLogger(__name__)` at module import. If the application has not configured logging handlers, warnings may go to stderr (Python default). Acceptable; the `cli/ui/logging.py` setup (forthcoming) routes everything correctly later.
- **Memory for large mappings**: the service caches every row. The Modelo Documental in production is hundreds of rows, not millions. Trivial. If it ever grows, indexed lookup still works.

### 7.2 Open questions (resolved in plan.md)

- Should `MappingService` be a `@dataclass` or a regular class? **Plan**: regular class. Dataclasses are for data; this is behavior with state.
- Should the constructor sort the cache for deterministic `get_all` ordering? **Plan**: no. Insertion order (dict order in Python 3.7+) is deterministic and matches the source row order, which is meaningful (REBIRTH §4.3 first-wins implies source order is the contract).
- Should `get_mapping` accept normalization (e.g., uppercase) for case-insensitive lookup? **Plan**: NO. ID RVI is a precise code (`"FF17"`, `"FB01"`); case-insensitivity would be a footgun if the source has mixed case (it does not in practice). Keep it strict.

---

## 8. Verification Strategy

| REQ block | Verification |
|-----------|--------------|
| REQ-001..008 (class) | unit tests in `test_mapping.py` (construction, validation, duplicate, skip) |
| REQ-009..014 (API) | one test per public method |
| REQ-015..018 (METADATOS parsing) | `test_metadatos_parsing_edge_cases` (parametrized) |
| REQ-019..024 (tests) | the suite itself; coverage report |
| REQ-025..027 (tooling) | ruff / mypy / pre-commit on the staged files |
| Scenarios 4.1..4.9 | each maps to one or more named tests |

---

## 9. Cross-References

- Predecessor changes: `specs/002-domain-models-and-ports/`, `specs/003-tabular-data-source-adapter/`
- Constitution Principles I, III, V, VI, VII, VIII, IX
- REBIRTH §4 (Modelo Documental), §6.2 (field aliases — out of scope here), §10.1 (S2 stage uses this service)
- Plan: `specs/004-mapping-service/plan.md`
- Tasks: `specs/004-mapping-service/tasks.md`

# Spec — 003-tabular-data-source-adapter

**Status**: Draft (under review)
**Created**: 2026-05-09
**Author**: bitBreaker
**Constitution version at draft time**: v1.0.0
**Depends on**: 002-domain-models-and-ports (merged)

> The **what** of this change. Implements the first concrete adapter — `TabularDataSource` over CSV and XLSX files via pandas. The **how** lives in `plan.md`.

---

## 1. Intent

Provide the first concrete implementation of `cmcourier.domain.IDataSource`: a **`TabularDataSource`** class that reads CSV and XLSX files via pandas and exposes the IDataSource contract. After this change merges, services (004+) and tests of higher layers have a working data source against which to run, **without depending on AS400**.

Per Constitution Principle VI, `TabularDataSource` is the canonical dev/test data source for this project. The AS400 adapter (later change) implements the same port; both are interchangeable behind `IDataSource` and the service layer never knows which is wired.

The adapter handles:
- **CSV files** via `pandas.read_csv` (UTF-8 default; encoding overridable per source)
- **XLSX files** via `pandas.read_excel` (requires `openpyxl` engine; added as a dependency in this change)
- File format dispatched by extension (`.csv`, `.xlsx` — case-insensitive)
- Eager loading: the entire file is read into memory at construction. Streaming via `chunksize` is post-MVP (see `docs/roadmap/POST-MVP.md`, future entry).
- All `IDataSource` methods except `query(sql, ...)`, which raises `NotImplementedError` because tabular files have no SQL surface (see plan.md §3.2 for rationale).

---

## 2. Why now

- The `IDataSource` port has existed since 002 but no concrete implementation does. Services (004+) cannot be exercised against real data without one.
- Constitution Principle VI: the CSV adapter is the substitute for AS400 in development and tests. Without it, every higher-layer test depends on a real AS400 — unacceptable for a fast unit/integration loop.
- The `docs/samples/csv/` and `docs/samples/excel/` directories already contain real-shape fixtures from RVIMigration. We can write integration tests against them immediately.
- 003 is the **shortest path** from "ports exist" to "services have something to read against".

---

## 3. Requirements (RFC 2119)

### 3.1 Adapter class (REQ-001 through REQ-010)

- **REQ-001** — A class `TabularDataSource` MUST exist in `src/cmcourier/adapters/sources/tabular.py` and inherit from `cmcourier.domain.ports.IDataSource`.
- **REQ-002** — `TabularDataSource(path: Path, encoding: str = "utf-8", sheet_name: str | int = 0)` constructor MUST accept a file path, an optional encoding (CSV only — ignored for XLSX), and an optional sheet name or index (XLSX only — ignored for CSV).
- **REQ-003** — At construction, the adapter MUST validate that *path* exists (`FileNotFoundError` otherwise) and that the file extension is one of `.csv`, `.xlsx`, `.xls` (case-insensitive). Unknown extensions MUST raise `ConfigurationError`.
- **REQ-004** — At construction, the adapter MUST eagerly load the file into a private `pandas.DataFrame`. If `pandas` raises during load (corrupt file, encoding mismatch, empty file with strict-typed schema), the exception MUST be wrapped in `ConfigurationError` with the original cause attached.
- **REQ-005** — All column headers MUST be preserved as strings exactly as written in the source file. No automatic case-folding, no whitespace stripping.
- **REQ-006** — All row values MUST be returned to callers as their pandas-inferred types (`str`, `int`, `float`, `numpy.datetime64`, `None` for blank cells). The adapter performs no type coercion. Callers (services, factories) handle conversion to domain types.
- **REQ-007** — `NaN` values from pandas MUST be normalized to Python `None` before returning to callers. This avoids leaking pandas-specific sentinels through the port boundary.
- **REQ-008** — The class MUST be importable as `from cmcourier.adapters.sources.tabular import TabularDataSource`.
- **REQ-009** — `cmcourier.adapters.sources.__init__` MUST re-export `TabularDataSource` for direct `from cmcourier.adapters.sources import TabularDataSource` usage.
- **REQ-010** — The adapter MUST NOT cache or share data across instances. Each instance owns its own DataFrame; closing one instance must not affect another.

### 3.2 IDataSource method implementations (REQ-011 through REQ-020)

- **REQ-011** — `get_all() -> Iterator[dict[str, Any]]`: yields every row of the file as a `dict[str, Any]`, with `NaN` normalized to `None`. Order matches file order.
- **REQ-012** — `count() -> int`: returns the total number of rows in the file (header excluded).
- **REQ-013** — `get_by_fields(filters: Mapping[str, Any]) -> list[dict[str, Any]]`: returns rows where every key-value pair in *filters* matches by equality. An empty *filters* dict returns all rows. Missing keys (filter key not in DataFrame columns) raises `KeyError`.
- **REQ-014** — `get_by_fields_in(field: str, values: list[Any], fixed_filters: Mapping[str, Any]) -> list[dict[str, Any]]`: returns rows where `df[field].isin(values)` AND every fixed-filter equality holds. Missing *field* raises `KeyError`.
- **REQ-015** — `query_stream(sql: str, params: list[Any] | None = None) -> Iterator[dict[str, Any]]`: raises `NotImplementedError` with a clear message pointing the caller to `get_by_fields` / `get_all`.
- **REQ-016** — `query(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]`: raises `NotImplementedError` with the same message as `query_stream`. Tabular sources have no SQL surface.
- **REQ-017** — `close() -> None`: releases the in-memory DataFrame (`del self._df`). Subsequent operations on a closed instance MUST raise `RuntimeError("operation on closed TabularDataSource")`.
- **REQ-018** — `close()` MUST be idempotent: calling it twice does NOT raise.
- **REQ-019** — All filter and lookup operations MUST be O(N) where N is the row count. The adapter does not build indexes (post-MVP optimization).
- **REQ-020** — `NaN`-to-`None` normalization MUST also apply to dict keys' values within rows yielded by `get_all`, `get_by_fields`, and `get_by_fields_in`.

### 3.3 File format dispatch (REQ-021 through REQ-024)

- **REQ-021** — On `.csv` extension, the adapter MUST call `pandas.read_csv(path, encoding=<self.encoding>, dtype=str, keep_default_na=True)`. Reading as strings preserves leading zeros (relevant for RVABREP transaction numbers and CIFs) and lets the caller parse integers explicitly when needed.
- **REQ-022** — On `.xlsx` or `.xls` extension, the adapter MUST call `pandas.read_excel(path, sheet_name=<self.sheet_name>, dtype=str, engine="openpyxl")`.
- **REQ-023** — `openpyxl` MUST be added to `pyproject.toml` runtime dependencies (`>=3.1,<4.0`). It is required by `pandas.read_excel` for the `.xlsx` engine.
- **REQ-024** — The dispatch MUST be case-insensitive on the extension (`.CSV`, `.XLSX`, `.Csv` all valid).

### 3.4 Tests (REQ-025 through REQ-032)

- **REQ-025** — Integration tests in `tests/integration/adapters/test_tabular_data_source.py` MUST cover both CSV and XLSX formats via parametrization.
- **REQ-026** — Test fixtures MUST live under `tests/fixtures/sources/`:
  - `sample.csv` — small CSV with 5 rows, 3 columns (string, integer-as-string, datetime-string)
  - `sample.xlsx` — same shape as `sample.csv`, generated via the same source data so behavior is identical across formats
  - `multi_sheet.xlsx` — two sheets to test the `sheet_name` parameter
  - `bad_extension.txt` — for the unknown-extension test
- **REQ-027** — A pytest fixture MUST generate `sample.xlsx` and `multi_sheet.xlsx` from a Python data structure during the integration test session if they do not exist (deterministic regeneration). Committed binary fixtures are acceptable but not required.
- **REQ-028** — Tests MUST cover the happy path of every public method (`get_all`, `count`, `get_by_fields`, `get_by_fields_in`, `close`).
- **REQ-029** — Tests MUST cover error paths: nonexistent file, unknown extension, corrupt CSV, encoding mismatch, missing filter key, operation after close.
- **REQ-030** — Tests MUST cover `NaN` → `None` normalization: a row with a blank cell MUST yield a dict where that column's value is `None`, never `NaN`, never `""`.
- **REQ-031** — Tests MUST cover that `query()` and `query_stream()` raise `NotImplementedError`.
- **REQ-032** — Tests MUST be marked `@pytest.mark.integration` and run under `pytest -m integration`.

### 3.5 Coverage and tooling (REQ-033 through REQ-035)

- **REQ-033** — Branch coverage on `src/cmcourier/adapters/sources/tabular.py` MUST be at least 90% (slightly lower than the domain layer's 95% because pandas error paths are awkward to trigger; we cover the ones that matter).
- **REQ-034** — `mypy` MUST be clean. The adapter is in `cmcourier.adapters.*` which is **not** under the strict-mode override per Constitution §Constraints — baseline mypy applies. The pandas-related `Any` types are accepted at the port boundary.
- **REQ-035** — `ruff` MUST be clean.

---

## 4. Acceptance Scenarios

### 4.1 Read a CSV happy path

- **Given** `tests/fixtures/sources/sample.csv` with header `Name,Age,Birth` and 5 data rows
- **When** `TabularDataSource(Path("tests/fixtures/sources/sample.csv"))` is constructed
- **And** `list(adapter.get_all())` is called
- **Then** the result is a list of 5 dicts, each with keys `Name`, `Age`, `Birth`
- **And** `adapter.count()` returns 5

### 4.2 Read an XLSX with same shape

- **Given** `tests/fixtures/sources/sample.xlsx` generated from the same data as `sample.csv`
- **When** `TabularDataSource(Path("tests/fixtures/sources/sample.xlsx"))` is constructed
- **And** `list(adapter.get_all())` is called
- **Then** the result is functionally identical to scenario 4.1 (same dicts, same row order)

### 4.3 NaN normalized to None

- **Given** a CSV row with a blank cell in column `Age`
- **When** the row is retrieved via `get_all` or `get_by_fields`
- **Then** the dict value at key `Age` is `None`, NOT `numpy.nan` and NOT `""`

### 4.4 Filter by field

- **Given** the sample CSV with `Name` column containing `"JUANPEREZ01"` in row 1 and 4
- **When** `adapter.get_by_fields({"Name": "JUANPEREZ01"})` is called
- **Then** the result contains exactly 2 dicts, both with `Name == "JUANPEREZ01"`

### 4.5 Filter by IN-list

- **Given** the sample CSV with `system_id` column containing values `"1"`, `"2"`, `"5"` distributed
- **When** `adapter.get_by_fields_in("system_id", ["1", "5"], fixed_filters={"Status": "ACTIVE"})` is called
- **Then** the result contains only rows where `system_id ∈ {1, 5}` AND `Status == "ACTIVE"`

### 4.6 Unknown extension is rejected

- **Given** `tests/fixtures/sources/bad_extension.txt`
- **When** `TabularDataSource(Path("...bad_extension.txt"))` is constructed
- **Then** `ConfigurationError` is raised mentioning the extension

### 4.7 Nonexistent file

- **Given** a path that does not exist
- **When** `TabularDataSource(Path("/nope.csv"))` is constructed
- **Then** `FileNotFoundError` is raised

### 4.8 SQL methods raise

- **Given** a constructed adapter
- **When** `adapter.query("SELECT *")` is called
- **Then** `NotImplementedError` is raised, with a message that names the supported methods (`get_by_fields`, `get_all`)
- **And** the same applies to `adapter.query_stream("...")`

### 4.9 Operation after close

- **Given** a constructed adapter
- **When** `adapter.close()` is called
- **And** then `adapter.get_all()` is called
- **Then** `RuntimeError` is raised with message "operation on closed TabularDataSource"
- **And** calling `adapter.close()` a second time does NOT raise

### 4.10 Multi-sheet XLSX

- **Given** `tests/fixtures/sources/multi_sheet.xlsx` with sheets `Sheet1` and `Sheet2` of different content
- **When** `TabularDataSource(Path("...multi_sheet.xlsx"), sheet_name="Sheet2")` is constructed
- **Then** `list(adapter.get_all())` returns rows from `Sheet2` only

### 4.11 Encoding override for CSV

- **Given** a CSV file encoded as `latin-1` with characters that fail under UTF-8
- **When** `TabularDataSource(Path("..."), encoding="latin-1")` is constructed
- **Then** the file loads cleanly
- **And** the same construction with `encoding="utf-8"` raises `ConfigurationError`

---

## 5. Out of Scope

- Streaming via `chunksize` on `read_csv` / `read_excel`. Eager loading is sufficient for fixtures and the volumes the dev/test workflow exercises. Streaming is a post-MVP item if/when memory becomes a problem.
- Encoding auto-detection (e.g., `chardet`). Caller specifies encoding explicitly. Auto-detection is a future change if real-world CSVs surface that need it.
- Index optimization (sorting / pre-built dicts for lookup). All operations are linear scans. The dev/test workloads are tiny; production migrations will use the AS400 adapter, not this one.
- AS400 adapter (`cmcourier.adapters.sources.as400.AS400DataSource`). Implements the same `IDataSource` port via `pyodbc`. Lands in a later change.
- Service-layer factories that convert raw `dict[str, Any]` rows into typed domain models (`TriggerRecord`, `RVABREPDocument`, `CMMapping`). Lands in 004+.
- A `query` SQL implementation via `pandasql` or `duckdb`. Tabular sources expose explicit field-based methods; SQL is for AS400.
- Round-trip writing (the adapter is read-only). If a tabular write surface is ever needed, it goes in a separate `ITabularWriter` port and adapter.

---

## 6. Constraints from Constitution

- **Principle I**: the adapter is in `cmcourier.adapters.*` — not subject to the "zero deps" rule that binds `domain/`. It freely uses `pandas`, `openpyxl`, `numpy`. It does NOT import anything from `cmcourier.services`, `cmcourier.orchestrators`, or `cmcourier.cli`.
- **Principle III**: 50-line function cap. Longest expected function is the constructor (~30 lines including dispatch + load + validation). All filter methods are <20 lines.
- **Principle V**: no env reads. The adapter takes its config (path, encoding, sheet_name) as constructor arguments. Wiring from `config.yaml` is the responsibility of the future config layer (005).
- **Principle VI**: integration tests use real CSV and XLSX files from `tests/fixtures/sources/`. The adapter is the test substitute for AS400; it is itself NOT mocked.
- **Principle VII**: this spec exists before any code ships.
- **Principle VIII**: test fixtures use synthetic identifiers (per `docs/samples/` precedent). No real PII.
- **Principle IX**: the `query()` raising `NotImplementedError` is documented in plan.md with a clear rationale — not a "TODO".

---

## 7. Risks & Open Questions

### 7.1 Known risks

- `pandas` may infer types differently between CSV and XLSX for the same content (e.g., `"00123"` becomes integer 123 in one, string `"00123"` in the other). We mitigate by passing `dtype=str` in both calls — every column is a string at the adapter layer. Type conversion is a service-layer responsibility.
- `openpyxl` is added as a runtime dependency. Adds ~5 MB to the install size. Justified by the explicit user requirement to support XLSX.
- pandas frequently emits `FutureWarning` about API changes. Tests must NOT rely on suppressing them; the adapter code must be future-proof against the warned-about changes (use the modern API directly).
- `NaN` normalization happens at every row yield. For very large files, this is per-cell overhead. Acceptable at MVP scales (tens of thousands of rows). Revisit if profiling shows it on the hot path.

### 7.2 Open questions (resolved in plan.md)

- Should `dtype=str` be configurable, or is it always-on? **Plan**: always-on. Type inference is a service-layer concern.
- Should `query()` raise `NotImplementedError` or a custom exception? **Plan**: `NotImplementedError` is the standard Python idiom for "method exists but not supported here". A custom exception adds noise without value.
- Should the adapter accept a `pathlib.Path` only, or also a `str` path? **Plan**: `Path` only. Callers convert at the boundary. Consistent with PEP 519 + modern Python style.
- Multi-sheet XLSX with sheet selection: should `sheet_name` accept `None` (read all sheets and concatenate)? **Plan**: NO. One file, one sheet. If users need a "concatenated view", they generate it ahead of time. The adapter is dumb about its source.

---

## 8. Verification Strategy

| REQ block | Verification |
|-----------|--------------|
| REQ-001..010 (class, construction) | unit / integration tests in `test_tabular_data_source.py`; mypy; ruff |
| REQ-011..020 (IDataSource methods) | one test per method, parametrized over CSV / XLSX |
| REQ-021..024 (dispatch) | `test_csv_dispatch`, `test_xlsx_dispatch`, `test_unknown_extension`, `test_case_insensitive_extension` |
| REQ-025..032 (tests) | the very fact tests pass; `pytest -m integration` collects ≥ 12 tests |
| REQ-033..035 (coverage + tooling) | `pytest --cov=src/cmcourier/adapters/sources/tabular`; ruff; mypy |
| Scenarios 4.1..4.11 | each maps to one or more named tests |

---

## 9. Cross-References

- Predecessor change: 002-domain-models-and-ports (defines `IDataSource`, `ConfigurationError`)
- Constitution Principles I, III, V, VI, VII, VIII, IX
- the spec (trigger source modes — CSV is mode 1), §6.6 (metadata pre-fetch — sources are CSV / AS400 tables), §12 (datasources registry)
- Plan: `specs/003-tabular-data-source-adapter/plan.md`
- Tasks: `specs/003-tabular-data-source-adapter/tasks.md`

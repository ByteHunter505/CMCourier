# Spec — 006-trigger-service

**Status**: Draft (under review)
**Created**: 2026-05-10
**Author**: bitBreaker
**Constitution version**: v1.0.0
**Depends on**: 002, 003, 004, 005 (all merged)

> Implements stage S0 (Trigger Acquisition) of every pipeline. Concrete `S0Strategy` implementations for CSV-driven and RVABREP-driven trigger sources, plus stubs for AS400 and local-scan sources that raise `NotImplementedError` with explicit messages.

---

## 1. Intent

Populate `src/cmcourier/services/triggers/` with two concrete `S0Strategy` implementations:

- **`CsvTriggerStrategy`** — reads triggers from any tabular `IDataSource` (matches REBIRTH §5.1 mode `csv:alias`).
- **`DirectRvabrepTriggerStrategy`** — discovers triggers by scanning RVABREP itself, optionally filtered by system codes and/or document types, and deduplicates `(shortname, system_id)` pairs (matches REBIRTH §5.1 mode `direct_rvabrep`).

Plus two stub strategies for the modes that depend on infrastructure not yet shipped:

- **`As400TriggerStrategy`** — raises `NotImplementedError` (depends on the AS400 adapter, future change).
- **`LocalScanTriggerStrategy`** — raises `NotImplementedError` (depends on a folder-scanner module, future change).

After this change merges, **stage S0 is implementable for every pipeline whose data source is CSV or RVABREP-direct**. The first MVP pipeline (`rvabrep-pipeline`) uses `DirectRvabrepTriggerStrategy`; the `csv-trigger-pipeline` uses `CsvTriggerStrategy`. Both can be wired and tested end-to-end after this change + a tracking store + an orchestrator.

---

## 2. Why now

- Stage S0 is the entry point of every pipeline (REBIRTH §10.1). With S0 unimplemented, no orchestrator can run.
- The `S0Strategy` port has existed since 002. Two concrete implementations are needed for the MVP pipelines; this change ships both.
- The `as400` and `local_scan` stubs honor the contract today and document the expected future shape, so the orchestrator can dispatch to them by command and surface a clear "not yet" error to operators.

---

## 3. Requirements (RFC 2119)

### 3.1 Module layout (REQ-001 through REQ-005)

- **REQ-001** — Source files MUST live under `src/cmcourier/services/triggers/`:
  - `__init__.py` — re-exports the public types
  - `csv.py` — `CsvTriggerStrategy` + `CsvTriggerColumnsConfig`
  - `direct_rvabrep.py` — `DirectRvabrepTriggerStrategy` + `RvabrepColumnsConfig` + `RvabrepFilters`
  - `stubs.py` — `As400TriggerStrategy` + `LocalScanTriggerStrategy` (both raise `NotImplementedError`)
- **REQ-002** — Each strategy MUST inherit from `cmcourier.domain.ports.S0Strategy`.
- **REQ-003** — `cmcourier.services.__init__` MUST re-export every public name from `cmcourier.services.triggers`.
- **REQ-004** — Constitution Principle I binds: the `services/triggers/` modules import only `cmcourier.domain.*` and stdlib. NO adapter imports.
- **REQ-005** — Each strategy's `acquire(source_descriptor: str)` method ignores `source_descriptor` (the strategy is fully configured by its constructor). The argument is the port contract from 002 and remains for compatibility; a future port refinement may remove it.

### 3.2 `CsvTriggerStrategy` (REQ-006 through REQ-013)

- **REQ-006** — `CsvTriggerStrategy(source: IDataSource, columns: CsvTriggerColumnsConfig | None = None)` constructor accepts the data source and optional column-name overrides.
- **REQ-007** — `CsvTriggerColumnsConfig` is a frozen+slots dataclass with `col_shortname: str = "ShortName"`, `col_cif: str = "CIF"`, `col_system_id: str = "SystemID"` (defaults match REBIRTH §12 trigger config).
- **REQ-008** — On `acquire()`, the strategy iterates `source.get_all()`. The first row's keys MUST be checked against required columns (`col_shortname`, `col_system_id`); missing column raises `ConfigurationError` with the missing column name in context. **`col_cif` is NOT required** because the CSV may legitimately not carry CIF (the CIF self-healing rule from REBIRTH §6.5 / 005 covers that).
- **REQ-009** — For each row, the strategy yields a `TriggerRecord` with:
  - `shortname` = `str(row[col_shortname]).strip()`
  - `cif` = `str(row[col_cif]).strip()` if the column is present and non-blank; `None` otherwise
  - `system_id` = `str(row[col_system_id]).strip()`
- **REQ-010** — Rows where `shortname` or `system_id` is blank (`None`, empty string, whitespace-only) MUST be silently skipped. The strategy MAY log an `INFO` line summarizing the skipped count when the iterator is exhausted.
- **REQ-011** — The strategy MUST yield `TriggerRecord` lazily (generator), not materialize a list. Trigger lists may be very large (REBIRTH §10.4 mentions 200k+).
- **REQ-012** — The strategy MUST NOT close `source` — its lifecycle is the caller's.
- **REQ-013** — The strategy MUST NOT deduplicate (CSV consumers expect every row through; deduplication is a different concern).

### 3.3 `DirectRvabrepTriggerStrategy` (REQ-014 through REQ-021)

- **REQ-014** — `DirectRvabrepTriggerStrategy(rvabrep_source: IDataSource, filters: RvabrepFilters | None = None, columns: RvabrepColumnsConfig | None = None)` constructor accepts the RVABREP-shaped data source, optional filters, and optional column-name overrides.
- **REQ-015** — `RvabrepColumnsConfig` is a frozen+slots dataclass with `col_shortname: str = "ABABCD"`, `col_cif: str = "ABACCD"`, `col_system_id: str = "ABAACD"`, `col_id_rvi: str = "ABAHCD"` (RVABREP physical column names per REBIRTH §3.2).
- **REQ-016** — `RvabrepFilters` is a frozen+slots dataclass with `systems: tuple[str, ...] = ()` and `document_types: tuple[str, ...] = ()`. Empty tuple = "no filter" (return everything).
- **REQ-017** — On `acquire()`, the strategy iterates the RVABREP source filtered by `(systems, document_types)`:
  - If both filters are empty, iterate `rvabrep_source.get_all()`.
  - If only `systems` set, use `rvabrep_source.get_by_fields_in(field=col_system_id, values=list(systems), fixed_filters={})`.
  - If only `document_types` set, use `get_by_fields_in(field=col_id_rvi, values=list(document_types), fixed_filters={})`.
  - If both set, query the cross-product. The simplest implementation iterates once with one filter and rejects the other in Python — documented in plan.md.
- **REQ-018** — For each filtered RVABREP row, the strategy extracts the trigger tuple `(shortname=row[col_shortname], cif=row[col_cif] or None, system_id=row[col_system_id])` and **deduplicates by `(shortname, system_id)`**: each unique pair yields exactly ONE `TriggerRecord`. First occurrence wins (matches REBIRTH §4.3 first-wins precedent).
- **REQ-019** — Rows with blank `shortname` or `system_id` MUST be silently skipped (same as `CsvTriggerStrategy`).
- **REQ-020** — `cif` extraction: if `col_cif` is present and non-blank, populate `TriggerRecord.cif`. Otherwise `None` (CIF self-healing in 005 will resolve it).
- **REQ-021** — The strategy MUST yield lazily.

### 3.4 Stub strategies (REQ-022 through REQ-024)

- **REQ-022** — `As400TriggerStrategy(query: str)` constructor accepts the AS400 SQL query string. Calling `acquire()` raises `NotImplementedError` with a message naming `"AS400 adapter not yet shipped; this strategy will activate when that adapter change merges."`.
- **REQ-023** — `LocalScanTriggerStrategy(scan_path: pathlib.Path, cif_lookup_source: IDataSource | None = None)` constructor accepts the scan path and an optional CIF lookup source. Calling `acquire()` raises `NotImplementedError` with a message naming `"local-scan strategy not yet shipped; depends on a forthcoming folder-scanner module."`.
- **REQ-024** — Both stubs are importable and constructible (no `NotImplementedError` at construction time) so the orchestrator dispatch can wire them up and surface the error only when the strategy is actually used. This is the same pattern used for `as400:<alias>` in 005.

### 3.5 Tests (REQ-025 through REQ-030)

- **REQ-025** — Unit tests in `tests/unit/services/test_trigger_strategies.py` MUST cover both real strategies plus stubs.
- **REQ-026** — Test fixtures MUST live under `tests/fixtures/services/triggers/`:
  - `trigger_list.csv` — minimal trigger CSV (columns `ShortName`, `CIF`, `SystemID`; ~5 rows including one with empty CIF)
  - `trigger_list_alt_columns.csv` — same data with non-default column names (for the columns-config override test)
  - `rvabrep_export.csv` — RVABREP-shaped CSV (~10 rows; multiple rows per `(shortname, system_id)` pair to test deduplication; mix of `system_codes` and `id_rvi` values to test filtering)
- **REQ-027** — Tests MUST cover: CSV happy path, CSV custom columns, CSV missing required column raises, CSV with empty CIF yields `cif=None`, CSV blank rows skipped; RVABREP no filters, RVABREP filtered by `systems`, RVABREP filtered by `document_types`, RVABREP filtered by both, RVABREP deduplication, RVABREP rows with blank shortname/system_id skipped; `as400` stub raises with explicit message; `local_scan` stub raises with explicit message.
- **REQ-028** — Tests MUST verify the strategies are `S0Strategy` subclasses (`isinstance` check).
- **REQ-029** — Branch coverage on `src/cmcourier/services/triggers/` (combined) MUST be at least 95%.
- **REQ-030** — Tests MUST be marked `pytest.mark.unit` (SUT does no I/O; the data source is wiring).

### 3.6 Tooling (REQ-031 through REQ-033)

- **REQ-031** — `mypy --strict` MUST be clean.
- **REQ-032** — `ruff check` and `ruff format --check` MUST be clean.
- **REQ-033** — `pre-commit run --all-files` MUST pass.

---

## 4. Acceptance Scenarios

### 4.1 CSV happy path

- **Given** a CSV fixture with header `ShortName,CIF,SystemID` and 3 data rows
- **When** `CsvTriggerStrategy(source=tabular).acquire("")` is iterated
- **Then** 3 `TriggerRecord` instances are yielded, with `shortname`, `cif`, `system_id` matching the rows

### 4.2 CSV custom columns

- **Given** a CSV with column names `Cliente`, `Doc`, `Sistema`
- **And** `CsvTriggerColumnsConfig(col_shortname="Cliente", col_cif="Doc", col_system_id="Sistema")`
- **When** the strategy iterates
- **Then** records yield correctly

### 4.3 CSV missing required column

- **Given** a CSV without the `ShortName` column
- **When** `acquire()` is iterated (first row)
- **Then** `ConfigurationError` is raised with the missing column name in context

### 4.4 CSV with empty CIF cell yields cif=None

- **Given** a CSV row with the `CIF` column blank
- **When** the strategy iterates that row
- **Then** the yielded `TriggerRecord.cif is None` (not empty string, not `NaN`)

### 4.5 CSV blank rows skipped

- **Given** a CSV row with blank `ShortName`
- **When** the strategy iterates
- **Then** that row is NOT yielded

### 4.6 RVABREP no filters yields every unique (shortname, system_id)

- **Given** an RVABREP fixture with 10 rows but only 4 unique `(shortname, system_id)` pairs
- **When** `DirectRvabrepTriggerStrategy(source).acquire("")` is iterated
- **Then** exactly 4 `TriggerRecord` instances are yielded

### 4.7 RVABREP filtered by systems

- **Given** the same fixture and `RvabrepFilters(systems=("1",))`
- **When** the strategy iterates
- **Then** only triggers with `system_id == "1"` are yielded

### 4.8 RVABREP filtered by document_types

- **Given** the same fixture and `RvabrepFilters(document_types=("FF17",))`
- **When** the strategy iterates
- **Then** only triggers whose RVABREP rows had `id_rvi == "FF17"` are yielded
- **And** deduplication by `(shortname, system_id)` still applies

### 4.9 RVABREP filtered by both

- **Given** filters `RvabrepFilters(systems=("1",), document_types=("FF17",))`
- **When** the strategy iterates
- **Then** only triggers matching BOTH filters are yielded

### 4.10 RVABREP cif extraction

- **Given** an RVABREP row with `col_cif` populated (e.g., `"123456"`)
- **When** that row produces a trigger
- **Then** the yielded `TriggerRecord.cif == "123456"`
- **And** if `col_cif` is blank, the yielded `TriggerRecord.cif is None`

### 4.11 as400 stub raises

- **When** `As400TriggerStrategy(query="SELECT ...").acquire("")` is iterated
- **Then** `NotImplementedError` is raised with `"AS400 adapter"` in the message

### 4.12 local_scan stub raises

- **When** `LocalScanTriggerStrategy(scan_path=Path("/tmp/x")).acquire("")` is iterated
- **Then** `NotImplementedError` is raised with `"local-scan"` in the message

### 4.13 Strategies are S0Strategy subclasses

- **When** `isinstance(strategy, S0Strategy)` is checked for each of the 4 strategies
- **Then** all return `True`

### 4.14 No PII

- **Given** the merged change
- **When** the contributor greps the new files for PII patterns
- **Then** only synthetic identifiers (`JUANPEREZ01`, `123456`, etc.)

---

## 5. Out of Scope

- AS400 adapter and the AS400 trigger strategy implementation (stub only here).
- Folder-scanner module and the local-scan strategy implementation (stub only here).
- A `TriggerService` class that wraps strategies. The strategies ARE the service surface; orchestrators (later changes) instantiate the appropriate strategy directly.
- Caching trigger results across pipeline invocations.
- Filter validation (e.g., enforcing valid `system_id` codes). Validation is orchestrator / pre-flight responsibility.
- Refactoring the `S0Strategy` port to remove the vestigial `source_descriptor` parameter. That requires a constitutional / spec amendment to 002 and is deferred.

---

## 6. Constraints from Constitution

- **Principle I**: services/triggers/ imports only `cmcourier.domain.*` and stdlib. NO adapter imports. Verified by static analysis.
- **Principle III**: 50-line function cap. Each strategy's `acquire` is ~25-35 lines.
- **Principle V**: no env reads.
- **Principle VI**: tests use real `TabularDataSource` over CSV fixtures. AS400 not mocked (none used); the `as400` stub doesn't even attempt I/O.
- **Principle VII**: spec/plan/tasks committed before implementation.
- **Principle VIII**: synthetic identifiers in fixtures; no real PII. The strategies log `shortname` and `system_id` at most (operational identifiers, not PII per se — but `cif` is, so it MUST NOT be logged).
- **Principle IX**: each strategy has a clear one-sentence docstring; design decisions live in plan.md.

---

## 7. Risks & Open Questions

### 7.1 Known risks

- **Filter combination semantics**: when both `systems` and `document_types` are set, the simplest implementation iterates by one filter and rejects the other in Python. For very large RVABREPs this could be slow. Plan documents the tradeoff and a future change can optimize via two `get_by_fields_in` queries with set intersection if profiling demands.
- **`source_descriptor` ignored**: future readers may try to pass meaningful values. Plan documents the rationale; tests assert it is ignored.
- **Stub raises only at `acquire`**, not construction: matches `as400:<alias>` in 005. Lets orchestrators dispatch first and fail late with a clear message. Tests pin this.
- **CIF leak in logs**: the strategies MUST NOT include `cif` in any log message. If they did, PII could leak. Code review and absence of log statements involving `cif` are the safeguards.

### 7.2 Open questions (resolved in plan.md)

- Should `acquire(source_descriptor)` raise if a non-empty descriptor is passed? **Plan**: NO. Silently ignore. Future port refinement will remove the parameter cleanly; raising now would break callers later.
- Should `RvabrepFilters` accept regex/glob patterns instead of equality lists? **Plan**: NO. Equality lists match REBIRTH §12 config shape (`filters.systems: []`, `filters.document_types: []`). If glob/regex is ever needed, that's a new field.
- Does deduplication preserve insertion order? **Plan**: YES. Use a `set` for `seen` membership check + a generator that yields the first occurrence in source order.

---

## 8. Verification Strategy

| REQ block | Verification |
|-----------|--------------|
| REQ-001..005 (layout) | files exist, classes inherit S0Strategy |
| REQ-006..013 (CSV strategy) | scenarios 4.1..4.5 |
| REQ-014..021 (RVABREP strategy) | scenarios 4.6..4.10 |
| REQ-022..024 (stubs) | scenarios 4.11..4.12 |
| REQ-025..030 (tests + coverage) | suite + cov report |
| REQ-031..033 (tooling) | ruff/mypy/pre-commit |

---

## 9. Cross-References

- Predecessor changes: 002 (S0Strategy port), 003 (TabularDataSource), 004 (services pattern), 005 (logging discipline + stub pattern)
- Constitution Principles I, III, V, VI, VII, VIII, IX
- REBIRTH §3.2 (RVABREP columns), §5 (Trigger List + 4 modes), §10.1 (S0 in stage architecture), §12 (config)
- Plan: `specs/006-trigger-service/plan.md`
- Tasks: `specs/006-trigger-service/tasks.md`

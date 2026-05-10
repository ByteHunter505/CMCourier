# Spec — 005-metadata-service

**Status**: Draft (under review)
**Created**: 2026-05-10
**Author**: bitBreaker
**Constitution version**: v1.0.0
**Depends on**: 002, 003, 004 (all merged)

> The **what** of this change. Implements the metadata resolution service — the most complex service in CMCourier. The **how** lives in `plan.md`.

---

## 1. Intent

Implement `cmcourier.services.metadata.MetadataService`: per-field metadata resolution with **fallback chain**, **validation regex**, **default-value fallback**, **CIF self-healing**, **field alias normalization**, and **eager pre-fetching** of source tables (REBIRTH §6.6).

This is the engine of stage S3 (Metadata Resolution) in every pipeline. Without it, no document can be uploaded with correct metadata.

After this change merges, the only remaining services for an MVP pipeline are the trigger and document services (light wrappers) and the orchestrators that compose them.

---

## 2. Why now

- `MappingService` (004) tells us which `BAC_*` fields each document class requires. We have to resolve those fields' values.
- The CMIS upload adapter (later change) needs a `Mapping[str, str]` of CMIS property values; that mapping is what `MetadataService` produces.
- Pre-fetching is performance-critical for production scale (REBIRTH §6.6: "tens of thousands of AS400 queries" without it). Including it now means the service ships production-ready, not "good for testing then we revisit".

---

## 3. Requirements (RFC 2119)

### 3.1 Public types (REQ-001 through REQ-008)

- **REQ-001** — A class `MetadataService` MUST exist in `src/cmcourier/services/metadata.py`.
- **REQ-002** — A frozen dataclass `MetadataResolution` MUST exist (same module) with fields:
  - `metadata: ResolvedMetadata` — the resolved BAC_* properties
  - `healed_trigger: TriggerRecord` — the trigger, potentially with `cif` populated by self-healing
- **REQ-003** — A frozen dataclass `MetadataConfig` MUST exist with:
  - `field_aliases: Mapping[str, str]` — case-insensitive forward map (e.g., `"CIF" → "BAC_CIF"`, `"NUM_PRESTAMO" → "BAC_Num_Cuenta"`)
  - `field_sources: Mapping[str, FieldSourceConfig]` — keyed by **canonical** name (`BAC_*`)
  - `prefetch_enabled: bool` (default `True`) — whether to pre-load CSV sources at construction
- **REQ-004** — A frozen dataclass `FieldSourceConfig` MUST exist with:
  - `sources: tuple[SourceConfig, ...]` — ordered fallback chain
  - `default_value: str | None` — last-resort value, MUST also pass validation if the first source has validation
- **REQ-005** — A frozen dataclass `SourceConfig` MUST exist with:
  - `source_type: str` — one of `"trigger"`, `"rvabrep"`, `"csv:<alias>"`. `"as400:<alias>"` MUST raise `NotImplementedError` at resolution time (deferred to AS400 adapter change).
  - `lookup_value_column: str` — for `trigger`/`rvabrep`, the attribute name to read; for `csv:<alias>`, the column whose value is returned
  - `lookup_key_column: str | None` — for `csv:<alias>`, the column to match against the **lookup key** (resolved from the trigger or document); ignored for `trigger`/`rvabrep`
  - `validation: ValidationConfig | None` — optional regex check
- **REQ-006** — A frozen dataclass `ValidationConfig` MUST exist with `allowed_pattern: str | None = None`. The pattern is validated via `re.fullmatch` (not partial match).
- **REQ-007** — All five dataclasses (`MetadataResolution`, `MetadataConfig`, `FieldSourceConfig`, `SourceConfig`, `ValidationConfig`) MUST be `frozen=True, slots=True`.
- **REQ-008** — `cmcourier.services.__init__` MUST re-export `MetadataService`, `MetadataResolution`, `MetadataConfig`, `FieldSourceConfig`, `SourceConfig`, `ValidationConfig`.

### 3.2 Constructor + pre-fetching (REQ-009 through REQ-014)

- **REQ-009** — `MetadataService(config: MetadataConfig, sources_registry: Mapping[str, IDataSource])` MUST accept the config and a registry of CSV source aliases (e.g., `{"clients": tabular_clients, "accounts": tabular_accounts}`).
- **REQ-010** — At construction, if `config.prefetch_enabled` is `True`, the service MUST iterate every `csv:<alias>` source referenced in `config.field_sources` and **eagerly call `source.get_all()`** for each unique alias, building an in-memory cache.
- **REQ-011** — The pre-fetch cache MUST be keyed by `(alias, lookup_key_column, lookup_key_value, lookup_value_column)`. This lets a single source serve multiple fields with different lookup columns without re-iterating.
- **REQ-012** — If `prefetch_enabled` is `False`, every CSV resolution MUST go through `source.get_by_fields(...)` per call (slower but uses no extra memory).
- **REQ-013** — If a `csv:<alias>` referenced in config does NOT exist in `sources_registry`, the constructor MUST raise `ConfigurationError` with the missing alias name in context.
- **REQ-014** — The service MUST NOT close the sources in `sources_registry`. Their lifecycle is the caller's responsibility.

### 3.3 Resolution flow (REQ-015 through REQ-022)

- **REQ-015** — `resolve(trigger: TriggerRecord, document: RVABREPDocument, mapping: CMMapping) -> MetadataResolution` MUST be the sole resolution entry point.
- **REQ-016** — The fields to resolve are derived from `mapping.required_metadata_fields`, normalized via `config.field_aliases` (case-insensitive). Unknown aliases (no entry in `field_aliases` and no entry in `field_sources`) MUST raise `ConfigurationError` with the offending field name.
- **REQ-017** — **CIF self-healing**: if `trigger.cif is None` AND `"BAC_CIF"` is among the canonical fields to resolve, the service MUST resolve `BAC_CIF` FIRST, construct a new `TriggerRecord` with the resolved CIF, and use that for subsequent field resolutions. If `BAC_CIF` resolution fails, `MetadataError` propagates immediately (we cannot continue without a CIF).
- **REQ-018** — For each canonical field, the service walks `field_sources[field].sources` in order:
  1. Fetch the raw value from the source (per `source_type` dispatch).
  2. If the value is `None` or empty string, skip to the next source (treated as "not found").
  3. If the source has a `validation`, run `re.fullmatch(allowed_pattern, value)`. If it fails, skip to the next source.
  4. If the value passes, **use it** and stop.
- **REQ-019** — If all sources fail, the service tries `default_value`:
  - If `default_value is None`, raise `SourceFailedError(field_name=field, source="<all>")`.
  - If `default_value` is set, validate it against the **first source's validation regex** (if any). If passes, use it. If fails, raise `DefaultValidationFailedError(field_name=field, default_value=default_value)`.
  - If the first source has no validation, the default is accepted as-is.
- **REQ-020** — All resolved values are collected into a `dict[str, str]` keyed by canonical field name (`BAC_*`), wrapped in `ResolvedMetadata.from_dict(...)`.
- **REQ-021** — The returned `MetadataResolution.healed_trigger` is the trigger received in the call, OR a new `TriggerRecord` with `cif` populated if self-healing happened.
- **REQ-022** — The service MUST NOT mutate the input `trigger`, `document`, or `mapping`. Domain models are frozen; this is enforced by Python at runtime.

### 3.4 Source dispatch (REQ-023 through REQ-026)

- **REQ-023** — Source dispatch MUST be implemented as a dict-of-handlers, not an if/elif tree:
  ```python
  self._handlers: dict[str, Callable[..., str | None]] = {
      "trigger": self._fetch_trigger,
      "rvabrep": self._fetch_rvabrep,
      # csv:<alias> matched by prefix
  }
  ```
- **REQ-024** — `trigger` source MUST read the named attribute from `TriggerRecord` via `getattr(trigger, source.lookup_value_column)`. Unknown attribute raises `ConfigurationError`.
- **REQ-025** — `rvabrep` source MUST read the named attribute from `RVABREPDocument` via the same pattern.
- **REQ-026** — `csv:<alias>` source MUST:
  1. Look up the data source from `sources_registry[alias]`.
  2. Determine the lookup key value (the value to match in `lookup_key_column`). This is the `cif` field of the (possibly self-healed) trigger by convention. **TODO clarify in plan.md if we need a more general mechanism.**
  3. If pre-fetched, look up in cache. If not pre-fetched, call `source.get_by_fields({lookup_key_column: lookup_key_value})`.
  4. Return the first row's `lookup_value_column` value, or `None` if no row matches.

### 3.5 Field aliases (REQ-027 through REQ-029)

- **REQ-027** — Field aliasing MUST be case-insensitive (`"cif"`, `"CIF"`, `"Cif"` all map to `"BAC_CIF"`).
- **REQ-028** — If a field name appears as both an alias key AND a canonical key, the canonical key MUST be preferred (no double-aliasing).
- **REQ-029** — A field name that is neither a known alias nor a canonical key MUST raise `ConfigurationError` at resolution time, NOT at construction (since it depends on which mapping is active).

### 3.6 Tests (REQ-030 through REQ-035)

- **REQ-030** — Unit tests in `tests/unit/services/test_metadata.py` MUST cover the resolution flow against a real `TabularDataSource` registry.
- **REQ-031** — Test fixtures MUST live under `tests/fixtures/services/metadata/`:
  - `clients.csv` — CIF, Nombre_Cliente
  - `accounts.csv` — CIF, Num_Cuenta
  - `cards.csv` — CIF, Num_Cuenta_Tarjeta
  - These mirror the real samples in `docs/samples/csv/` but with synthetic identifiers.
- **REQ-032** — Tests MUST cover: vanilla resolution, fallback chain (first source fails validation, second succeeds), default-value fallback, default-validation failure raises `DefaultValidationFailedError`, CIF self-healing happy path, CIF self-healing where BAC_CIF itself fails (propagates), unknown alias raises, missing alias in registry raises at construction, pre-fetch on/off behavior, all source types (trigger, rvabrep, csv).
- **REQ-033** — Tests MUST cover the `as400:<alias>` source type raising `NotImplementedError` with a clear message pointing to "the AS400 adapter change is not shipped yet".
- **REQ-034** — Branch coverage on `src/cmcourier/services/metadata.py` MUST be at least 95%.
- **REQ-035** — All tests pass under `pytest -m unit` and complete in under 5 seconds total.

### 3.7 Tooling (REQ-036 through REQ-038)

- **REQ-036** — `mypy --strict` MUST be clean (services is in the strict-mode override).
- **REQ-037** — `ruff check` and `ruff format --check` MUST be clean.
- **REQ-038** — `pre-commit run --all-files` MUST pass.

---

## 4. Acceptance Scenarios

### 4.1 Vanilla resolution from trigger source

- **Given** a config where `BAC_Shortname` resolves from `trigger.shortname`
- **When** `resolve(trigger=TriggerRecord(shortname="JUANPEREZ01", cif="123456", system_id="1"), document=..., mapping=...)` is called
- **Then** `result.metadata["BAC_Shortname"] == "JUANPEREZ01"`

### 4.2 Fallback chain — first source fails validation

- **Given** `BAC_CIF` config with sources `[rvabrep:index2 (must match \d{6}), trigger:cif (must match \d{6})]`
- **And** `document.index2 == "ABC"` (fails validation)
- **And** `trigger.cif == "123456"` (passes)
- **When** `resolve(...)` is called
- **Then** `result.metadata["BAC_CIF"] == "123456"`

### 4.3 Default value fallback

- **Given** `BAC_CIF` config with `default_value="000000"` and one source that fails
- **And** the first source has validation `^\d{6}$`
- **When** all sources fail and `"000000"` matches the validation
- **Then** `result.metadata["BAC_CIF"] == "000000"`

### 4.4 Default validation failure raises

- **Given** `BAC_CIF` config with `default_value="abc"` (would fail `^\d{6}$`)
- **When** all sources fail and the default is checked
- **Then** `DefaultValidationFailedError(field_name="BAC_CIF", default_value="abc")` is raised

### 4.5 CIF self-healing happy path

- **Given** `trigger.cif is None` and `BAC_CIF` is in `mapping.required_metadata_fields`
- **And** `BAC_CIF` resolves to `"123456"` from `rvabrep:index2`
- **When** `resolve(...)` is called
- **Then** `result.healed_trigger.cif == "123456"`
- **And** `result.healed_trigger.shortname == trigger.shortname` (other fields preserved)
- **And** `result.metadata["BAC_CIF"] == "123456"`

### 4.6 CIF self-healing failure propagates

- **Given** `trigger.cif is None` and all `BAC_CIF` sources fail and no valid default
- **When** `resolve(...)` is called
- **Then** `SourceFailedError(field_name="BAC_CIF", source="<all>")` is raised
- **And** no other fields are attempted (fail fast)

### 4.7 Field alias normalization

- **Given** mapping requires `"CIF"` (uppercase, no `BAC_` prefix)
- **And** `field_aliases == {"CIF": "BAC_CIF"}`
- **When** `resolve(...)` is called
- **Then** the service resolves `BAC_CIF` per its `field_sources` config, not `CIF`

### 4.8 Unknown alias raises ConfigurationError

- **Given** mapping requires `"UNKNOWN_FIELD"` and neither aliases nor field_sources have it
- **When** `resolve(...)` is called
- **Then** `ConfigurationError` is raised with the field name in context

### 4.9 Pre-fetching reduces source calls

- **Given** `prefetch_enabled=True` and a CSV source with 100 rows
- **When** `resolve(...)` is called 10 times for different documents
- **Then** the source's `get_all()` was called exactly **once** (at construction)
- **And** `get_by_fields` was NOT called

### 4.10 as400 source raises NotImplementedError

- **Given** a config with `source_type="as400:default"` for some field
- **When** `resolve(...)` triggers that source
- **Then** `NotImplementedError` is raised with a message naming `"as400 adapter not yet shipped"`

### 4.11 No PII in tests

- **Given** the merged change
- **When** the contributor greps for known PII patterns under `src/cmcourier/services/metadata.py`, `tests/unit/services/test_metadata.py`, `tests/fixtures/services/metadata/`
- **Then** only synthetic identifiers (per REBIRTH samples convention)

---

## 5. Out of Scope

- AS400 source adapter (`as400:<alias>`). Raises `NotImplementedError` until its adapter ships.
- TTL-based cache invalidation (REBIRTH §6.6 mentions). Pre-fetch is one-shot at construction; if config files change, the process restarts. TTL becomes relevant when AS400 sources are pre-fetched (data on a live DB can change). Post-MVP.
- `metadata_prefetch_max_rows` skip-large-tables guard (REBIRTH §6.6). Useful in production with huge AS400 tables; not relevant for CSV. Post-MVP.
- `metadata_prefetch_exclude` list. Same reasoning. Post-MVP.
- TriggerService (REBIRTH §5) and DocumentService (REBIRTH §3). Land in subsequent changes.
- The `doctor` command's metadata-resolvability check. Will use `MetadataService.validate_field_resolvability(...)` (a method we may add later, NOT in this change unless it surfaces naturally).
- Pydantic config schema that loads `config.yaml` into `MetadataConfig`. Lands in a separate change.

---

## 6. Constraints from Constitution

- **Principle I**: `services/metadata.py` imports only `cmcourier.domain.*` and stdlib. NO adapter imports. Tests instantiate `TabularDataSource` (wiring), but the SUT does not.
- **Principle III**: 50-line function cap. Constructor + `resolve` are the longest methods (~40 lines each, with helpers split out). Helpers each <20 lines.
- **Principle V**: no env reads.
- **Principle VI**: tests use real `TabularDataSource` — `pytest.mark.unit` because SUT does no I/O.
- **Principle VII**: spec/plan/tasks committed before implementation.
- **Principle VIII**: PII discipline. The metadata service handles CIF, customer names, account numbers — these ARE PII. Logs MUST NOT include resolved values; logs identify *which field* failed but never WHAT value was resolved. CIF context in error messages is acceptable (it is the lookup key, not the value being protected) but customer name values are NOT logged.
- **Principle IX**: every public method has a docstring; every architectural decision is documented in `plan.md`.

---

## 7. Risks & Open Questions

### 7.1 Known risks

- **Pre-fetch cache key complexity**: a 4-tuple `(alias, key_col, key_value, value_col)` is right but verbose. Plan documents the data structure and access pattern.
- **CIF self-healing creates a new TriggerRecord**: the caller (orchestrator) MUST use `result.healed_trigger` for subsequent stages, not the original. This is a contract that must be documented and tested. If the orchestrator forgets, downstream code sees `cif=None` and fails confusingly.
- **Logging PII**: easy to leak if developers add helpful debug logs. Plan §X documents the rule: "log field names, never field values."
- **`as400:<alias>` source type stub**: tests must explicitly cover it raising; otherwise a future contributor might assume it works and ship broken config to production.

### 7.2 Open questions (resolved in plan.md)

- For `csv:<alias>` lookup, what is the "lookup key value"? **Plan**: `trigger.cif` (the canonical join key in REBIRTH §6 examples). If a future field needs to lookup by something else, we add `SourceConfig.lookup_key_value_from: str` (`"trigger.cif"`, `"trigger.shortname"`, etc.) — out of scope here.
- Should `validate_field_resolvability` exist now (for doctor command)? **Plan**: NO. The doctor command can call `resolve` with a sample document and catch errors. If profile shows that's slow, we add the explicit method later.
- Should we support per-field validation override on `default_value`? **Plan**: NO. Default uses the first source's validation. Documented in REQ-019.

---

## 8. Verification Strategy

| REQ block | Verification |
|-----------|--------------|
| REQ-001..008 (types) | unit tests asserting class existence + frozen-ness |
| REQ-009..014 (constructor + pre-fetch) | tests covering pre-fetch on/off + missing alias raises |
| REQ-015..022 (resolution flow) | acceptance scenarios 4.1..4.7 |
| REQ-023..026 (dispatch) | one test per source type + as400 NotImplementedError |
| REQ-027..029 (aliases) | scenario 4.7 + 4.8 |
| REQ-030..035 (tests + coverage) | suite passing + cov report |
| REQ-036..038 (tooling) | ruff/mypy/pre-commit on staged files |
| Scenario 4.9 (pre-fetch reduces calls) | counter-mock or get_all assertion |
| Scenario 4.11 (no PII) | grep |

---

## 9. Cross-References

- Predecessor changes: 002, 003, 004
- Constitution Principles I, III, V, VI, VII, VIII, IX
- REBIRTH §6 (entire section), §10.1 (S3 stage), §12 (config metadata block)
- Plan: `specs/005-metadata-service/plan.md`
- Tasks: `specs/005-metadata-service/tasks.md`

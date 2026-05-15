# Plan — 005-metadata-service

**Status**: Draft (under review)
**Created**: 2026-05-10
**Spec reference**: `specs/005-metadata-service/spec.md`

> The **how** of this change. Most complex service in CMCourier so far. Tasks live in `tasks.md`.

---

## 1. Approach Summary

A single class `MetadataService` at `src/cmcourier/services/metadata.py` (~250 LOC) backed by five frozen dataclasses (`MetadataConfig`, `FieldSourceConfig`, `SourceConfig`, `ValidationConfig`, `MetadataResolution`). Source dispatch via a dict of handlers. Pre-fetching at construction for `csv:<alias>` sources. CIF self-healing returns a new `TriggerRecord` (the input is frozen).

Test file uses real `TabularDataSource` instances over CSV fixtures (one per data source type — `clients.csv`, `accounts.csv`, `cards.csv` — synthetic data).

---

## 2. File Layout

```
src/cmcourier/services/
├── __init__.py            # MODIFIED: re-export 6 new public symbols
└── metadata.py            # NEW (~250 LOC)

tests/unit/services/
└── test_metadata.py       # NEW (~400 LOC; ~22 tests)

tests/fixtures/services/metadata/   # NEW directory
├── clients.csv            # CIF + Nombre_Cliente, ~5 rows
├── accounts.csv           # CIF + Num_Cuenta, ~5 rows
└── cards.csv              # CIF + Num_Cuenta_Tarjeta, ~5 rows
```

No new dependencies. `re` and `logging` are stdlib.

---

## 3. Architectural Decisions

### 3.1 Dataclass hierarchy (config types)

All five public dataclasses (`MetadataResolution`, `MetadataConfig`, `FieldSourceConfig`, `SourceConfig`, `ValidationConfig`) are `frozen=True, slots=True`. This matches the project pattern (002, 004) and makes immutability of resolution results trivial.

```python
@dataclass(frozen=True, slots=True)
class ValidationConfig:
    allowed_pattern: str | None = None  # full-match regex; None = no validation

@dataclass(frozen=True, slots=True)
class SourceConfig:
    source_type: str
    lookup_value_column: str
    lookup_key_column: str | None = None
    validation: ValidationConfig | None = None

@dataclass(frozen=True, slots=True)
class FieldSourceConfig:
    sources: tuple[SourceConfig, ...]
    default_value: str | None = None

@dataclass(frozen=True, slots=True)
class MetadataConfig:
    field_aliases: Mapping[str, str]
    field_sources: Mapping[str, FieldSourceConfig]
    prefetch_enabled: bool = True

@dataclass(frozen=True, slots=True)
class MetadataResolution:
    metadata: ResolvedMetadata
    healed_trigger: TriggerRecord
```

### 3.2 Source dispatch via dict-of-handlers

```python
class MetadataService:
    def __init__(self, ...) -> None:
        ...
        self._exact_handlers: dict[str, _FetchFn] = {
            "trigger": self._fetch_trigger,
            "rvabrep": self._fetch_rvabrep,
        }
        # csv:<alias> matched by prefix; as400:<alias> raises NotImplementedError
```

`_FetchFn` is a typed callable signature — a `Protocol` would be cleaner, but a `Callable[[SourceConfig, TriggerRecord, RVABREPDocument], str | None]` type alias is enough.

The dispatch logic in `_fetch_from_source(source_config, trigger, document) -> str | None`:

1. If `source_type` is in `_exact_handlers`, call it.
2. Else if it starts with `"csv:"`, extract alias and call `_fetch_csv(alias, source_config, trigger, document)`.
3. Else if it starts with `"as400:"`, raise `NotImplementedError("as400 adapter not yet shipped; this source type will be enabled when the AS400 adapter change ships.")`.
4. Else raise `ConfigurationError("unknown source_type", source_type=source_type)`.

### 3.3 Pre-fetching strategy

The pre-fetch cache is keyed by `(alias, key_column, key_value, value_column)`:

```python
self._csv_cache: dict[tuple[str, str, str, str], str] = {}
```

Why this shape: a single `clients.csv` may be queried for `(CIF=X) → Nombre_Cliente` and `(CIF=X) → Tipo_Cliente`. Both lookups should hit the same cache.

Population at construction (when `prefetch_enabled=True`):

```python
for canonical_field, fsc in config.field_sources.items():
    for sc in fsc.sources:
        if sc.source_type.startswith("csv:"):
            alias = sc.source_type.split(":", 1)[1]
            if alias not in sources_registry:
                raise ConfigurationError("unknown CSV alias", alias=alias)
            if (alias, sc.lookup_key_column, sc.lookup_value_column) in seen:
                continue
            seen.add(...)
            for row in sources_registry[alias].get_all():
                key_value = row.get(sc.lookup_key_column)
                value = row.get(sc.lookup_value_column)
                if key_value is not None and value is not None:
                    cache_key = (alias, sc.lookup_key_column, str(key_value), sc.lookup_value_column)
                    cache.setdefault(cache_key, str(value))  # first wins (no overwrite)
```

`setdefault` (instead of `cache[k] = v`) means the **first** row wins on duplicate keys, matching the precedent of `MappingService`.

If `prefetch_enabled=False`, the cache stays empty and `_fetch_csv` falls back to `source.get_by_fields(...)` per call.

### 3.4 CIF self-healing — return new TriggerRecord

The frozen dataclass cannot be mutated. We construct a new one when self-healing applies:

```python
def resolve(self, trigger, document, mapping) -> MetadataResolution:
    canonical_fields = self._normalize_fields(mapping.required_metadata_fields)
    resolved: dict[str, str] = {}

    # CIF self-healing
    if trigger.cif is None and "BAC_CIF" in canonical_fields:
        cif_value = self._resolve_one("BAC_CIF", trigger, document)
        trigger = TriggerRecord(
            shortname=trigger.shortname,
            cif=cif_value,
            system_id=trigger.system_id,
        )
        resolved["BAC_CIF"] = cif_value

    for field in canonical_fields:
        if field in resolved:
            continue
        resolved[field] = self._resolve_one(field, trigger, document)

    return MetadataResolution(
        metadata=ResolvedMetadata.from_dict(resolved),
        healed_trigger=trigger,
    )
```

Note the order: self-healing happens BEFORE the main loop so subsequent CSV lookups (which use `trigger.cif` as the lookup key value) see the resolved CIF.

### 3.5 `_resolve_one` — the per-field fallback chain

```python
def _resolve_one(self, canonical_field, trigger, document) -> str:
    if canonical_field not in self._config.field_sources:
        raise ConfigurationError("no field_sources config for field", field=canonical_field)

    fsc = self._config.field_sources[canonical_field]
    first_validation: ValidationConfig | None = (
        fsc.sources[0].validation if fsc.sources else None
    )

    for sc in fsc.sources:
        try:
            value = self._fetch_from_source(sc, trigger, document)
        except NotImplementedError:
            raise  # propagate as400 stubs cleanly
        if value is None or value == "":
            continue
        if sc.validation and not self._validates(value, sc.validation):
            continue
        return value

    # All sources exhausted; try default
    if fsc.default_value is None:
        raise SourceFailedError(field_name=canonical_field, source="<all>")

    if first_validation and not self._validates(fsc.default_value, first_validation):
        raise DefaultValidationFailedError(
            field_name=canonical_field,
            default_value=fsc.default_value,
        )

    return fsc.default_value
```

50-line cap holds — this is ~25 lines.

### 3.6 Field alias normalization

```python
def _normalize_fields(self, raw_fields: tuple[str, ...]) -> list[str]:
    """Map raw field names from Modelo Documental to canonical BAC_* names."""
    canonical = []
    aliases_lower = {k.lower(): v for k, v in self._config.field_aliases.items()}
    for raw in raw_fields:
        if raw in self._config.field_sources:
            canonical.append(raw)  # already canonical
        elif raw.lower() in aliases_lower:
            canonical.append(aliases_lower[raw.lower()])
        else:
            raise ConfigurationError(
                "unknown field (no alias and no field_sources entry)",
                field=raw,
            )
    return canonical
```

Case-insensitive lookup via lowercase keys. Canonical-already check first (per REQ-028).

### 3.7 Logging discipline (Constitution Principle VIII)

- Log field NAMES, never field VALUES. The customer's name, account, and CIF VALUE are PII; the field NAME (`"BAC_Nombre_Cliente"`) is not.
- Resolution success → DEBUG. Operationally noisy at INFO; only investigators need this detail.
- Source-skip-due-to-validation → DEBUG with field name + source identifier (NOT the rejected value).
- All-sources-failed → WARNING with field name + list of source identifiers.
- Default validation failed → ERROR (raised exception captures full context).

The masking helper (`cli/ui/logging.py`, forthcoming) will sit in front of the structured logger. For now, the service emits no logs that contain PII values, so even default Python stderr is safe.

### 3.8 `ResolvedMetadata` keys are canonical (`BAC_*`), not aliases

The cache returned in `MetadataResolution.metadata` has keys like `BAC_CIF`, `BAC_Nombre_Cliente` — never `CIF` or `Nombre_Cliente`. This is the format the CMIS uploader expects (the spec: `clbNonGroup.BAC_*`); the upload adapter trivially prefixes `clbNonGroup.` to produce the property catalog.

### 3.9 `_validates` helper

```python
def _validates(self, value: str, validation: ValidationConfig) -> bool:
    if validation.allowed_pattern is None:
        return True
    return re.fullmatch(validation.allowed_pattern, value) is not None
```

`re.fullmatch` (not `re.match`) ensures the entire string matches, per REQ-006.

### 3.10 Error vocabulary

The change uses three exception types from `cmcourier.domain.exceptions`:

- `ConfigurationError` — bad config (unknown alias, unknown field, unknown source_type, missing CSV alias in registry, unknown attribute on trigger/rvabrep)
- `SourceFailedError(field_name, source)` — all sources exhausted, no default, OR default is None
- `DefaultValidationFailedError(field_name, default_value)` — sources exhausted, default failed validation

Note: `SourceFailedError` is reused for "all sources" — context says `source="<all>"`. The service doesn't add a new exception type; it uses what 002 defined.

### 3.11 What about `as400:<alias>`?

The dispatch raises `NotImplementedError`. Tests assert the message names `"as400 adapter"` so a future contributor knows where the missing piece is.

When the AS400 adapter ships in a later change, that change adds a new entry to the dispatch (`self._exact_handlers["as400"] = self._fetch_as400`) — and updates the as400 prefix branch — without touching anything else here.

---

## 4. Implementation Sketch (full)

```python
"""Metadata resolution service - the spec.

Per-field source fallback chain with validation regexes, default-value
fallback, CIF self-healing, field alias normalization, and eager pre-fetching
of csv:<alias> sources at construction. Stage S3 of every pipeline depends
on this service.

Constitution Principle I: imports only cmcourier.domain.* and stdlib.
Principle VIII: never log resolved field VALUES (PII); log field NAMES only.
"""

from __future__ import annotations

__all__ = [
    "FieldSourceConfig",
    "MetadataConfig",
    "MetadataResolution",
    "MetadataService",
    "SourceConfig",
    "ValidationConfig",
]

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from cmcourier.domain.exceptions import (
    ConfigurationError,
    DefaultValidationFailedError,
    SourceFailedError,
)
from cmcourier.domain.models import (
    CMMapping,
    ResolvedMetadata,
    RVABREPDocument,
    TriggerRecord,
)
from cmcourier.domain.ports import IDataSource

_logger = logging.getLogger(__name__)

# ... (all five dataclasses as in §3.1)

_FetchFn = Callable[
    ["MetadataService", "SourceConfig", TriggerRecord, RVABREPDocument],
    "str | None",
]

_CSV_PREFIX = "csv:"
_AS400_PREFIX = "as400:"


class MetadataService:
    """the spec metadata resolution. See plan.md for detailed flow."""

    def __init__(
        self,
        config: MetadataConfig,
        sources_registry: Mapping[str, IDataSource],
    ) -> None:
        self._config = config
        self._sources_registry = sources_registry
        self._csv_cache: dict[tuple[str, str, str, str], str] = {}
        if config.prefetch_enabled:
            self._prefetch_csv_sources()

    def _prefetch_csv_sources(self) -> None:
        """Iterate every csv:<alias> source in config and pre-load into cache."""
        seen_pairs: set[tuple[str, str, str]] = set()
        for fsc in self._config.field_sources.values():
            for sc in fsc.sources:
                if not sc.source_type.startswith(_CSV_PREFIX):
                    continue
                alias = sc.source_type[len(_CSV_PREFIX):]
                if alias not in self._sources_registry:
                    raise ConfigurationError("unknown CSV alias", alias=alias)
                if sc.lookup_key_column is None:
                    raise ConfigurationError(
                        "csv source requires lookup_key_column",
                        source_type=sc.source_type,
                    )
                pair_key = (alias, sc.lookup_key_column, sc.lookup_value_column)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                for row in self._sources_registry[alias].get_all():
                    key = row.get(sc.lookup_key_column)
                    val = row.get(sc.lookup_value_column)
                    if key is None or val is None:
                        continue
                    cache_key = (alias, sc.lookup_key_column, str(key), sc.lookup_value_column)
                    self._csv_cache.setdefault(cache_key, str(val))

    def resolve(
        self,
        trigger: TriggerRecord,
        document: RVABREPDocument,
        mapping: CMMapping,
    ) -> MetadataResolution:
        canonical_fields = self._normalize_fields(mapping.required_metadata_fields)
        resolved: dict[str, str] = {}

        if trigger.cif is None and "BAC_CIF" in canonical_fields:
            cif_value = self._resolve_one("BAC_CIF", trigger, document)
            trigger = TriggerRecord(
                shortname=trigger.shortname,
                cif=cif_value,
                system_id=trigger.system_id,
            )
            resolved["BAC_CIF"] = cif_value

        for field in canonical_fields:
            if field in resolved:
                continue
            resolved[field] = self._resolve_one(field, trigger, document)

        return MetadataResolution(
            metadata=ResolvedMetadata.from_dict(resolved),
            healed_trigger=trigger,
        )

    # ... _normalize_fields, _resolve_one, _fetch_from_source,
    # ... _fetch_trigger, _fetch_rvabrep, _fetch_csv, _validates
    # All as documented in §3.x above.
```

Total estimated LOC: ~250 (including dataclasses, docstrings, helpers).

---

## 5. Test Strategy

### 5.1 Fixtures

Three CSV files under `tests/fixtures/services/metadata/`:

`clients.csv`:
```
CIF,Nombre_Cliente,Tipo_Cliente
123456,JUAN PEREZ TEST,INDIVIDUAL
234567,MARIA GOMEZ TEST,INDIVIDUAL
345678,EMPRESA SA TEST,CORPORATE
```

`accounts.csv`:
```
CIF,Num_Cuenta
123456,1234567890
234567,2345678901
```

`cards.csv`:
```
CIF,Num_Cuenta_Tarjeta
123456,4111111111111111
345678,4222222222222222
```

All synthetic. No real CIFs, no real names.

### 5.2 Test class shape

```python
@pytest.mark.unit
class TestMetadataService:
    @pytest.fixture
    def sources_registry(self): ...   # builds dict of TabularDataSource

    @pytest.fixture
    def basic_config(self): ...   # a MetadataConfig with the typical fields

    @pytest.fixture
    def service(self, basic_config, sources_registry): ...

    # Construction + pre-fetch
    def test_pre_fetch_loads_at_construction(...): ...
    def test_missing_csv_alias_raises(...): ...
    def test_prefetch_disabled_uses_get_by_fields_per_call(...): ...

    # Vanilla resolution
    def test_trigger_source(...): ...
    def test_rvabrep_source(...): ...
    def test_csv_source(...): ...

    # Fallback chain
    def test_first_source_fails_validation_second_succeeds(...): ...
    def test_first_source_returns_none_second_succeeds(...): ...
    def test_all_sources_fail_default_used(...): ...
    def test_all_sources_fail_no_default_raises(...): ...
    def test_default_validation_fails_raises(...): ...

    # CIF self-healing
    def test_cif_self_healing_happy_path(...): ...
    def test_cif_self_healing_failure_propagates(...): ...
    def test_no_self_healing_when_cif_present(...): ...
    def test_self_healed_cif_used_for_subsequent_csv_lookups(...): ...

    # Aliases
    def test_alias_normalization_case_insensitive(...): ...
    def test_canonical_already_used_directly(...): ...
    def test_unknown_field_raises(...): ...

    # Source dispatch
    def test_as400_source_raises_not_implemented(...): ...
    def test_unknown_source_type_raises_configuration(...): ...
    def test_csv_source_missing_alias_in_registry_raises(...): ...

    # Type immutability
    def test_metadata_resolution_is_frozen(...): ...
    def test_metadata_config_is_frozen(...): ...
```

~22 tests total.

### 5.3 Pre-fetch counter test (Scenario 4.9)

Wraps a `TabularDataSource` in a `_CountingSource` that delegates but counts `get_all` and `get_by_fields` invocations:

```python
class _CountingSource(IDataSource):
    def __init__(self, inner): self.inner = inner; self.get_all_calls = 0; self.get_by_fields_calls = 0
    def get_all(self):
        self.get_all_calls += 1
        yield from self.inner.get_all()
    def get_by_fields(self, filters):
        self.get_by_fields_calls += 1
        return self.inner.get_by_fields(filters)
    # ... other IDataSource methods delegate
```

This is the one place where a "wrapper" (not a mock) is justified — we want to measure behavior, not stub it.

### 5.4 Coverage target

≥ 95% branch on `src/cmcourier/services/metadata.py`. Achievable because every branch (each source type, each fallback step, each CIF-healing path) is reachable from a fixture-driven test.

---

## 6. CHANGELOG entry shape

```markdown
## [0.7.0] — 2026-05-XX

### Added
- `cmcourier.services.metadata.MetadataService`: per-field metadata resolution with fallback chain, validation regexes, default-value fallback, CIF self-healing, field-alias normalization, and eager pre-fetching of CSV sources at construction. Stage S3 of every pipeline depends on this service.
- `MetadataConfig`, `FieldSourceConfig`, `SourceConfig`, `ValidationConfig`, `MetadataResolution`: five frozen+slots dataclasses for the configuration and result shapes.
- 22 unit tests using real `TabularDataSource` instances over CSV fixtures (`clients.csv`, `accounts.csv`, `cards.csv`).
- Pre-fetch cache keyed by `(alias, key_column, key_value, value_column)` for shared cache across multiple fields per source.

### Out of scope (deferred)
- AS400 source resolution. `as400:<alias>` raises `NotImplementedError` until the AS400 adapter ships.
- TTL-based cache invalidation, prefetch row-count guard, prefetch exclude list. Not relevant for CSV; documented as post-MVP for AS400 in `docs/roadmap/POST-MVP.md`.

### Rationale
- Most complex service in CMCourier so far; engine of stage S3.
- CIF self-healing returns a new `TriggerRecord` (the input is frozen). Callers (orchestrators) MUST use `result.healed_trigger` for subsequent stages — documented in spec REQ-021 and risks §7.1.
- Pre-fetching at construction is included in this change (not deferred) because it is performance-critical and central to the architecture, even if the dev/test workload doesn't exercise it.
```

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Resolved values leak to logs (PII) | Strict policy: log field NAMES only (§3.7). Code review checklist. Future masking helper in cli/ui/logging.py. |
| `healed_trigger` ignored by orchestrator | Tests assert behavior; orchestrator change (later) explicitly threads `healed_trigger` forward. Documented in CONTRIBUTING.md when the orchestrator change ships. |
| Pre-fetch builds a large dict | CSV sources are tiny in practice (<1000 rows). AS400 sources (when they ship) will need the prefetch_max_rows guard — post-MVP. |
| `as400:<alias>` accidentally configured | Tests assert NotImplementedError fires with a clear message. Doctor command (later) will surface this in pre-flight. |
| Pre-fetch first-wins vs caller expectation | `setdefault` preserves first occurrence, matching MappingService's first-wins precedent. Documented. |
| Re-running with different config across sessions yields different cache | Acceptable — the service is ephemeral per-process; no persistence concerns. |

---

## 8. Phases (mirrored in `tasks.md`)

1. Fixtures (`clients.csv`, `accounts.csv`, `cards.csv`)
2. Tests (RED)
3. Dataclasses + helpers (`_validates`, `_normalize_fields`, `_fetch_*`)
4. `MetadataService` class (`__init__`, `_prefetch_csv_sources`, `resolve`, `_resolve_one`)
5. Re-exports + verification
6. Docs + commit

---

## 9. Cross-References

- Spec: `specs/005-metadata-service/spec.md`
- Tasks: `specs/005-metadata-service/tasks.md`
- Constitution Principles I, III, V, VI, VII, VIII, IX
- the spec (entire), §10.1 (S3), §12 (config layout)
- Predecessors: 002, 003, 004

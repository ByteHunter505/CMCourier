# Plan — 006-trigger-service

**Status**: Draft (under review)
**Created**: 2026-05-10
**Spec reference**: `specs/006-trigger-service/spec.md`

> The **how** of this change. Tasks live in `tasks.md`.

---

## 1. Approach Summary

Three small classes (one CSV strategy, one RVABREP strategy, two stubs) split into four files under `src/cmcourier/services/triggers/`. Each strategy is < 100 LOC. Tests use real `TabularDataSource` instances over fixture CSVs (consistent with 004 / 005). No new dependencies.

The strategies are the service surface — there is no `TriggerService` wrapper class. Orchestrators (future changes) instantiate the appropriate strategy directly per pipeline.

---

## 2. File Layout

```
src/cmcourier/services/triggers/
├── __init__.py            # NEW: re-exports
├── csv.py                 # NEW: CsvTriggerStrategy + CsvTriggerColumnsConfig (~80 LOC)
├── direct_rvabrep.py      # NEW: DirectRvabrepTriggerStrategy + RvabrepColumnsConfig + RvabrepFilters (~120 LOC)
└── stubs.py               # NEW: As400TriggerStrategy + LocalScanTriggerStrategy (~50 LOC)

src/cmcourier/services/__init__.py    # MODIFIED: re-export 7 new public symbols

tests/unit/services/
└── test_trigger_strategies.py  # NEW (~400 LOC; ~18 tests)

tests/fixtures/services/triggers/
├── trigger_list.csv             # ShortName, CIF, SystemID; ~5 rows
├── trigger_list_alt_columns.csv # same data, columns Cliente/Doc/Sistema
├── trigger_list_missing_col.csv # missing ShortName column (for the error test)
└── rvabrep_export.csv           # RVABREP-shaped; ~10 rows for dedup + filter tests
```

No changes to `pyproject.toml`. No new deps.

---

## 3. Architectural Decisions

### 3.1 Strategies-only, no `TriggerService` wrapper

The `S0Strategy` port already represents "the trigger service" abstraction. Adding a wrapper class around strategies would:
- Add an indirection without behavior
- Break the `S0Strategy` port contract (the wrapper would have a different signature)
- Repeat the strategy's API one-to-one

Decision: orchestrators receive a `S0Strategy` directly. No wrapper.

### 3.2 One file per strategy (plus `stubs.py`)

Three real candidates — keeping each in its own file makes diffs cleaner when one strategy changes (e.g., when the AS400 adapter ships and `As400TriggerStrategy` gets a real implementation). Stubs share `stubs.py` because they're trivial.

### 3.3 `source_descriptor` is silently ignored

The `S0Strategy.acquire(source_descriptor: str)` port signature requires the parameter. Each strategy ignores it (sets `source_descriptor: str = ""` default). Rationale:

- The strategy is fully configured by its constructor (CSV source, filters, columns).
- A non-empty descriptor passed today has no meaningful interpretation; raising would break future callers if the port refines without descriptor.
- Tests assert that a non-empty descriptor is silently ignored.

A constitutional amendment to refine the port (drop the parameter) is out of scope.

### 3.4 CIF defaulting to `None`

`TriggerRecord.cif: str | None`. Per REBIRTH §6.5, `None` is the sentinel for "needs CIF self-healing in stage S3". Strategies extract the cell value if non-blank, otherwise yield `None`. The blank-vs-`None` distinction is irrelevant downstream — anything falsy means "self-heal".

### 3.5 RVABREP filter combination

When both `RvabrepFilters.systems` and `.document_types` are set, the strategy:

1. Picks the smaller filter (by tuple length) for the SQL query (via `get_by_fields_in`).
2. Filters the other in Python during iteration.

This keeps the IDataSource API simple (it doesn't support compound IN/IN queries cleanly) while still being efficient when one filter is much more selective.

If profiling later shows this is slow for AS400, an optimization is to issue two `get_by_fields_in` calls and compute set intersection in memory. Out of scope here.

### 3.6 Deduplication for RVABREP

Each `(shortname, system_id)` pair yields exactly one trigger. Dedup is in-memory `set[tuple[str, str]]` — small (max ~tens of thousands) so memory is fine. First-occurrence wins, matching the REBIRTH §4.3 / MappingService precedent.

### 3.7 Stubs raise at `acquire`, not construction

The constructor accepts arguments (e.g., the SQL query for AS400, the path for local-scan) so the orchestrator can build them without tripping. The `acquire()` call is what fails, with a message that names the missing infrastructure. This pattern is consistent with `as400:<alias>` in 005.

### 3.8 Logging discipline (Constitution Principle VIII)

The strategies MAY log:
- `INFO` with the count of skipped rows (blank shortname / system_id) at end of iteration — operational, not PII.
- `DEBUG` with `shortname` and `system_id` per yielded trigger (operational identifiers).

The strategies MUST NOT log `cif` values. CIF is PII. If a future maintainer adds a log statement involving `cif`, code review must catch it.

### 3.9 Lazy iteration

Every strategy yields via generator. Trigger lists may be very large (REBIRTH §10.4 mentions 200k+). The current `IDataSource.get_all()` from `TabularDataSource` (003) is technically eager (whole DataFrame in memory) but the iteration over it is lazy via generator semantics. The contract is preserved at the strategy level.

---

## 4. Implementation Sketches

### 4.1 `csv.py`

```python
"""CSV-driven trigger strategy. REBIRTH §5.1 mode csv:<alias>."""

from __future__ import annotations

__all__ = ["CsvTriggerColumnsConfig", "CsvTriggerStrategy"]

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.models import TriggerRecord
from cmcourier.domain.ports import IDataSource, S0Strategy

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CsvTriggerColumnsConfig:
    col_shortname: str = "ShortName"
    col_cif: str = "CIF"
    col_system_id: str = "SystemID"


def _is_blank(v: object) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


class CsvTriggerStrategy(S0Strategy):
    """Reads triggers from any tabular IDataSource (CSV, XLSX, etc.)."""

    def __init__(
        self,
        source: IDataSource,
        columns: CsvTriggerColumnsConfig | None = None,
    ) -> None:
        self._source = source
        self._columns = columns or CsvTriggerColumnsConfig()

    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]:
        del source_descriptor  # vestigial; see plan §3.3
        skipped = 0
        validated = False
        for row in self._source.get_all():
            if not validated:
                self._validate_columns(row)
                validated = True
            shortname_raw = row.get(self._columns.col_shortname)
            system_raw = row.get(self._columns.col_system_id)
            if _is_blank(shortname_raw) or _is_blank(system_raw):
                skipped += 1
                continue
            cif_raw = row.get(self._columns.col_cif)
            yield TriggerRecord(
                shortname=str(shortname_raw).strip(),
                cif=None if _is_blank(cif_raw) else str(cif_raw).strip(),
                system_id=str(system_raw).strip(),
            )
        if skipped:
            _logger.info("skipped %d blank trigger row(s)", skipped)

    def _validate_columns(self, row: dict[str, object]) -> None:
        for col in (self._columns.col_shortname, self._columns.col_system_id):
            if col not in row:
                raise ConfigurationError(
                    "Trigger CSV missing required column",
                    missing_column=col,
                )
        # col_cif is OPTIONAL — its absence means every yielded TriggerRecord has cif=None
```

### 4.2 `direct_rvabrep.py`

```python
"""Direct-RVABREP trigger strategy. REBIRTH §5.1 mode direct_rvabrep."""

from __future__ import annotations

__all__ = [
    "DirectRvabrepTriggerStrategy",
    "RvabrepColumnsConfig",
    "RvabrepFilters",
]

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.models import TriggerRecord
from cmcourier.domain.ports import IDataSource, S0Strategy

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RvabrepColumnsConfig:
    col_shortname: str = "ABABCD"  # index1
    col_cif: str = "ABACCD"        # index2
    col_system_id: str = "ABAACD"  # system_code
    col_id_rvi: str = "ABAHCD"     # index7 (document type)


@dataclass(frozen=True, slots=True)
class RvabrepFilters:
    systems: tuple[str, ...] = ()
    document_types: tuple[str, ...] = ()


def _is_blank(v: object) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


class DirectRvabrepTriggerStrategy(S0Strategy):
    """Discovers triggers by scanning RVABREP itself, optionally filtered."""

    def __init__(
        self,
        rvabrep_source: IDataSource,
        filters: RvabrepFilters | None = None,
        columns: RvabrepColumnsConfig | None = None,
    ) -> None:
        self._source = rvabrep_source
        self._filters = filters or RvabrepFilters()
        self._columns = columns or RvabrepColumnsConfig()

    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]:
        del source_descriptor
        seen: set[tuple[str, str]] = set()
        skipped = 0
        for row in self._iter_filtered_rows():
            shortname_raw = row.get(self._columns.col_shortname)
            system_raw = row.get(self._columns.col_system_id)
            if _is_blank(shortname_raw) or _is_blank(system_raw):
                skipped += 1
                continue
            shortname = str(shortname_raw).strip()
            system_id = str(system_raw).strip()
            key = (shortname, system_id)
            if key in seen:
                continue
            seen.add(key)
            cif_raw = row.get(self._columns.col_cif)
            yield TriggerRecord(
                shortname=shortname,
                cif=None if _is_blank(cif_raw) else str(cif_raw).strip(),
                system_id=system_id,
            )
        if skipped:
            _logger.info("skipped %d malformed RVABREP row(s)", skipped)

    def _iter_filtered_rows(self) -> Iterator[dict[str, object]]:
        f = self._filters
        if not f.systems and not f.document_types:
            yield from self._source.get_all()
            return
        # Pick the smaller filter for the IN query; reject the other in Python.
        if f.document_types and (not f.systems or len(f.document_types) <= len(f.systems)):
            primary_field, primary_values = self._columns.col_id_rvi, list(f.document_types)
            secondary_field, secondary_values = self._columns.col_system_id, set(f.systems)
        else:
            primary_field, primary_values = self._columns.col_system_id, list(f.systems)
            secondary_field, secondary_values = self._columns.col_id_rvi, set(f.document_types)
        rows = self._source.get_by_fields_in(
            field=primary_field,
            values=primary_values,
            fixed_filters={},
        )
        for row in rows:
            if secondary_values:
                v = row.get(secondary_field)
                if v is None or str(v) not in secondary_values:
                    continue
            yield row
```

### 4.3 `stubs.py`

```python
"""Trigger strategies that depend on infrastructure not yet shipped."""

from __future__ import annotations

__all__ = ["As400TriggerStrategy", "LocalScanTriggerStrategy"]

from collections.abc import Iterator
from pathlib import Path

from cmcourier.domain.models import TriggerRecord
from cmcourier.domain.ports import IDataSource, S0Strategy


class As400TriggerStrategy(S0Strategy):
    """REBIRTH §5.1 mode as400:<alias>. Activates when the AS400 adapter ships."""

    def __init__(self, query: str) -> None:
        self._query = query

    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]:
        del source_descriptor
        raise NotImplementedError(
            "AS400 adapter not yet shipped; this strategy will activate "
            "when that adapter change merges."
        )
        yield  # pragma: no cover - keeps the function a generator


class LocalScanTriggerStrategy(S0Strategy):
    """REBIRTH §5.1 mode local_scan. Activates when the folder-scanner module ships."""

    def __init__(
        self,
        scan_path: Path,
        cif_lookup_source: IDataSource | None = None,
    ) -> None:
        self._scan_path = scan_path
        self._cif_lookup_source = cif_lookup_source

    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]:
        del source_descriptor
        raise NotImplementedError(
            "local-scan strategy not yet shipped; depends on a forthcoming "
            "folder-scanner module."
        )
        yield  # pragma: no cover - keeps the function a generator
```

### 4.4 `__init__.py`

```python
"""Concrete S0Strategy implementations for stage S0 (Trigger Acquisition)."""

from __future__ import annotations

__all__ = [
    "As400TriggerStrategy",
    "CsvTriggerColumnsConfig",
    "CsvTriggerStrategy",
    "DirectRvabrepTriggerStrategy",
    "LocalScanTriggerStrategy",
    "RvabrepColumnsConfig",
    "RvabrepFilters",
]

from cmcourier.services.triggers.csv import (
    CsvTriggerColumnsConfig,
    CsvTriggerStrategy,
)
from cmcourier.services.triggers.direct_rvabrep import (
    DirectRvabrepTriggerStrategy,
    RvabrepColumnsConfig,
    RvabrepFilters,
)
from cmcourier.services.triggers.stubs import (
    As400TriggerStrategy,
    LocalScanTriggerStrategy,
)
```

`services/__init__.py` re-exports the same set.

---

## 5. Test Strategy

### 5.1 Fixtures

`trigger_list.csv`:
```csv
ShortName,CIF,SystemID
JUANPEREZ01,123456,1
MARIAGOMEZ02,234567,5
PEPELOPEZ03,,1
EMPRESA04,345678,2
,123456,1
```
(5 rows; one with empty CIF; one with blank ShortName for skip test)

`trigger_list_alt_columns.csv`:
```csv
Cliente,Doc,Sistema
JUANPEREZ01,123456,1
```

`trigger_list_missing_col.csv`:
```csv
CIF,SystemID
123456,1
```
(missing ShortName column)

`rvabrep_export.csv` (RVABREP-shaped, ~10 rows):
```csv
ABABCD,ABACCD,ABAACD,ABAHCD
JUANPEREZ01,123456,1,FF17
JUANPEREZ01,123456,1,AA01
MARIAGOMEZ02,234567,5,FF17
PEPELOPEZ03,,1,BB02
EMPRESA04,345678,2,FF17
JUANPEREZ01,123456,1,FF17
,234567,5,FF17
JUANPEREZ01,123456,1,CC03
```
(8 rows; 4 unique `(shortname, system_id)` pairs after dedup; mix of `id_rvi` for filter tests; one row with blank ShortName to test skip)

### 5.2 Test class shape

```python
@pytest.mark.unit
class TestCsvTriggerStrategy:
    def test_yields_records(self): ...
    def test_yields_cif_none_when_blank(self): ...
    def test_blank_rows_skipped(self): ...
    def test_custom_columns(self): ...
    def test_missing_required_column_raises(self): ...
    def test_source_descriptor_ignored(self): ...
    def test_is_s0strategy(self): ...

class TestDirectRvabrepTriggerStrategy:
    def test_no_filters_yields_unique_pairs(self): ...
    def test_filter_by_systems(self): ...
    def test_filter_by_document_types(self): ...
    def test_filter_by_both(self): ...
    def test_blank_rows_skipped(self): ...
    def test_cif_none_when_blank(self): ...
    def test_source_descriptor_ignored(self): ...
    def test_is_s0strategy(self): ...

class TestStubStrategies:
    def test_as400_construction_succeeds(self): ...
    def test_as400_acquire_raises(self): ...
    def test_local_scan_construction_succeeds(self): ...
    def test_local_scan_acquire_raises(self): ...
    def test_both_are_s0strategies(self): ...
```

~18-20 tests total.

### 5.3 Coverage target

≥ 95% branch on `src/cmcourier/services/triggers/` (combined). Achievable because each module is small.

---

## 6. CHANGELOG entry shape

```markdown
## [0.8.0] — 2026-05-XX

### Added

- `cmcourier.services.triggers.csv.CsvTriggerStrategy` — concrete `S0Strategy` over any tabular `IDataSource`. Validates required columns at first row; yields `TriggerRecord` per non-blank row; treats blank `CIF` as `None` (CIF self-healing in stage S3 covers it).
- `cmcourier.services.triggers.direct_rvabrep.DirectRvabrepTriggerStrategy` — concrete `S0Strategy` that scans RVABREP itself, with optional `RvabrepFilters(systems, document_types)`. Deduplicates `(shortname, system_id)` pairs (first occurrence wins).
- `cmcourier.services.triggers.stubs.{As400TriggerStrategy, LocalScanTriggerStrategy}` — concrete `S0Strategy` placeholders that raise `NotImplementedError` at `acquire()` (not construction) with messages naming the missing dependency.
- 3 frozen+slots config dataclasses: `CsvTriggerColumnsConfig`, `RvabrepColumnsConfig`, `RvabrepFilters`.
- 18 unit tests in `tests/unit/services/test_trigger_strategies.py`.
- 4 fixture CSVs under `tests/fixtures/services/triggers/`.

### Rationale

- Stage S0 (Trigger Acquisition) is the entry point of every pipeline. With S0 unimplemented, no orchestrator can run end-to-end. This change ships the two real strategies needed for the MVP pipelines (`rvabrep-pipeline`, `csv-trigger-pipeline`) and gates the other two with explicit stubs.
- No `TriggerService` wrapper class. The `S0Strategy` port already represents the abstraction; orchestrators instantiate the appropriate strategy directly.
```

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| CIF leak in logs | Code review checklist; tests do NOT assert on log messages containing CIF; logger usage limited to skip-counts and operational identifiers |
| `source_descriptor` ignored may surprise callers | Test asserts non-empty descriptor is silently ignored; future port refinement (separate change) cleans this up |
| RVABREP filter combination performance | Documented; if profiling shows it bites for AS400, separate optimization change |
| Stub raises only at `acquire` | Pattern matches `as400:<alias>` from 005; tests pin the contract |
| Deduplication memory | `set[tuple[str, str]]` fits even at 200k pairs; documented |

---

## 8. Phases (mirrored in tasks.md)

1. Fixtures (4 CSV files)
2. Tests (RED)
3. CSV strategy + RVABREP strategy + stubs (GREEN)
4. Re-exports + verification
5. Docs + commit

---

## 9. Cross-References

- Spec: `specs/006-trigger-service/spec.md`
- Tasks: `specs/006-trigger-service/tasks.md`
- Constitution Principles I, III, V, VI, VII, VIII, IX
- REBIRTH §3.2, §5, §10.1, §12
- Predecessors: 002, 003, 004, 005

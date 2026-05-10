# Plan — 004-mapping-service

**Status**: Draft (under review)
**Created**: 2026-05-09
**Spec reference**: `specs/004-mapping-service/spec.md`

> The **how** of this change. Tasks live in `tasks.md`.

---

## 1. Approach Summary

A small, focused class `MappingService` at `src/cmcourier/services/mapping.py` (~120 LOC including docstrings) plus a frozen dataclass `MappingColumnsConfig`. Eager load via `IDataSource.get_all()` at construction; cached as `dict[str, CMMapping]` for O(1) lookup. Logging via `logging.getLogger(__name__)` for skip / duplicate signals.

Test file `tests/unit/services/test_mapping.py` (~250 LOC) using a real `TabularDataSource` over a single CSV fixture `tests/fixtures/services/modelo_documental.csv`.

---

## 2. File Layout

```
src/cmcourier/services/
├── __init__.py            # MODIFIED: re-export MappingService (and the config dataclass)
└── mapping.py             # NEW: ~120 LOC

tests/unit/services/
├── __init__.py            # already exists
└── test_mapping.py        # NEW: ~250 LOC

tests/fixtures/services/
└── modelo_documental.csv  # NEW: 8-10 rows covering happy path + edge cases
```

No changes to `pyproject.toml`. No new dependencies — `logging` is stdlib.

---

## 3. Architectural Decisions

### 3.1 Regular class, not dataclass

`MappingService` carries behavior plus internal state (`_cache: dict[str, CMMapping]`). Dataclasses are sugar for data carriers; this is a service. Regular `class` with explicit `__init__` is clearer here.

### 3.2 Eager load + dict cache

REBIRTH §4 + §10.1 (S2) imply Modelo Documental is small (< 1000 rows in practice). Eager load:
- O(N) one-time cost at construction
- O(1) lookup per `get_mapping` thereafter
- Insertion order preserved (Python 3.7+ dict semantics) → matches source row order, which is meaningful for first-wins

Lazy alternative (cache miss → query) is rejected: `IDataSource.get_by_fields` is O(N) per call for `TabularDataSource` (linear scan); we'd be paying O(N) per lookup, which dominates at pipeline scale.

### 3.3 Logging via `logging.getLogger(__name__)`

The service emits two structured-ish events:

```python
logger.warning(
    "duplicate ID RVI %r dropped from mapping (first occurrence at row %d wins)",
    id_rvi, first_row_index,
)
logger.info(
    "skipped %d row(s) from Modelo Documental with empty ID RVI",
    skipped_count,
)
```

These use stdlib `logging`. They will be picked up by the central handler config when `cli/ui/logging.py` lands. For now, default Python behavior (stderr) is acceptable.

PII discipline (Constitution Principle VIII) does not apply here — `id_rvi` is a document-class code, not customer data. No CIF, no name. Safe to log.

### 3.4 `MappingColumnsConfig` defaults match REBIRTH §4.1

```python
@dataclass(frozen=True, slots=True)
class MappingColumnsConfig:
    col_clase_id: str = "ID CLASE DOCUMENTAL"
    col_id_rvi: str = "ID RVI"
    col_id_corto: str = "ID Corto"
    col_clase_name: str = "CLASE DOCUMENTAL"
    col_metadata_list: str = "METADATOS"
```

Living in the same file as the service keeps "config-with-its-consumer" cohesion. If config grows beyond ~5 fields, we revisit.

### 3.5 Empty value handling

A row is "empty" (and skipped) when its `id_rvi` cell is any of:
- `None` (NaN-normalized by the adapter)
- empty string `""`
- whitespace-only string (`"   "` after `.strip()`)

The service treats them identically. A helper `_is_blank(value: object) -> bool` is internal:

```python
def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
```

### 3.6 METADATOS parsing

```python
def _parse_metadata_list(raw: object) -> tuple[str, ...]:
    if _is_blank(raw):
        return ()
    if not isinstance(raw, str):
        return ()  # defensive: pandas could in theory yield non-str despite dtype=str
    parts = (p.strip() for p in raw.split(","))
    return tuple(p for p in parts if p)
```

Module-level helper, testable in isolation.

### 3.7 Public API shape

```python
class MappingService:
    def __init__(
        self,
        source: IDataSource,
        columns: MappingColumnsConfig | None = None,
    ) -> None: ...

    def get_mapping(self, id_rvi: str) -> CMMapping: ...
    def get_all(self) -> Iterator[CMMapping]: ...
    def count(self) -> int: ...
    def __contains__(self, id_rvi: object) -> bool: ...
```

`__contains__` accepts `object` (not `str`) per Python convention — even though we only succeed for str keys, the runtime accepts any type and returns `False` for non-strings cleanly.

### 3.8 Validation strategy

The constructor calls `source.get_all()` and iterates rows. The first row's keys are checked against the required column names. If any column is missing, raise:

```python
raise ConfigurationError(
    "Modelo Documental missing required column",
    missing_column=col_name,
)
```

What if the source is empty? The service constructs successfully with an empty cache. Every `get_mapping` raises `IDRViNotMappedError`. Acceptable behavior — empty mapping is a valid state at MVP shakedown when no data has been loaded yet.

### 3.9 The service does NOT close the source

`IDataSource.close()` is the caller's responsibility. The service holds a reference for the duration of the constructor call; after `__init__` returns, the source can be closed by the caller and the service still works (its cache is independent of the source's open state).

---

## 4. Implementation Sketch

```python
"""Mapping service — Modelo Documental cache + lookup (REBIRTH §4)."""

from __future__ import annotations

__all__ = ["MappingColumnsConfig", "MappingService"]

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from cmcourier.domain.exceptions import ConfigurationError, IDRViNotMappedError
from cmcourier.domain.models import CMMapping
from cmcourier.domain.ports import IDataSource

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MappingColumnsConfig:
    """Column-name overrides for the Modelo Documental source. Defaults match REBIRTH §4.1."""
    col_clase_id: str = "ID CLASE DOCUMENTAL"
    col_id_rvi: str = "ID RVI"
    col_id_corto: str = "ID Corto"
    col_clase_name: str = "CLASE DOCUMENTAL"
    col_metadata_list: str = "METADATOS"

    def required_columns(self) -> tuple[str, ...]:
        return (
            self.col_clase_id, self.col_id_rvi, self.col_id_corto,
            self.col_clase_name, self.col_metadata_list,
        )


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_metadata_list(raw: object) -> tuple[str, ...]:
    if _is_blank(raw) or not isinstance(raw, str):
        return ()
    parts = (p.strip() for p in raw.split(","))
    return tuple(p for p in parts if p)


class MappingService:
    """In-memory cache + lookup over the Modelo Documental.

    Loads everything at construction via ``source.get_all()``; subsequent
    ``get_mapping`` calls are O(1). First occurrence of a duplicate
    ``id_rvi`` wins (REBIRTH §4.3); duplicates after the first emit a
    ``WARNING`` log entry.
    """

    def __init__(
        self,
        source: IDataSource,
        columns: MappingColumnsConfig | None = None,
    ) -> None:
        self._columns = columns or MappingColumnsConfig()
        self._cache: dict[str, CMMapping] = {}
        self._load(source)

    def _load(self, source: IDataSource) -> None:
        skipped = 0
        validated_columns = False
        for row_index, row in enumerate(source.get_all()):
            if not validated_columns:
                self._validate_columns(row)
                validated_columns = True

            id_rvi_raw = row.get(self._columns.col_id_rvi)
            if _is_blank(id_rvi_raw):
                skipped += 1
                continue
            id_rvi = str(id_rvi_raw).strip()

            if id_rvi in self._cache:
                _logger.warning(
                    "duplicate ID RVI %r dropped from mapping (first occurrence wins)",
                    id_rvi,
                )
                continue

            self._cache[id_rvi] = CMMapping(
                clase_id=str(row[self._columns.col_clase_id]).strip(),
                id_rvi=id_rvi,
                id_corto=str(row[self._columns.col_id_corto]).strip(),
                clase_name=str(row[self._columns.col_clase_name]).strip(),
                required_metadata_fields=_parse_metadata_list(
                    row.get(self._columns.col_metadata_list)
                ),
            )
        if skipped:
            _logger.info(
                "skipped %d row(s) from Modelo Documental with empty ID RVI",
                skipped,
            )

    def _validate_columns(self, row: dict[str, object]) -> None:
        for col in self._columns.required_columns():
            if col not in row:
                raise ConfigurationError(
                    "Modelo Documental missing required column",
                    missing_column=col,
                )

    def get_mapping(self, id_rvi: str) -> CMMapping:
        try:
            return self._cache[id_rvi]
        except KeyError:
            raise IDRViNotMappedError(id_rvi=id_rvi) from None

    def get_all(self) -> Iterator[CMMapping]:
        return iter(self._cache.values())

    def count(self) -> int:
        return len(self._cache)

    def __contains__(self, id_rvi: object) -> bool:
        return isinstance(id_rvi, str) and id_rvi in self._cache
```

Note the loop is **single-pass** over the source. Validation happens on the first row only (after that, missing columns would have already raised). Empty-ID rows are skipped and counted; duplicates are logged and dropped; valid rows are stored.

---

## 5. Test Strategy

### 5.1 Fixture

`tests/fixtures/services/modelo_documental.csv`:

```csv
ID CLASE DOCUMENTAL,ID RVI,ID Corto,CLASE DOCUMENTAL,METADATOS
01.02.04.01.01,FF17,PT57,Autorizacion SMS,"CIF, NUM_CUENTA_TARJETA"
02.01.03.01.01,AA01,PR12,Solicitud Prestamo,"CIF, NUM_PRESTAMO, Fecha_Firma"
03.01.01.01.01,BB02,GN15,Documento Generico,
04.01.01.01.01,CC03,GN16,Otro Documento,"  CIF  ,  Nombre_Cliente  "
05.01.01.01.01,DD04,GN17,Doc Comma Trail,"CIF,"
06.01.01.01.01,EE05,GN18,Doc Doubled Comma,"CIF,,NUM_CUENTA"
01.02.04.01.01,FF17,PT58,DUPLICATE FF17,"NUM_PRESTAMO"
07.01.01.01.01,,GN19,Empty ID RVI Row,"CIF"
```

8 rows. Covers: vanilla, multiple metadata, empty METADATOS, whitespace METADATOS, trailing comma, doubled comma, duplicate `FF17`, empty `id_rvi`.

### 5.2 Test class shape

```python
@pytest.mark.unit
class TestMappingService:
    @pytest.fixture
    def source(self) -> Iterator[TabularDataSource]:
        path = Path(__file__).parent.parent.parent / "fixtures" / "services" / "modelo_documental.csv"
        src = TabularDataSource(path)
        yield src
        src.close()

    @pytest.fixture
    def service(self, source: TabularDataSource, caplog) -> MappingService:
        # Construction logs warnings; tests that don't care about logs can ignore caplog.
        return MappingService(source)

    def test_count(self, service): ...
    def test_get_mapping_vanilla(self, service): ...
    def test_get_mapping_unknown_raises(self, service): ...
    def test_contains(self, service): ...
    def test_get_all_yields_in_insertion_order(self, service): ...

    # METADATOS parsing
    def test_metadata_empty_cell_becomes_empty_tuple(self, service): ...
    def test_metadata_whitespace_stripped(self, service): ...
    def test_metadata_trailing_comma_handled(self, service): ...
    def test_metadata_doubled_comma_filtered(self, service): ...

    # Edge cases
    def test_duplicate_id_rvi_first_wins(self, service): ...
    def test_duplicate_emits_warning(self, source, caplog): ...
    def test_empty_id_rvi_row_skipped(self, source, caplog): ...
    def test_empty_id_rvi_emits_info(self, source, caplog): ...

    # Custom columns config
    def test_custom_columns(self, tmp_path): ...

    # Validation
    def test_missing_required_column_raises(self, tmp_path): ...
```

`caplog` is a built-in pytest fixture that captures `logging` output for inspection.

### 5.3 Why `pytest.mark.unit` despite using a real adapter

Constitution Principle VI distinguishes unit vs integration by what the SUT touches:

- The SUT here is `MappingService`, which does no I/O (only a single iteration over a generator passed in via constructor).
- The `TabularDataSource` is **wiring**, not the system under test.
- The test is fast (sub-50ms), deterministic, and runs in any environment that has the CSV fixture.

This matches "unit test" intent — fast, isolated, no external systems. The fact that `TabularDataSource` reads a file is an implementation detail of how we set up the test data; we could equally well stub `IDataSource` with a list of dicts, but using the real adapter validates the contract.

### 5.4 Coverage target

≥ 95% branch on `src/cmcourier/services/mapping.py`. The constructor's `if not validated_columns: ...` path on row 0, all `_is_blank` branches, both `_parse_metadata_list` branches, `KeyError` in `get_mapping`, and `__contains__` non-string fallback are all covered.

---

## 6. CHANGELOG entry shape

```markdown
## [0.6.0] — 2026-05-XX

### Added

- `cmcourier.services.mapping.MappingService`: first service in CMCourier. Caches the Modelo Documental from any `IDataSource` and exposes `get_mapping(id_rvi)`, `get_all()`, `count()`, and `__contains__`. Duplicate `ID RVI` rows obey the REBIRTH §4.3 first-wins rule and emit a `WARNING` log entry.
- `cmcourier.services.mapping.MappingColumnsConfig`: frozen dataclass for column-name overrides. Defaults match REBIRTH §4.1.
- `tests/unit/services/test_mapping.py`: ~16 unit tests using a real `TabularDataSource` against `tests/fixtures/services/modelo_documental.csv`. Coverage on `mapping.py`: 95%+.
- `tests/fixtures/services/modelo_documental.csv`: 8-row fixture covering vanilla mappings, METADATOS parsing edge cases (empty, whitespace, trailing/doubled commas), duplicates, and empty-ID rows.

### Rationale

- First service-layer module. Validates that the hexagonal architecture established by 001-003 works end-to-end: a `services/` module imports only from `cmcourier.domain.*`, the test wires a real `IDataSource` adapter, and the service raises domain-defined exceptions.
- Stage S2 of every pipeline depends on this lookup; the `doctor` command's mapping-completeness check uses `get_all()` to validate "every ID RVI in the upcoming batch has a mapping".
```

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Logger config not yet established | stdlib `logging.getLogger(__name__)` defaults to stderr; later `cli/ui/logging.py` routes properly |
| Tests use real adapter, fail if adapter has bugs | acceptable — Constitution Principle VI says we don't mock to insulate from the adapter; if adapter breaks, both adapter tests and service tests fail, which is signal |
| `caplog` fixture behavior subtle (propagation, levels) | tests use `caplog.set_level(logging.WARNING)` explicitly to avoid flakiness |
| Constitution Principle I violation (importing adapters) | tests import the adapter, `mapping.py` does NOT — verified by ruff + mypy on the source file |
| Empty source breaks something | empty source → empty cache → every `get_mapping` raises; documented behavior |

---

## 8. Phases (mirrored in `tasks.md`)

1. Fixture (`modelo_documental.csv`)
2. Test file (`test_mapping.py`) — RED
3. Implementation (`mapping.py` + re-export) — GREEN
4. Verification (ruff, mypy, coverage, pre-commit)
5. Docs + commit

---

## 9. Cross-References

- Spec: `specs/004-mapping-service/spec.md`
- Tasks: `specs/004-mapping-service/tasks.md`
- Constitution: `.specify/memory/constitution.md`
- Predecessor changes: 001, 002, 003
- REBIRTH §4 (Modelo Documental), §10.1 (S2)

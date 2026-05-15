# Plan — 008-indexing-service

**Status**: Draft
**Spec**: `specs/008-indexing-service/spec.md`

---

## 1. Architecture in one paragraph

A single class `IndexingService` (Constitution III: thin and focused),
constructed with an `IDataSource` adapter and an `IndexingColumnsConfig`.
Two public methods: `find_documents(trigger)` for single-trigger lookups
(typed-error on miss) and `find_documents_batch(triggers)` for orchestrator-
driven batches (silent-empty on miss). Both share a private
`_row_to_document` factory that converts adapter dicts into
`RVABREPDocument` instances. Lives in `services/indexing.py`; re-exported
from `services/__init__.py`.

---

## 2. Module layout

```
src/cmcourier/services/indexing.py
├── IndexingColumnsConfig           # frozen+slots dataclass
├── IndexingService                 # the service
│   ├── __init__(source, config, batch_size=50)
│   ├── find_documents(trigger) -> list[RVABREPDocument]
│   ├── find_documents_batch(triggers) -> Iterator[tuple[TriggerRecord, list[RVABREPDocument]]]
│   ├── _query_for_trigger(trigger) -> list[dict]      # private wrapper around get_by_fields
│   ├── _query_for_chunk(chunk) -> list[dict]          # private wrapper around get_by_fields_in
│   ├── _classify(rows, trigger) -> list[RVABREPDocument]   # dedupe + delete-filter + dict→doc
│   └── _row_to_document(row) -> RVABREPDocument       # field-by-field coercion
```

Every method ≤ 50 lines.

---

## 3. Public API contracts

### 3.1 `IndexingColumnsConfig`

```python
@dataclass(frozen=True, slots=True)
class IndexingColumnsConfig:
    # Filter / lookup columns
    shortname_column:      str = "ABABCD"
    system_id_column:      str = "ABAACD"
    delete_code_column:    str = "ABACST"
    txn_num_column:        str = "ABAANB"
    # Index columns (passthrough to RVABREPDocument)
    index2_column:         str = "ABACCD"
    index3_column:         str = "ABADCD"
    index4_column:         str = "ABAECD"
    index5_column:         str = "ABAFCD"
    index6_column:         str = "ABAGCD"
    index7_column:         str = "ABAHCD"   # = id_rvi join key
    # File columns
    image_type_column:     str = "ABABST"
    image_path_column:     str = "ABAICD"
    file_name_column:      str = "ABAJCD"
    # Date / numeric columns
    creation_date_column:  str = "ABAADT"
    last_view_date_column: str = "ABABDT"
    total_pages_column:    str = "ABABUN"
```

Defaults match the spec verbatim. Tests override columns to use the
friendly names in the CSV fixture (`shortname`, `system_id`, `txn_num`, …)
and a second test verifies defaults are correct.

### 3.2 `IndexingService.find_documents`

```python
def find_documents(self, trigger: TriggerRecord) -> list[RVABREPDocument]:
    """Single-trigger lookup with typed-error semantics.

    Raises:
        RVABREPNotFoundError: zero rows match (shortname, system_id).
        RVABREPDeletedError:  all matching rows have non-empty delete_code.
        IndexingError:        adapter raised an unexpected exception.
    """
```

### 3.3 `IndexingService.find_documents_batch`

```python
def find_documents_batch(
    self, triggers: Iterable[TriggerRecord]
) -> Iterator[tuple[TriggerRecord, list[RVABREPDocument]]]:
    """Yield one (trigger, docs) per input trigger.

    Missing / fully-deleted triggers yield an EMPTY list (no exception).
    The orchestrator decides whether an empty result is an error in its
    pipeline context.
    """
```

---

## 4. Algorithm sketches

### 4.1 Single-trigger lookup

```
rows = source.get_by_fields({
    shortname_column: trigger.shortname,
    system_id_column: trigger.system_id,
})
if not rows:
    raise RVABREPNotFoundError(shortname=..., system_id=...)
docs = _classify(rows, trigger)
if not docs and rows:
    raise RVABREPDeletedError(shortname=..., system_id=..., deleted_count=len(rows))
return docs
```

### 4.2 Batched lookup

```
buffer = []
for t in triggers:
    buffer.append(t)
    if len(buffer) >= batch_size:
        yield from _process_chunk(buffer)
        buffer = []
if buffer:
    yield from _process_chunk(buffer)


def _process_chunk(chunk):
    shortnames = [t.shortname for t in chunk]
    rows = source.get_by_fields_in(
        field=shortname_column,
        values=shortnames,
        fixed_filters={},
    )
    # Index rows by (shortname, system_id) for O(1) per-trigger grouping.
    by_key = defaultdict(list)
    for row in rows:
        key = (row[shortname_column], row[system_id_column])
        by_key[key].append(row)
    for t in chunk:
        trigger_rows = by_key.get((t.shortname, t.system_id), [])
        yield t, _classify(trigger_rows, t)
```

**Why no per-`system_id` `fixed_filters`**: triggers in the same chunk may
have different `system_id`s (a `system_id=1` trigger and a `system_id=5`
trigger can land in the same batch). The query over-fetches across system
ids, then Python filters by `(shortname, system_id)` tuple in the
`defaultdict`. Over-fetch cost is bounded — same shortname rarely exists
across many system_ids; cardinality is small.

### 4.3 `_classify(rows, trigger)`

```
# 1. Filter deleted
active = [r for r in rows if not r[delete_code_column]]
# 2. Detect duplicate txn_num — keep first occurrence, WARN on rest
seen: set[str] = set()
unique: list[dict] = []
duplicates = 0
for r in active:
    txn = r[txn_num_column]
    if txn in seen:
        duplicates += 1
        continue
    seen.add(txn)
    unique.append(r)
if duplicates:
    log.warning(
        "indexing: dropped duplicate txn_num rows",
        extra={"shortname": trigger.shortname, "duplicate_count": duplicates},
    )
# 3. Convert dicts to RVABREPDocument
return [self._row_to_document(r) for r in unique]
```

### 4.4 `_row_to_document(row)`

Field-by-field coercion with explicit `None` / `"0"` handling for dates and
ints. Pure function over the `IndexingColumnsConfig` map. Uses helpers from
`domain.models`:

- `parse_cymmdd` for `creation_date`.
- `parse_cymmdd` for `last_view_date` UNLESS the raw value is `""`, `None`,
  or `"0"` — in which case `None`.
- `int(value)` for `total_pages`, treating `None` / `""` as `0`.
- `str(value)` for every other field, defensive against pandas / pyodbc
  returning native ints.

---

## 5. Test plan

### 5.1 Tests in `tests/unit/services/test_indexing.py`

Group / count breakdown:

| Group | Tests | Acceptance scenarios covered |
|-------|-------|------------------------------|
| Construction & defaults | 3 | 4.12 + lazy init |
| Single-trigger lookup | 5 | 4.1, 4.2, 4.3, 4.4, 4.5 |
| Duplicate handling | 2 | 4.6 |
| Batched lookup | 5 | 4.7, 4.8, 4.9, plus single-call instrumentation |
| Row coercion | 4 | 4.11 + edge cases for `total_pages`, `last_view_date` |
| Error wrapping | 2 | 4.10 + duplicate WARNING does NOT raise |
| Logging discipline | 1 | Field NAMES only, no VALUES of cif/index2 |

Total: ~22 tests.

### 5.2 Fixtures

New file `tests/fixtures/services/rvabrep_index_sample.csv`:
- ~12 synthetic rows
- Columns use the FRIENDLY names (`shortname`, `system_id`, `txn_num`,
  `delete_code`, `index2..7`, `image_type`, `image_path`, `file_name`,
  `creation_date`, `last_view_date`, `total_pages`)
- Rows cover: vanilla single match, multi-match (3 rows same shortname),
  fully-deleted shortname, mixed deleted, duplicate `txn_num`,
  `system_id=5` (system filter test), `last_view_date='0'` and `''`,
  PDF row and paged row, `total_pages='1'` and `'540'`.

Tests use `IndexingColumnsConfig(shortname_column='shortname', ...)` to
override every column name. One test instantiates the default config and
asserts the AS400 physical names match the spec.

### 5.3 Instrumentation for "exactly N calls"

REQ-002 NFR-002 require call counting. Approach: a tiny `_CallCountingSource`
adapter that wraps a real `TabularDataSource` and increments a counter on
each `get_by_fields_in` / `get_by_fields` invocation. Lives in
`test_indexing.py` only (test helper, not production code).

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..003 (construction) | §3.1, §3.2, §3.3 | Construction & defaults |
| REQ-004..009 (single-trigger) | §4.1, §4.3 | Single-trigger + duplicate handling |
| REQ-010..014 (batched) | §4.2 | Batched lookup |
| REQ-015..018 (coercion) | §4.4 | Row coercion |
| REQ-019..020 (error wrap) | §4.1 | Error wrapping |
| REQ-021 (logging) | §4.3 | Logging discipline |
| NFR-001..003 (perf) | §4.1, §4.2 | Call-count instrumentation |
| NFR-004 (coverage ≥95%) | — | `pytest --cov` |
| NFR-005 (50-line cap) | — | Visual review of each method |

---

## 7. Files touched

```
NEW   src/cmcourier/services/indexing.py
NEW   tests/unit/services/test_indexing.py
NEW   tests/fixtures/services/rvabrep_index_sample.csv
EDIT  src/cmcourier/services/__init__.py    # re-export IndexingService + IndexingColumnsConfig
EDIT  CHANGELOG.md                          # [0.10.0]
EDIT  README.md                             # Status checklist: "Eighth change"
NEW   specs/008-indexing-service/{spec,plan,tasks}.md
```

No domain changes. No adapter changes (TabularDataSource is sufficient for
tests).

---

## 8. Risks

- **Risk**: `last_view_date` semantics. the spec says `"0"` if never
  viewed. The CSV fixture may also produce `""` from pandas. Both must map
  to `None`. **Mitigation**: explicit test for both values.
- **Risk**: Duplicate WARNING may flood logs in production. **Mitigation**:
  log includes `duplicate_count` so a single WARNING describes N
  duplicates; no per-row WARNING.
- **Risk**: Coverage threshold ≥95% on `indexing.py`. **Mitigation**: the
  module is small (~120 LOC estimated); 22 tests should cover every branch.

---

## 9. Estimated effort

- Spec / plan / tasks (this commit): done
- Phase 1 (tests RED): ~75 min
- Phase 2 (impl GREEN): ~75 min
- Phase 3 (verification): ~15 min
- Phase 4 (docs + commit + merge): ~15 min
- **Total**: ~3 h

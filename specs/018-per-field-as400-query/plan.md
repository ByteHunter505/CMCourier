# Plan — 018-per-field-as400-query

**Status**: Draft
**Spec**: `specs/018-per-field-as400-query/spec.md`

---

## 1. Architecture in one paragraph

Two narrow refactors. (1) `As400DataSource` accepts `table` OR
`query` (keyword-only, mutually exclusive); internally collapses to
a single `source_expr` string used in every SQL template. (2)
`As400MetadataSourceConfig` makes `table` optional and adds optional
`query`, with a model-validator enforcing exactly-one. Wiring passes
through. No change to MetadataService or doctor — the polymorphic
contract holds.

---

## 2. Module layout

```
src/cmcourier/adapters/sources/as400.py   # constructor + source_expr
src/cmcourier/config/schema.py            # As400MetadataSourceConfig fields + validator
src/cmcourier/config/wiring.py            # pass query when present
```

No new modules.

---

## 3. Public API contracts

### 3.1 `As400DataSource.__init__`

```python
class As400DataSource(IDataSource):
    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        driver: str,
        username: str,
        password: str,
        table: str = "",
        query: str | None = None,
    ) -> None:
        if bool(table) == bool(query):
            raise ConfigurationError(
                "As400DataSource needs exactly one of table or query",
                table_set=bool(table),
                query_set=bool(query),
            )
        self._source_expr = f"({query}) AS T" if query else table
        ...
```

Existing call sites pass `table="..."`. New metadata wiring may pass
`query="..."`. The trigger and indexing paths keep using `table`.

### 3.2 `As400MetadataSourceConfig`

```python
class As400MetadataSourceConfig(BaseModel):
    model_config = _STRICT
    kind: Literal["as400"]
    alias: str
    as400_connection: As400ConnectionConfig
    table: str | None = Field(default=None, min_length=1)
    query: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one_table_or_query(self) -> Self:
        if bool(self.table) == bool(self.query):
            raise ValueError(
                "as400 metadata source requires exactly one of "
                "`table` or `query`"
            )
        return self
```

### 3.3 Wiring `_build_metadata_sources` branch

```python
# inside the for-loop, the as400 branch:
registry[src_cfg.alias] = As400DataSource(
    host=src_cfg.as400_connection.host,
    port=src_cfg.as400_connection.port,
    database=src_cfg.as400_connection.database,
    driver=src_cfg.as400_connection.driver,
    username=secrets.as400_username,
    password=secrets.as400_password,
    table=src_cfg.table or "",
    query=src_cfg.query,
)
```

The adapter's own validator handles the exactly-one rule
(redundant with schema but enforces invariants at adapter boundary).

---

## 4. Algorithm sketches

### 4.1 source_expr collapse

```python
self._source_expr = f"({query}) AS T" if query else table
```

Then everywhere `self._table` was referenced (`get_all`, `count`,
`get_by_fields`, `get_by_fields_in`), replace with
`self._source_expr`.

### 4.2 SQL templates after the change

| Method | Before (table mode) | After (query mode) |
|--------|---------------------|---------------------|
| `get_all` | `SELECT * FROM CUSTOMERS` | `SELECT * FROM (SELECT CIF, NAME FROM CUSTOMERS WHERE ACTIVE = 'Y') AS T` |
| `count` | `SELECT COUNT(*) AS CNT FROM CUSTOMERS` | `SELECT COUNT(*) AS CNT FROM (...) AS T` |
| `get_by_fields` | `SELECT * FROM CUSTOMERS WHERE CIF = ?` | `SELECT * FROM (...) AS T WHERE CIF = ?` |
| `get_by_fields_in` | `SELECT * FROM CUSTOMERS WHERE CIF IN (?,?,?)` | `SELECT * FROM (...) AS T WHERE CIF IN (?,?,?)` |

All transparent to callers.

### 4.3 Backwards compat at the constructor

The constructor keeps `table` as a positional-by-keyword arg with a
default `""`. Existing call sites that pass `table="CUSTOMERS"` work
unchanged. Existing call sites that pass `table=trigger_cfg.as400_connection.table
or ""` (the trigger path with optional table) still work — they pass
non-empty strings, and the validator only complains when both empty.

---

## 5. Test plan

### 5.1 `tests/unit/adapters/sources/test_as400.py` (~4 new tests)

- `TestAs400DataSourceConstructor`:
  - `test_table_only_succeeds` — backwards compat
  - `test_query_only_succeeds` — new
  - `test_both_raises` — ConfigurationError
  - `test_neither_raises` — ConfigurationError
- `TestAs400DataSourceQueryMode` (extends existing tests with
  query-backed source):
  - `test_get_all_with_query_uses_subquery` — mocked pyodbc, assert
    SQL contains `FROM (SELECT ...) AS T`
  - `test_count_with_query` — mocked pyodbc, assert COUNT works
  - `test_get_by_fields_with_query` — mocked pyodbc, assert WHERE
    clause appended

### 5.2 `tests/unit/config/test_schema.py` (~3 new tests)

- `test_as400_metadata_source_with_query_loads` — query-only YAML
  validates.
- `test_as400_metadata_source_both_table_and_query_rejected` —
  Pydantic raises.
- `test_as400_metadata_source_neither_table_nor_query_rejected` —
  Pydantic raises.

### 5.3 `tests/integration/config/test_wiring.py` (~1 new test)

- `test_as400_metadata_source_with_query_builds` — YAML with
  query-backed metadata source builds pipeline; registry contains
  the alias.

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..004 (schema) | §3.2 | test_schema |
| REQ-005..008 (adapter) | §3.1, §4.1-4.3 | TestAs400DataSourceConstructor, TestAs400DataSourceQueryMode |
| REQ-009 (wiring) | §3.3 | test_as400_metadata_source_with_query_builds |
| REQ-010 (doctor) | implicit | existing doctor tests still pass |
| REQ-011..013 (tests) | §5 | all above |

---

## 7. Files touched

```
EDIT  src/cmcourier/adapters/sources/as400.py
EDIT  src/cmcourier/config/schema.py
EDIT  src/cmcourier/config/wiring.py
EDIT  tests/unit/adapters/sources/test_as400.py
EDIT  tests/unit/config/test_schema.py
EDIT  tests/integration/config/test_wiring.py
EDIT  CHANGELOG.md
EDIT  README.md
NEW   specs/018-per-field-as400-query/{spec,plan,tasks}.md
```

No new dependencies. No new test fixtures.

---

## 8. Risks

- **Risk R1**: Existing `As400DataSource` tests pass `table=` and
  rely on `self._table`. After the rename to `self._source_expr`,
  any test that introspects `strategy._table` breaks. Mitigation:
  grep for `_table` access in test files, replace with
  `_source_expr` if any.
- **Risk R2**: DB2/AS400 may reject the derived-table alias in some
  legacy configurations. Mitigation: DB2 has supported derived
  tables since v6r1; AS400 ODBC driver inherits. If a customer's
  environment is older, document the table-mode fallback.
- **Risk R3**: The `query` string is concatenated into SQL without
  validation. Operators are responsible. Mitigation: PII discipline
  (Principle VIII) means we don't log query bodies; the failure
  surface is the AS400's own error response, which doctor already
  catches.
- **Risk R4**: The trigger path uses
  `trigger_cfg.as400_connection.table or ""` and passes that to
  `As400DataSource(table=...)`. If `table` is empty (because the
  trigger uses `query`), the constructor would now raise. But the
  trigger flow constructs the adapter with `table=""` AND passes
  `query=trigger_cfg.query` separately at call time via
  `As400TriggerStrategy`. Need to verify: does the trigger path
  need `query` in the constructor too, or only at call time?
  Answer: trigger calls `data_source.query_stream(self._query, [])`
  — the query is passed per-call to `query`/`query_stream`, NOT in
  the constructor. So the trigger path passes `table=""` and the
  new validator would raise. **Resolution**: relax the validator to
  allow `table=""` and `query=None` (the "uninitialized" form used
  by callers that only invoke `query`/`query_stream` directly). The
  exactly-one rule applies ONLY when callers want
  table-or-source-expr semantics (`get_all`, `count`,
  `get_by_fields*`).
  
  Cleaner alternative: keep the trigger path passing `table=""`
  unchanged, and the validator allows `table=""` (empty allowed) +
  `query=None` together — meaning "I'll use raw `query`/`query_stream`
  only, never `get_all`/etc." The simpler check then becomes: "if
  both set (truthy), raise. If neither, allow (deferred
  initialization)." This is consistent with the existing trigger
  code path which sets `table=""`.

  **Final decision**: the constructor accepts (table="", query=None)
  as a valid "raw mode" — both `get_all`/`count`/etc. raise at call
  time with a clear error if invoked. The exactly-one rule applies
  at the SCHEMA layer (where the metadata source must have one of
  the two), not at the adapter layer.

---

## 9. Estimated effort

- Spec / plan / tasks: 30 min
- Phase 1 (adapter refactor + 7 tests): 50 min
- Phase 2 (schema + wiring + 4 tests): 40 min
- Phase 3 (verification + smoke): 15 min
- Phase 4 (docs + commit + merge): 15 min
- **Total**: ~2 h 30 min

---

## 10. Open questions

None. All scope decisions resolved.

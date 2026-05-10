# Plan — 014-as400-pipelines

**Status**: Draft
**Spec**: `specs/014-as400-pipelines/spec.md`

---

## 1. Architecture in one paragraph

Five changes in one PR:
1. New adapter `As400DataSource` over pyodbc (mocked at the
   `pyodbc.connect` boundary in tests).
2. Rename `CsvTriggerPipeline` → `StagedPipeline` (module + class).
   The class IS the generic pipeline; trigger strategy is injected.
3. Schema's `TriggerConfig` becomes a discriminated union by `kind`
   (`csv` | `rvabrep` | `as400`). `As400ConnectionConfig` new block.
4. New CLI commands: `rvabrep-pipeline run`, `as400-trigger-pipeline run`.
   Both wrap the same `StagedPipeline.run`; differ in which S0 is
   constructed.
5. Doctor adds `as400_connectivity` (active only when `kind == "as400"`).

The real `As400TriggerStrategy` replaces the 006 stub. Wiring layer
dispatches on `config.trigger.kind` to construct the right S0.

---

## 2. Module layout

```
src/cmcourier/
├── adapters/sources/
│   └── as400.py                                # NEW
├── orchestrators/
│   ├── staged.py                               # RENAMED (was csv_trigger.py)
│   └── __init__.py                             # exports StagedPipeline, RunReport
├── services/triggers/
│   ├── as400.py                                # NEW (real strategy)
│   └── stubs.py                                # As400TriggerStrategy REMOVED from here
├── config/
│   ├── schema.py                               # +discriminated union, +As400ConnectionConfig
│   └── wiring.py                               # dispatch by kind
└── cli/
    ├── app.py                                  # +rvabrep + as400 CLI commands
    └── doctor.py                               # +_check_as400_connectivity
```

Every method ≤ 50 lines. Modules ≤ 250 lines.

---

## 3. Public API contracts

### 3.1 `As400DataSource`

```python
class As400DataSource(IDataSource):
    def __init__(
        self, *,
        host: str, port: int, database: str, driver: str,
        username: str, password: str, table: str,
    ) -> None: ...

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]: ...
    def query_stream(self, sql: str, params: list[Any] | None = None) -> Iterator[dict[str, Any]]: ...
    def get_by_fields(self, filters: Mapping[str, Any]) -> list[dict[str, Any]]: ...
    def get_by_fields_in(
        self, field: str, values: list[Any], fixed_filters: Mapping[str, Any],
    ) -> list[dict[str, Any]]: ...
    def get_all(self) -> Iterator[dict[str, Any]]: ...
    def count(self) -> int: ...
    def close(self) -> None: ...
```

Internal: `_connect()` lazy on first method call. `_cursor()` returns
the current cursor or opens a new one. Connection string built via
`_build_connection_string()`.

### 3.2 `StagedPipeline`

Identical constructor to today's `CsvTriggerPipeline`. Class renamed
in the source file `staged.py`. All other types (`RunReport`,
`_StageItem`) move with it.

### 3.3 Schema discriminated union

```python
class CsvTriggerConfig(BaseModel):
    model_config = _STRICT
    kind: Literal["csv"] = "csv"
    csv_path: FilePath
    shortname_column: str = "ShortName"
    cif_column: str = "CIF"
    system_id_column: str = "SystemID"


class RvabrepFiltersModel(BaseModel):
    model_config = _STRICT
    systems: list[str] = Field(default_factory=list)
    document_types: list[str] = Field(default_factory=list)


class RvabrepTriggerConfig(BaseModel):
    model_config = _STRICT
    kind: Literal["rvabrep"]
    filters: RvabrepFiltersModel = Field(default_factory=RvabrepFiltersModel)


class As400ConnectionConfig(BaseModel):
    model_config = _STRICT
    host: str
    port: int = 446
    database: str = "RVILIB"
    driver: str = "iSeries Access ODBC Driver"
    table: str | None = None


class As400TriggerConfig(BaseModel):
    model_config = _STRICT
    kind: Literal["as400"]
    query: str
    as400_connection: As400ConnectionConfig


TriggerConfigUnion = Annotated[
    CsvTriggerConfig | RvabrepTriggerConfig | As400TriggerConfig,
    Field(discriminator="kind"),
]


class PipelineConfig(BaseModel):
    model_config = _STRICT
    trigger: TriggerConfigUnion
    ...
```

Discriminator default for backwards-compat: when `kind` is missing,
Pydantic looks at field shape — but tagged unions require the
discriminator. So in 014 we keep config-level loaders flexible:
`load_config` injects `kind: "csv"` into the `trigger` block if the
operator omitted it AND no other `kind`-only fields are present
(e.g., `filters` or `query`).

### 3.4 `As400TriggerStrategy`

```python
class As400TriggerStrategy(S0Strategy):
    def __init__(
        self, source: As400DataSource, query: str,
        col_shortname: str = "SHORTNAME",
        col_cif: str = "CIF",
        col_system_id: str = "SYSTEMID",
    ) -> None: ...
    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]: ...
```

`acquire` runs `self._source.query(self._query, [])`, yields one
`TriggerRecord` per row. Blank rows are dropped with an INFO log of
the count (matches `CsvTriggerStrategy` semantics).

### 3.5 CLI

```python
@main.group(name="rvabrep-pipeline")
def rvabrep_pipeline_group() -> None: ...

@rvabrep_pipeline_group.command(name="run")
@click.option(...)
def rvabrep_run_command(...): ...
```

Same for `as400-trigger-pipeline`. Each command's body verifies
`config.trigger.kind` matches the expected kind, then dispatches to
the shared `_run_pipeline_command(config, secrets, batch_id,
from_stage, batch_size, triggers_override, log_level)` helper.

---

## 4. Algorithm sketches

### 4.1 `As400DataSource._connect`

```python
def _connect(self) -> pyodbc.Connection:
    if self._conn is not None:
        return self._conn
    try:
        self._conn = pyodbc.connect(self._build_connection_string())
    except pyodbc.Error as exc:
        raise IndexingError(
            "AS400 connection failed",
            sqlstate=_extract_sqlstate(exc),
        ) from exc
    return self._conn
```

### 4.2 `As400DataSource.query`

```python
def query(self, sql, params=None):
    cursor = self._connect().cursor()
    try:
        cursor.execute(sql, params or [])
        columns = [col[0] for col in cursor.description or []]
        return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
    except pyodbc.Error as exc:
        raise IndexingError("AS400 query failed", sql_prefix=sql[:80]) from exc
    finally:
        cursor.close()
```

### 4.3 `As400DataSource.get_by_fields_in`

```python
def get_by_fields_in(self, field, values, fixed_filters):
    if not values:
        return []
    chunks = [values[i:i + _IN_CHUNK_SIZE] for i in range(0, len(values), _IN_CHUNK_SIZE)]
    results: list[dict[str, Any]] = []
    fixed_cols = list(fixed_filters.keys())
    fixed_vals = list(fixed_filters.values())
    for chunk in chunks:
        placeholders = ", ".join("?" * len(chunk))
        fixed_clause = " AND " + " AND ".join(f"{c} = ?" for c in fixed_cols) if fixed_cols else ""
        sql = f"SELECT * FROM {self._table} WHERE {field} IN ({placeholders}){fixed_clause}"
        results.extend(self.query(sql, list(chunk) + fixed_vals))
    return results
```

`_IN_CHUNK_SIZE = 1000`.

### 4.4 Wiring dispatch

```python
def build_pipeline(config, secrets):
    _reject_unsupported_source_types(config.metadata)
    trigger_strategy = _build_trigger_strategy(config.trigger, secrets)
    rvabrep_src = _build_rvabrep_source(config, secrets)
    ...

def _build_trigger_strategy(trigger_cfg, secrets):
    if trigger_cfg.kind == "csv":
        trigger_src = TabularDataSource(trigger_cfg.csv_path)
        return CsvTriggerStrategy(trigger_src, CsvTriggerColumnsConfig(...))
    if trigger_cfg.kind == "rvabrep":
        # Reuse the indexing source for discovery.
        ... (constructed later from config.indexing)
        return DirectRvabrepTriggerStrategy(indexing_src, ...)
    if trigger_cfg.kind == "as400":
        if not secrets.as400_username:
            raise ConfigurationError(...)
        as400_src = As400DataSource(...)
        return As400TriggerStrategy(as400_src, trigger_cfg.query)
    raise ConfigurationError("unknown trigger.kind", kind=trigger_cfg.kind)
```

### 4.5 CLI dispatch

```python
@main.group("rvabrep-pipeline")
def rvabrep_pipeline_group(): ...

@rvabrep_pipeline_group.command("run")
@click.option(... common flags ...)
def rvabrep_run_command(config_path, ...):
    _run_pipeline_command(
        config_path, expected_kind="rvabrep", ...
    )
```

`_run_pipeline_command(config_path, *, expected_kind, batch_id, from_stage,
batch_size, triggers_override, log_level)` factors the common run flow
out of the three commands.

### 4.6 Doctor check

```python
def _check_as400_connectivity(config, secrets):
    if config.trigger.kind != "as400":
        return _skip("as400_connectivity", "trigger_kind_not_as400")
    try:
        src = As400DataSource(...)
        try:
            src.query("SELECT 1", [])  # cheapest connectivity probe
        finally:
            src.close()
    except Exception as exc:
        return _fail("as400_connectivity", exc)
    return CheckResult(name="as400_connectivity", status=CheckStatus.PASS,
                       message="AS400 reachable", details=_frozen({"host": ...}))
```

---

## 5. Test plan

### 5.1 `tests/integration/adapters/test_as400.py` (~15 tests)

All tests `monkeypatch.setattr("cmcourier.adapters.sources.as400.pyodbc.connect", _fake_connect)`.

- `_FakeCursor` (script driver: pre-loaded `executions` list + `rows`
  pulled by `execute`).
- `_FakeConnection` (cursor factory + close tracking).
- `_fake_connect(connection_string)` returns the prepared
  `_FakeConnection`.

Tests:
- Construction does not connect.
- First method call connects.
- `query` materializes rows correctly.
- `query_stream` yields lazily (assert via batch_size=500 fetchmany).
- `get_by_fields` builds the WHERE clause and parameter list.
- `get_by_fields_in` chunks values into 1000-sized groups.
- `get_by_fields_in` with empty values returns `[]` (no execute).
- `get_all` and `count` work.
- `close()` is idempotent.
- pyodbc.Error → IndexingError wrap.
- SQLSTATE extraction from `pyodbc.Error.args[0]`.
- Connection string format.

### 5.2 `tests/integration/pipeline/test_staged_pipeline_renames.py`

NOT a new test file — instead, every existing test file referencing
`CsvTriggerPipeline` is updated in-place to `StagedPipeline`. The
old `csv_trigger` import path is deleted.

### 5.3 `tests/unit/config/test_schema.py` (~5 new tests)

- Discriminated union: csv-kind YAML loads to `CsvTriggerConfig`.
- Rvabrep-kind YAML loads to `RvabrepTriggerConfig`.
- As400-kind YAML loads to `As400TriggerConfig`.
- Missing `kind` defaults to `"csv"` (REQ-017).
- Mismatched fields (kind=csv + filters: ...) raises.

### 5.4 `tests/integration/config/test_wiring.py` (~3 new tests)

- Build pipeline with `kind=rvabrep` config → returns StagedPipeline.
- Build pipeline with `kind=as400` config but `secrets.as400_username
  == ""` → raises `ConfigurationError`.
- Build pipeline with `kind=as400` + mocked pyodbc → succeeds.

### 5.5 `tests/integration/cli/test_rvabrep_pipeline.py` + `test_as400_pipeline.py`

~6 tests total:
- `rvabrep-pipeline run` happy path with mocked CMIS.
- `rvabrep-pipeline run` exit 2 when config has `kind=csv`.
- `as400-trigger-pipeline run` happy path (pyodbc mocked, CMIS mocked).
- `as400-trigger-pipeline run` exit 2 when `kind != "as400"`.
- `as400-trigger-pipeline run` exit 2 when env var missing.
- `cmcourier --help` lists all 4 commands.

### 5.6 `tests/integration/cli/test_doctor.py` (~2 new tests)

- `as400_connectivity` SKIPs when `kind != "as400"`.
- `as400_connectivity` PASSes with mocked pyodbc.

### 5.7 Test count breakdown

| Suite | New | Updated |
|-------|-----|---------|
| AS400 adapter | ~12 | — |
| Schema | 5 | — |
| Wiring | 3 | minor |
| RVABREP pipeline CLI | 3 | — |
| AS400 pipeline CLI | 3 | — |
| Doctor | 2 | rename touch-ups |
| Pipeline rename | — | every existing pipeline / wiring / CLI test |

Net new: ~28. Net touched: ~80 lines of imports + class-name renames.

---

## 6. Files touched

```
NEW   src/cmcourier/adapters/sources/as400.py
NEW   src/cmcourier/services/triggers/as400.py        # real strategy
EDIT  src/cmcourier/services/triggers/__init__.py      # re-export
EDIT  src/cmcourier/services/triggers/stubs.py         # remove As400TriggerStrategy
RENAME src/cmcourier/orchestrators/csv_trigger.py → staged.py
EDIT  src/cmcourier/orchestrators/__init__.py         # export new names
EDIT  src/cmcourier/config/schema.py                  # discriminated union + As400ConnectionConfig
EDIT  src/cmcourier/config/wiring.py                  # dispatch on kind
EDIT  src/cmcourier/cli/app.py                        # rvabrep + as400 CLI commands
EDIT  src/cmcourier/cli/doctor.py                     # as400_connectivity check
NEW   tests/integration/adapters/test_as400.py
EDIT  tests/integration/pipeline/{test_csv_trigger_pipeline.py, conftest.py}
        # rename class references
EDIT  tests/integration/config/test_wiring.py         # 3 new tests
EDIT  tests/unit/config/test_schema.py                # 5 new tests
NEW   tests/integration/cli/test_rvabrep_pipeline.py
NEW   tests/integration/cli/test_as400_pipeline.py
EDIT  tests/integration/cli/test_doctor.py            # 2 new tests + rename
EDIT  tests/integration/cli/test_cli.py               # rename touch-ups
EDIT  CHANGELOG.md                                    # [0.16.0]
EDIT  README.md                                       # Status checklist
NEW   specs/014-as400-pipelines/{spec,plan,tasks}.md
```

No new dependencies; `pyodbc` was already declared in `pyproject.toml`
since the bootstrap (change 003).

---

## 7. Risks

- **Risk**: the `csv_trigger.py` → `staged.py` rename in git history
  is detected as "delete + add" rather than rename. Mitigation: do
  the rename with `git mv` for clean diff history.
- **Risk**: discriminated-union schema with a default discriminator
  is unusual in Pydantic v2. Mitigation: a small custom validator in
  `load_config` injects `kind: "csv"` BEFORE `model_validate` if the
  trigger block has no kind. Loses the elegance of pure Pydantic
  but preserves backwards compatibility.
- **Risk**: pyodbc on the test machine. The `import pyodbc` itself
  fails if the dev hasn't installed `unixodbc-dev`. We never call
  `pyodbc.connect` in tests (it's mocked), but the top-level import
  in `as400.py` runs. Mitigation: defer the `import pyodbc` to
  inside `_connect()` AND inside the `_build_connection_string`
  helper if it references any pyodbc type. This delays the failure
  until an actual connect.
- **Risk**: the rename touches MANY test files; if any single
  reference is missed the import error is loud, but combined with
  the discriminator-default refactor, debugging gets noisy.
  Mitigation: do the rename in a discrete commit BEFORE any other
  edits inside this change's branch (Phase 2 task), then verify
  pytest passes, then proceed to Phase 3.

---

## 8. Estimated effort

- Spec / plan / tasks: done
- Phase 1 (AS400 adapter + ~12 tests): 90 min
- Phase 2 (StagedPipeline rename): 30 min
- Phase 3 (Schema discriminated union + 5 tests): 90 min
- Phase 4 (real strategy + wiring + CLI commands + 6 tests): 90 min
- Phase 5 (doctor as400 check + 2 tests + verification): 45 min
- Phase 6 (docs + commit + merge): 25 min
- **Total**: ~5 h 50 min — the most ambitious single change.

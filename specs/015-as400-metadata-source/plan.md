# Plan — 015-as400-metadata-source

**Status**: Draft
**Spec**: `specs/015-as400-metadata-source/spec.md`

---

## 1. Architecture in one paragraph

Three touch points:
1. `config/schema.py`: `MetadataSourceConfig` becomes a
   `Annotated[CsvMetadataSourceConfig | As400MetadataSourceConfig,
   Field(discriminator="kind")]` alias. Two new concrete classes.
2. `config/loader.py`: existing trigger-kind injection extended to
   also inject `kind: "csv"` into each `metadata.sources[i]` that
   omits it.
3. `config/wiring.py`: the per-source builder dispatches on `kind`.
   The `_reject_unsupported_source_types` guard is removed since
   `as400:*` field sources now have real backing data sources.

`MetadataService` and the orchestrator are unchanged — they consume
`IDataSource.get_all()` polymorphically.

---

## 2. Module layout

```
src/cmcourier/config/schema.py    # +CsvMetadataSourceConfig +As400MetadataSourceConfig
src/cmcourier/config/loader.py    # +metadata.sources kind injection
src/cmcourier/config/wiring.py    # +as400 dispatch, -reject_as400
src/cmcourier/cli/doctor.py       # +as400 dispatch in metadata_sources check
```

No new modules. No method exceeds 50 lines after the changes.

---

## 3. Public API contracts

### 3.1 Schema

```python
class CsvMetadataSourceConfig(BaseModel):
    model_config = _STRICT
    kind: Literal["csv"] = "csv"
    alias: str
    csv_path: FilePath


class As400MetadataSourceConfig(BaseModel):
    model_config = _STRICT
    kind: Literal["as400"]
    alias: str
    as400_connection: As400ConnectionConfig
    table: str = Field(min_length=1)


MetadataSourceConfig = Annotated[
    CsvMetadataSourceConfig | As400MetadataSourceConfig,
    Field(discriminator="kind"),
]
```

`MetadataConfigModel.sources` type signature changes from
`list[MetadataSourceConfig]` (old concrete) to
`list[MetadataSourceConfig]` (now discriminated union alias). The
literal type annotation in the model body needs updating to
`list[MetadataSourceConfig]` referencing the new alias.

### 3.2 Loader

```python
def _inject_default_trigger_kind(data):
    # existing: trigger.kind = "csv" if missing
    trigger = data.get("trigger")
    if isinstance(trigger, dict) and "kind" not in trigger:
        trigger["kind"] = "csv"
    # NEW: metadata.sources[i].kind = "csv" if missing
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        sources = metadata.get("sources")
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict) and "kind" not in source:
                    source["kind"] = "csv"
```

Rename: `_inject_default_trigger_kind` → `_inject_default_kinds`
(scope is wider now). Update the loader's docstring accordingly.

### 3.3 Wiring

```python
def build_pipeline(config, secrets):
    # _reject_unsupported_source_types REMOVED.

    rvabrep_src = TabularDataSource(config.indexing.csv_path)
    mapping_src = TabularDataSource(config.mapping.csv_path)
    metadata_sources = _build_metadata_sources(config.metadata.sources, secrets)
    ...

def _build_metadata_sources(sources, secrets):
    registry: dict[str, IDataSource] = {}
    for src_cfg in sources:
        if isinstance(src_cfg, CsvMetadataSourceConfig):
            registry[src_cfg.alias] = TabularDataSource(src_cfg.csv_path)
            continue
        # as400 — credentials required
        if not secrets.as400_username or not secrets.as400_password:
            raise ConfigurationError(
                "AS400 credentials required for as400 metadata source",
                missing_vars=_missing_as400_vars(secrets),
            )
        registry[src_cfg.alias] = As400DataSource(
            host=src_cfg.as400_connection.host,
            port=src_cfg.as400_connection.port,
            database=src_cfg.as400_connection.database,
            driver=src_cfg.as400_connection.driver,
            username=secrets.as400_username,
            password=secrets.as400_password,
            table=src_cfg.table,
        )
    return registry
```

### 3.4 Doctor

```python
def _check_metadata_sources(config):
    empty_aliases = []
    counts = {}
    for source_cfg in config.metadata.sources:
        try:
            count = _count_metadata_source(source_cfg, secrets)  # NEW signature
            ...
```

Or simpler: extract `_open_metadata_source(source_cfg, secrets) ->
IDataSource` helper used by both wiring and doctor. Doctor wraps
`open + count + close` in a `try/except`.

---

## 4. Test plan

### 4.1 `tests/unit/config/test_schema.py` (~5 new tests)

- csv-kind metadata source loads (existing test re-asserts).
- as400-kind metadata source loads.
- Missing `kind` in a metadata source defaults to `csv` (via the
  loader, not the schema — but the schema test asserts the loaded
  result).
- Unknown `kind` raises.
- `As400MetadataSourceConfig.table` required (empty string raises).

### 4.2 `tests/integration/config/test_wiring.py` (~2 new tests)

- `build_pipeline` with an as400 metadata source builds the
  `As400DataSource` and registers it under the alias.
- `build_pipeline` with as400 metadata source and missing
  `AS400_USERNAME` raises `ConfigurationError`.

### 4.3 `tests/integration/pipeline/test_staged_pipeline.py` (~1 new test)

- A pipeline with a csv trigger + an as400 metadata source (pyodbc
  mocked) runs end-to-end. The CMIS upload payload contains the
  field value resolved from the as400 prefetch cache.

### 4.4 `tests/integration/cli/test_doctor.py` (~1 new test)

- Doctor's `metadata_sources` check PASSes with a mixed config (csv
  + as400 sources).

---

## 5. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..004 (schema) | §3.1 | test_schema |
| REQ-005 (loader) | §3.2 | implicit via test_schema's missing-kind tests |
| REQ-006..008 (wiring) | §3.3 | test_wiring |
| REQ-009..010 (service) | unchanged | implicit via test_staged_pipeline |
| REQ-011 (doctor) | §3.4 | test_doctor |
| REQ-012 (logging) | implicit | code review |

---

## 6. Files touched

```
EDIT  src/cmcourier/config/schema.py
EDIT  src/cmcourier/config/loader.py
EDIT  src/cmcourier/config/wiring.py
EDIT  src/cmcourier/cli/doctor.py
EDIT  tests/unit/config/test_schema.py
EDIT  tests/integration/config/test_wiring.py
EDIT  tests/integration/pipeline/test_staged_pipeline.py
EDIT  tests/integration/cli/test_doctor.py
EDIT  CHANGELOG.md
EDIT  README.md
NEW   specs/015-as400-metadata-source/{spec,plan,tasks}.md
```

No new dependencies. No new modules.

---

## 7. Risks

- **Risk**: Pydantic v2 discriminated unions with `kind` defaults
  are tricky. The trigger union (014) needed the loader-side kind
  injection because Pydantic couldn't pick a default discriminator
  via the schema alone. Same pattern repeats here. Mitigation: copy
  the trigger-side trick.
- **Risk**: prefetching a large as400 table at startup could be
  slow / OOM. 015 accepts this per user direction. Mitigation
  documented in the spec; future per-source `prefetch: bool` flag.
- **Risk**: removing `_reject_unsupported_source_types` exposes the
  metadata service to runtime `KeyError` if a `field_sources`
  entry references an alias not present in `metadata.sources`. The
  MetadataService already raises `ConfigurationError("unknown CSV
  alias")` at prefetch time. Mitigation: that error path already
  covers as400 too (the helper inspects the registry keys).

---

## 8. Estimated effort

- Spec / plan / tasks: done
- Phase 1 (schema): 30 min
- Phase 2 (loader + wiring + doctor): 60 min
- Phase 3 (tests + verification): 60 min
- Phase 4 (docs + commit + merge): 20 min
- **Total**: ~2 h 50 min

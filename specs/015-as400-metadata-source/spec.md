# Spec — 015-as400-metadata-source

**Status**: Draft
**Composition**: Discriminated-union `MetadataSourceConfig` + new
`As400MetadataSourceConfig` + wiring builds `As400DataSource` for
as400 metadata aliases + `MetadataService` prefetch works uniformly
for csv and as400 sources.
**Constitution alignment**: I (the metadata service still imports
only `cmcourier.domain.*` + concrete adapters via the existing
`IDataSource` port — no change), V (config still drives everything),
III (no fat method: prefetch flow remains 1 helper that iterates
`sources_registry.values()`).

---

## 1. Intent

After 014, `As400DataSource` ships but `MetadataService` still
rejects `as400:<alias>` source types via the wiring's
`_reject_unsupported_source_types` guard. 015 closes the hole.

Two discriminated-union refactors land:

1. `MetadataSourceConfig` becomes a tagged union by `kind`
   (`csv` | `as400`). The CSV shape is unchanged in semantics
   (just gains a `kind` field with a default).
2. Wiring constructs the right `IDataSource` per kind:
   `TabularDataSource(csv_path)` for csv-kind sources,
   `As400DataSource(...)` for as400-kind. The `MetadataService`
   never knows which kind it is talking to — it consumes
   `IDataSource.get_all()` uniformly.

Per user direction, AS400 metadata sources **prefetch** identically
to CSV sources (one query at construction; results cached). The
operator is responsible for choosing tables small enough to keep
in memory.

---

## 2. Scope

### In scope

- **Schema**:
  - `MetadataSourceConfig` becomes a `Field(discriminator="kind")`
    union:
    - `CsvMetadataSourceConfig(kind: Literal["csv"] = "csv", alias, csv_path)`
    - `As400MetadataSourceConfig(kind: Literal["as400"], alias, as400_connection, table)`
  - The existing `MetadataSourceConfig` name is preserved as a
    `TypeAlias` for the discriminated union, so code that imports
    `MetadataSourceConfig` keeps working.
  - Loader injects `kind: "csv"` for entries that omit it, matching
    the trigger-discriminator pattern from 014.
- **Wiring**:
  - `build_pipeline` builds `As400DataSource(...)` for each
    `As400MetadataSourceConfig`, using `secrets.as400_username` /
    `secrets.as400_password`. The data source's `table` field
    comes from the metadata source config (NOT from the trigger
    config's `as400_connection.table`).
  - `_reject_unsupported_source_types` is REMOVED. The wiring layer
    now accepts `as400:*` source types in `MetadataConfig.field_sources`.
- **`MetadataService`**:
  - No code change. The prefetch helper already calls
    `IDataSource.get_all()` and stores results in `_csv_cache`. The
    cache key shape (`alias`, `key_column`, `key_value`, `value_column`)
    is naturally agnostic to the underlying data source. The cache's
    private name stays `_csv_cache` for now (rename to
    `_prefetch_cache` is a future cleanup; not in 015).
- **Tests**:
  - 5 schema tests for the discriminated union.
  - 2 wiring tests: as400 metadata source builds correctly; missing
    AS400 secrets raise `ConfigurationError`.
  - 1 end-to-end pipeline test: a pipeline with a `kind=csv` trigger
    + an `as400` metadata source resolves a field through the as400
    prefetch cache. pyodbc mocked.

### Out of scope

- **Per-field `as400_query`**: the spec documents
  `as400_query: "SELECT NOMBRE FROM RVILIB.CLIENT_TABLE WHERE CIF = ?"`
  on each `FieldSourceItem` so different fields can target different
  AS400 tables/joins via the same connection. 015 simplifies: each
  AS400 metadata source maps to ONE table; prefetch is
  `SELECT * FROM <table>`. Per-field custom SQL is a follow-up
  change.
- **Lazy AS400 fetch**: the spec's
  `metadata_prefetch_exclude: ["RVABREP"]` default explicitly
  excludes AS400 from prefetch. 015 prefetches AS400 sources
  by default (per user direction). A future change can add a
  per-source `prefetch: false` flag if it becomes a memory issue.
- **MetadataService rename of `_csv_cache` → `_prefetch_cache`**:
  cosmetic cleanup, not the focus here.

---

## 3. Functional requirements (RFC 2119)

### Schema

- **REQ-001** `MetadataSourceConfig` MUST become a discriminated
  union by `kind`. Two concrete classes:
  - `CsvMetadataSourceConfig(kind: Literal["csv"] = "csv", alias: str, csv_path: FilePath)`
  - `As400MetadataSourceConfig(kind: Literal["as400"], alias: str, as400_connection: As400ConnectionConfig, table: str)`
- **REQ-002** Both concrete classes MUST be `ConfigDict(frozen=True,
  extra="forbid")`.
- **REQ-003** The discriminator's default value (`"csv"`) on
  `CsvMetadataSourceConfig` MUST permit existing 012 configs to
  load without `kind`.
- **REQ-004** `As400MetadataSourceConfig.table` MUST be a required
  non-empty string. The data source runs `SELECT * FROM <table>` at
  prefetch time.

### Loader

- **REQ-005** The loader's existing `_inject_default_trigger_kind`
  helper MUST also inject `kind: "csv"` into every entry of
  `metadata.sources` that lacks one.

### Wiring

- **REQ-006** `build_pipeline` MUST iterate `config.metadata.sources`
  and dispatch on `kind`:
  - `csv`: `TabularDataSource(source_cfg.csv_path)`.
  - `as400`: `As400DataSource(host=..., port=..., database=...,
    driver=..., username=secrets.as400_username,
    password=secrets.as400_password, table=source_cfg.table)`.
- **REQ-007** If any `as400`-kind metadata source is present AND
  `secrets.as400_username` or `secrets.as400_password` is empty, the
  wiring MUST raise `ConfigurationError("AS400 credentials required
  for as400 metadata source", missing_vars=[...])`.
- **REQ-008** The wiring's `_reject_unsupported_source_types` helper
  MUST be REMOVED. `as400:*` `field_sources` entries are now
  legitimate.

### MetadataService

- **REQ-009** No public API change. The constructor still takes
  `(config, sources_registry)`. The prefetch helper continues to
  iterate `sources_registry.values()` and call `get_all()`.
- **REQ-010** The prefetch cache key shape stays unchanged: 
  `(alias, key_column, str(key_value), value_column)`.

### Doctor

- **REQ-011** Doctor's `_check_metadata_sources` already opens each
  source via `TabularDataSource(source_cfg.csv_path)`. After 015 it
  MUST dispatch on `kind`:
  - csv: open `TabularDataSource`.
  - as400: open `As400DataSource` and call `count()` (probes the
    connection + table). If credentials missing, FAIL.

### Logging discipline

- **REQ-012** The AS400 prefetch query MUST NOT be logged. The
  `As400DataSource.query_stream` already complies with Constitution
  VIII; this REQ is reinforcement.

---

## 4. Acceptance scenarios

### 4.1 CSV-only config still loads (backwards-compat)
- Given a YAML with `metadata.sources: [{alias: clients, csv_path: ...}]`.
- When `load_config` runs.
- Then the resulting `MetadataSourceConfig` is `CsvMetadataSourceConfig`
  with `kind="csv"`.

### 4.2 AS400 metadata source loads
- Given a YAML with `metadata.sources: [{kind: as400, alias: customers,
  as400_connection: {host: ...}, table: CUSTOMERS}]`.
- When `load_config` runs.
- Then the resulting source is `As400MetadataSourceConfig` with
  `kind="as400"` and the connection block populated.

### 4.3 Unknown kind rejected
- Given `metadata.sources: [{kind: ldap, alias: directory, ...}]`.
- When `load_config` runs.
- Then `ConfigurationError`.

### 4.4 Wiring builds As400DataSource for as400 metadata source
- Given a config with `kind=csv` trigger + 1 csv metadata source +
  1 as400 metadata source + valid `AS400_USERNAME`/`AS400_PASSWORD`
  env vars.
- When `build_pipeline(config, secrets)` is called.
- Then `metadata_service.sources_registry` has 2 entries: one
  `TabularDataSource` (csv alias) + one `As400DataSource` (as400
  alias).

### 4.5 Wiring rejects missing AS400 secrets
- Given the same config but with `secrets.as400_username == ""`.
- When `build_pipeline` is called.
- Then `ConfigurationError("AS400 credentials required", ...)`.

### 4.6 Pipeline run resolves field via as400 prefetch
- Given a `kind=csv` trigger + an as400 metadata source whose table
  contains (CIF=123456, NAME=JUAN_TEST).
- With pyodbc mocked to return that single row on the prefetch
  query.
- When `pipeline.run(...)` is called.
- Then the resulting CMIS upload's properties carry
  `BAC_Nombre_Cliente="JUAN_TEST"` (resolved from the as400 source).

### 4.7 Doctor handles as400 metadata source
- Given a config with as400 metadata sources + mocked pyodbc.
- When `cmcourier doctor` runs.
- Then `metadata_sources` check is PASS (or WARN if empty).
  `as400_connectivity` check still SKIPs because `trigger.kind=csv`.

### 4.8 field_sources with `as400:<alias>` accepted by wiring
- Given a config whose `BAC_Nombre_Cliente.sources[0].source_type ==
  "as400:customers"` and the registry has an `as400` source aliased
  `customers`.
- When `build_pipeline` runs.
- Then no error. The MetadataService receives the source and the
  field config; the prefetch loop populates the cache from the
  as400 source.

---

## 5. Non-functional requirements

- **NFR-001** Branch coverage on the touched modules stays ≥ 90%.
  No new module ships; the changes are additive in existing files.
- **NFR-002** Method length cap stays ≤ 50 lines.
- **NFR-003** No new runtime dependencies.

---

## 6. Tooling expectations

- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean.
- `pre-commit run --all-files`: clean.
- `pytest`: full suite passes; net positive test count (~8 new).

---

## 7. Open questions / risks

- **Risk**: prefetching a million-row AS400 table is RAM-expensive
  (~100 MB for typical 100-char rows). Per user direction this is
  accepted in 015. Mitigation when it surfaces: add a per-source
  `prefetch: bool` flag and a lazy `_fetch_as400` path.
- **Risk**: `MetadataSourceConfig` rename to a TypeAlias breaks
  `isinstance(x, MetadataSourceConfig)` checks. Mitigation: grep —
  no production code does this; only tests assert on
  `CsvMetadataSourceConfig` and `As400MetadataSourceConfig`
  individually.
- **Open question**: do field sources still need their own discriminator
  for `as400:<alias>` vs `csv:<alias>`? **Resolved**: no — the field's
  `source_type` string already encodes the alias-prefix. The
  MetadataService's `_fetch_from_source` already dispatches on the
  prefix.

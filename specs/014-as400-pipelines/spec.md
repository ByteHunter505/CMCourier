# Spec — 014-as400-pipelines

**Status**: Draft
**Composition**: AS400 ODBC adapter + StagedPipeline rename +
discriminated-union trigger schema + `rvabrep-pipeline` and
`as400-trigger-pipeline` CLI commands + doctor AS400 connectivity check.
**Constitution alignment**: I (new concrete adapter for the IDataSource
port), III (pipeline rename consolidates 5 stage methods into one
generic class — rule of three satisfied with the 2nd pipeline landing),
V (schema enforces shape via discriminated union), VI (AS400 mocked at
pyodbc boundary — no real CMIS AND no real AS400 in tests).

---

## 1. Intent

The MVP today ships ONE pipeline (`csv-trigger-pipeline`). REBIRTH §10.2
lists FOUR production pipelines + one debug. Each differs only in S0.
014 unlocks two more pipelines (`rvabrep`, `as400-trigger`) by:

1. Implementing the real AS400 ODBC adapter (`As400DataSource`) — the
   blocker for every `as400:*` source type and the `as400-trigger-pipeline`.
2. Renaming `CsvTriggerPipeline` → `StagedPipeline` (one generic class,
   S0 inyectable). Constitution III rule of three: with 2+ pipelines
   sharing the stage skeleton, the abstraction is earned.
3. Schema discriminated union: `trigger.kind: "csv" | "rvabrep" | "as400"`.
   The CLI command name + the config's `kind` field together select the
   S0 strategy. The wiring layer dispatches.
4. Two new CLI commands: `rvabrep-pipeline run` and
   `as400-trigger-pipeline run` — both wrap `StagedPipeline.run` with
   the appropriate S0.
5. Doctor amendment: if `config.trigger.kind == "as400"`, doctor adds an
   `as400_connectivity` check (pyodbc connect + `SELECT 1`).

**Out of scope** (separate change after 014):
- `MetadataService.as400:<alias>` source resolution — needs an AS400
  connection registered as a metadata source. Today it
  `raise NotImplementedError`; 014 keeps that, the future change wires it.
- Thread-local AS400 connections (post-MVP per REBIRTH §3.1 — current
  pipeline is single-threaded).
- `local-scan-pipeline` and `single-doc` — separate changes each.

---

## 2. Scope

### In scope

- **`cmcourier.adapters.sources.as400.As400DataSource`** — concrete
  `IDataSource` over pyodbc. Constructor takes the connection params
  + a target `table` (used by `get_all` / `count` / `get_by_fields`).
  Methods: `query`, `query_stream`, `get_by_fields`, `get_by_fields_in`
  (with IN-list chunking per REBIRTH §10.1), `get_all`, `count`, `close`.
- **Rename `CsvTriggerPipeline` → `StagedPipeline`** in a new module
  `cmcourier/orchestrators/staged.py` (the old module name
  `csv_trigger.py` re-exports for backwards compatibility within the
  test suite — DELETED at the end of 014 once tests are updated).
  Constructor signature unchanged. The class is the generic pipeline;
  the trigger strategy is injected.
- **`As400TriggerStrategy` becomes real** (replaces the stub in
  `services/triggers/stubs.py`): runs a configured SQL query over an
  AS400 data source, yields `TriggerRecord`s. Moves to
  `services/triggers/as400.py`.
- **Schema discriminated union**: `TriggerConfig` becomes a tagged
  union with `kind: Literal["csv", "rvabrep", "as400"]` discriminator.
  Three concrete classes: `CsvTriggerConfig`, `RvabrepTriggerConfig`,
  `As400TriggerConfig`.
- **`As400ConnectionConfig`** new schema block — `host`, `port`,
  `database`, `driver`. Credentials still env-only (Constitution VIII).
- **CLI commands**:
  - `cmcourier rvabrep-pipeline run` — flags identical to
    `csv-trigger-pipeline run`; the schema's `trigger.kind` MUST be
    `"rvabrep"` (mismatch → exit 2).
  - `cmcourier as400-trigger-pipeline run` — same shape; `trigger.kind`
    MUST be `"as400"`.
- **Doctor amendment**: `_check_as400_connectivity` runs when
  `config.trigger.kind == "as400"`, performs `pyodbc.connect(...)` +
  `SELECT 1`. PASS / FAIL / SKIP if `kind != "as400"`.
- **Wiring**: `build_pipeline(config, secrets)` dispatches on
  `config.trigger.kind` to construct the right S0 strategy. The rest
  of the adapter graph is identical.
- **Test pattern for AS400**: `unittest.mock.patch("pyodbc.connect")`
  returns a `_FakeAs400Connection` whose `cursor()` returns a
  `_FakeAs400Cursor` with scriptable `execute` / `fetchone` /
  `fetchmany` / `description` / `close`.

### Out of scope

- **MetadataService.as400:<alias>** resolution — kept raising
  `NotImplementedError("as400 metadata source not yet supported")`.
  When the operator configures a metadata field whose source is
  `as400:default`, the wiring still rejects it at `build_pipeline`
  time (Constitution V — config valid is not enough; the consumer
  must be ready).
- Thread-local connections — `As400DataSource` holds ONE connection.
  `close()` closes it. Future change adds `threading.local()` when
  the orchestrator's worker pool lands.
- `local-scan-pipeline` and `single-doc` — separate changes.
- Pyodbc connection-string crafting subtleties (UID/PWD vs separate
  parameters, SSL toggles, character set negotiation) — the adapter
  accepts a flat `(host, port, database, driver, username, password)`
  tuple and builds the simplest valid connection string. Anything
  fancier lives in a config-template helper or a future change.

---

## 3. Functional requirements (RFC 2119)

### `As400DataSource`

- **REQ-001** Constructor signature:
  `As400DataSource(host, port, database, driver, username, password, table)`.
  All required, all strings (except `port: int`). MUST NOT connect
  during construction — `_connect()` lazily on first call to a public
  method.
- **REQ-002** Connection string format:
  `"DRIVER={<driver>};SYSTEM=<host>;PORT=<port>;DATABASE=<database>;
  UID=<username>;PWD=<password>;"`. MUST escape neither braces nor
  characters within `driver` (operator's responsibility — driver names
  with embedded `;` are unsupported).
- **REQ-003** Every public method MUST raise the existing
  `cmcourier.domain.exceptions.IndexingError` on pyodbc failures,
  wrapping the original exception via `__cause__`. The wrapping
  preserves the SQL state code as `details["sqlstate"]` when present.
- **REQ-004** `query(sql, params=None) -> list[dict[str, Any]]` MUST
  execute the SQL via `cursor.execute(sql, params or [])`, read
  `cursor.description` for column names, and materialize all rows as
  dicts (column → value).
- **REQ-005** `query_stream(sql, params=None) -> Iterator[dict[str, Any]]`
  MUST yield rows lazily via `cursor.fetchmany(batch_size=500)`.
- **REQ-006** `get_by_fields(filters)` MUST build a `SELECT * FROM
  <table> WHERE <col1>=? AND <col2>=? ...` query with parameter
  placeholders bound positionally. Order-sensitive iteration over
  `filters.items()` defines the parameter order.
- **REQ-007** `get_by_fields_in(field, values, fixed_filters)` MUST
  chunk `values` into groups of at most 1000 and issue one query per
  chunk with `WHERE <field> IN (?, ?, ...) AND <fixed1>=? ...`.
  Materializes the union of chunk results.
- **REQ-008** `get_all() -> Iterator[dict]` MUST execute
  `SELECT * FROM <table>` and yield via `fetchmany(500)`.
- **REQ-009** `count() -> int` MUST execute
  `SELECT COUNT(*) FROM <table>` and return the integer.
- **REQ-010** `close()` MUST close cursor + connection if open.
  Idempotent: calling twice is a no-op.

### Pipeline class rename

- **REQ-011** Create `cmcourier/orchestrators/staged.py` containing
  `StagedPipeline` (the class formerly known as `CsvTriggerPipeline`).
  All other types in `csv_trigger.py` (`RunReport`, `_StageItem`)
  move with it.
- **REQ-012** `cmcourier/orchestrators/csv_trigger.py` is DELETED. The
  package `__init__.py` exports `StagedPipeline` + `RunReport`.
  `CsvTriggerPipeline` is NOT preserved as an alias — the doctor's
  private-attribute access (`pipeline._trigger_strategy`) keeps
  working because the constructor signature is unchanged.
- **REQ-013** Every test file referencing `CsvTriggerPipeline` MUST be
  updated to `StagedPipeline` in the same change.

### Schema discriminated union

- **REQ-014** `TriggerConfig` becomes a `pydantic.discriminator`
  union:
  - `CsvTriggerConfig` with `kind: Literal["csv"] = "csv"`, plus the
    existing fields (`csv_path`, columns).
  - `RvabrepTriggerConfig` with `kind: Literal["rvabrep"] = "rvabrep"`,
    `filters: RvabrepFiltersModel | None = None`,
    `as400_connection: As400ConnectionConfig | None = None`
    (the RVABREP source itself; rvabrep-pipeline reads it via
    `As400DataSource` OR through the existing
    `IndexingSourceConfig.csv_path` — the latter is the test pattern,
    the former is production).
  - `As400TriggerConfig` with `kind: Literal["as400"] = "as400"`,
    `query: str`, `as400_connection: As400ConnectionConfig`.
- **REQ-015** `As400ConnectionConfig` new schema:
  ```python
  class As400ConnectionConfig(BaseModel):
      host: str
      port: int = 446
      database: str = "RVILIB"
      driver: str = "iSeries Access ODBC Driver"
      table: str | None = None  # required for rvabrep_source; None for trigger queries
  ```
- **REQ-016** The discriminator `kind` MUST be a `Literal` type so
  Pydantic v2 can validate the union via
  `Field(discriminator="kind")` on `PipelineConfig.trigger`.
- **REQ-017** Existing configs without `kind` MUST still load —
  default `kind="csv"` (backwards-compatible alias).

### Wiring

- **REQ-018** `build_pipeline(config, secrets)` MUST dispatch on
  `config.trigger.kind`:
  - `"csv"` → existing `CsvTriggerStrategy` over `TabularDataSource`
    (no change).
  - `"rvabrep"` → existing `DirectRvabrepTriggerStrategy` over the
    existing indexing source (CSV in tests, AS400 in prod).
  - `"as400"` → real `As400TriggerStrategy` over
    `As400DataSource(config.trigger.as400_connection, secrets, query=trigger.query)`.
- **REQ-019** `build_pipeline` MUST raise `ConfigurationError` if
  `kind == "as400"` AND `secrets.as400_username` is empty (per the
  reservation in 012's `load_secrets`).

### CLI commands

- **REQ-020** `cmcourier rvabrep-pipeline run` — Click command with the
  same flag set as `csv-trigger-pipeline run`. The command verifies
  `config.trigger.kind == "rvabrep"` after `load_config` and exits 2
  with a clear message if not.
- **REQ-021** `cmcourier as400-trigger-pipeline run` — same shape; the
  `kind` must be `"as400"`.
- **REQ-022** Both commands reuse the existing run-time flow:
  `_apply_overrides`, `_emit_summary`, exit codes 0/1/2/3.

### Doctor

- **REQ-023** New check `_check_as400_connectivity(config, secrets)`:
  - If `config.trigger.kind != "as400"`: returns SKIP with
    `reason="trigger_kind_not_as400"`.
  - Else: opens an `As400DataSource(...)` with credentials from
    secrets, calls `count()` (which runs `SELECT COUNT(*) FROM <table>`
    when `table` is set, else runs `SELECT 1` as a connectivity probe).
    Returns PASS if no exception. FAIL otherwise.
- **REQ-024** `run_doctor` MUST insert the new check between
  `cmis_connectivity` and `tracking_openable` (so connectivity
  failures cluster at the top of the report).

### Logging discipline

- **REQ-025** AS400 SQL queries MUST NOT be logged at any level
  unless explicitly enabled in a future debug-logging change.
  Parameters passed to `query()` MAY contain CIFs / names —
  Principle VIII forbids logging them.

---

## 4. Acceptance scenarios

### 4.1 AS400DataSource happy path
- Given a `_FakeAs400Cursor` that returns 3 rows on `execute`.
- When `As400DataSource(...).query("SELECT * FROM T", [])` is called.
- Then 3 dicts are returned with the correct column → value mapping.

### 4.2 AS400DataSource IN-list chunking
- Given a `get_by_fields_in("CIF", values=list(range(1500)), fixed_filters={})`.
- When called with `chunk_size=1000` (the constant).
- Then `cursor.execute` is called twice — once with 1000 values, once
  with 500.

### 4.3 AS400DataSource error wrapping
- Given a cursor that raises `pyodbc.Error` on `execute`.
- When any public method is called.
- Then `IndexingError` is raised; the `pyodbc.Error` is the `__cause__`.

### 4.4 AS400DataSource close idempotent
- Given an `As400DataSource` with an open connection.
- When `.close()` is called twice.
- Then no exception is raised; subsequent calls are no-ops.

### 4.5 StagedPipeline runs csv-kind config
- Given a config with `trigger.kind == "csv"` (or no `kind` at all).
- When `build_pipeline(config, secrets)` is called.
- Then a `StagedPipeline` is returned; `pipeline.run(...)` succeeds
  end-to-end against the existing pipeline fixtures + responses-mocked
  CMIS.

### 4.6 StagedPipeline runs rvabrep-kind config
- Given a config with `trigger.kind == "rvabrep"`, no `as400_connection`
  (the pipeline reads from the existing CSV-mocked indexing source),
  and `filters.systems=["1"], filters.document_types=["FF17"]`.
- When `build_pipeline(config, secrets)` is called and the pipeline
  runs against the existing rvabrep CSV fixture.
- Then the orchestrator discovers triggers via
  `DirectRvabrepTriggerStrategy`, processes them through S1-S5, and
  `RunReport.s5_done > 0`.

### 4.7 StagedPipeline runs as400-kind config
- Given a config with `trigger.kind == "as400"`, an
  `as400_connection`, and `query == "SELECT SHORTNAME, CIF, SYSTEMID FROM TRIGGERS"`.
- With `pyodbc.connect` mocked to return a fake cursor that yields
  3 trigger rows.
- When `pipeline.run(...)` is invoked (CMIS mocked, RVABREP-CSV
  mocked).
- Then `RunReport.total_triggers == 3` and S5_done equals the number
  of matched docs.

### 4.8 Schema discriminated union accepts all three kinds
- Given three YAML configs (one per `kind`).
- When loaded.
- Then each `PipelineConfig.trigger` has the correct concrete type
  (`CsvTriggerConfig`, `RvabrepTriggerConfig`, `As400TriggerConfig`).

### 4.9 Schema rejects mismatched fields
- Given a YAML with `trigger.kind: "csv"` but a `filters` field.
- When loaded.
- Then `ConfigurationError` with a Pydantic validation error.

### 4.10 Schema defaults to csv kind for backwards compat
- Given a YAML without `kind` at all.
- When loaded.
- Then `PipelineConfig.trigger.kind == "csv"`.

### 4.11 `cmcourier rvabrep-pipeline run --config <yaml>` happy path
- Given a `kind: rvabrep` YAML + mocked CMIS.
- When invoked.
- Then exit 0; stdout has `s5_done=...`.

### 4.12 `rvabrep-pipeline` rejects csv-kind config
- Given a YAML with `kind: csv`.
- When invoked via `cmcourier rvabrep-pipeline run --config`.
- Then exit 2; stderr names the mismatch.

### 4.13 `as400-trigger-pipeline run` happy path
- Same as 4.7 but via the CLI.

### 4.14 Doctor adds as400_connectivity for kind=as400
- Given `kind: as400` + mocked pyodbc.
- When `cmcourier doctor --config` runs.
- Then 7 results are present (one more than today). The new check is
  `as400_connectivity`, status PASS.

### 4.15 Doctor SKIPs as400_connectivity for kind=csv
- Given `kind: csv` (or no kind).
- When doctor runs.
- Then `as400_connectivity` is SKIP with
  `reason="trigger_kind_not_as400"`.

---

## 5. Non-functional requirements

- **NFR-001** Branch coverage on the new modules MUST be combined ≥
  85%:
  - `adapters/sources/as400.py`
  - `orchestrators/staged.py`
  - The new `services/triggers/as400.py` (real strategy)
- **NFR-002** Method length cap (Constitution III): every method ≤ 50
  lines.
- **NFR-003** `cmcourier --help` MUST list FOUR commands: `doctor`,
  `csv-trigger-pipeline`, `rvabrep-pipeline`, `as400-trigger-pipeline`.
- **NFR-004** No new runtime dependencies; `pyodbc` already in
  pyproject.

---

## 6. Tooling expectations

- `ruff check src/ tests/`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean.
- `pre-commit run --all-files`: clean.
- `pytest`: full suite passes; net positive test count (~25 new).
- Smoke: `cmcourier rvabrep-pipeline --help`,
  `cmcourier as400-trigger-pipeline --help`.

---

## 7. Open questions / risks

- **Risk**: pyodbc availability on developer machines. Tests use
  `unittest.mock.patch("pyodbc.connect")` so the real driver is not
  needed. The import itself can fail on environments without the
  unixodbc headers — Constitution constraint already documents this.
- **Risk**: connection-string crafting is environment-specific (some
  AS400 servers want `SYSTEM=`, others `HOSTNAME=`). 014 ships the
  simplest form; future tests against staging will surface real
  needs. Mitigation: the connection string is built inside
  `_connect()` which is mockable.
- **Risk**: `pyodbc.Error` hierarchy is rich (DatabaseError,
  OperationalError, IntegrityError, etc.). The wrapper catches the
  parent `pyodbc.Error`. The SQLSTATE is extracted from `exc.args[0]`
  when available — this format is pyodbc-specific and may vary.
  Mitigation: the wrapper degrades gracefully (no sqlstate in
  details if extraction fails).
- **Risk**: The discriminated-union refactor breaks existing config
  YAMLs in the test suite that don't set `kind`. Mitigation:
  REQ-017 — `kind` defaults to `"csv"`. Existing YAMLs continue to
  load unchanged.
- **Open question**: should `As400DataSource.table` be required at
  construction, or settable per-call? **Resolved**: required at
  construction. The data source is bound to one table (RVABREP for
  the indexing pipeline; whatever table the trigger query targets
  for the trigger pipeline). Per-call SQL via `query()` is the
  escape hatch.
- **Open question**: should the discriminator default to `"csv"` for
  backwards-compat OR force every config to be explicit?
  **Resolved**: default to `"csv"` for backwards-compat in 014.
  Future config-validation hardening can flip the default later.

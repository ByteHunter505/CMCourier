# Spec — 012-cli-config

**Status**: Draft
**Composition**: Pydantic v2 config schema + YAML loader + adapter factory + Click CLI for `csv-trigger-pipeline run`.
**Constitution alignment**: V (config is single source of truth — YAML
validated by Pydantic at startup, env vars for secrets), VIII (credentials
NEVER appear in YAML — only env vars), III (each layer is single-purpose:
schema, loader, factory, command).

---

## 1. Intent

Expose `CsvTriggerPipeline` to operators via a CLI command. Without this
layer, the orchestrator (change 011) is only callable from Python — usable
for tests but not deployable.

Three thin layers compose into one runnable command:

1. **`src/cmcourier/config/schema.py`** — Pydantic v2 models that
   describe the full pipeline configuration.
2. **`src/cmcourier/config/loader.py`** — reads a YAML file into the
   schema; reads credentials from environment variables; returns a
   `(PipelineConfig, Secrets)` pair.
3. **`src/cmcourier/config/wiring.py`** — turns
   `(PipelineConfig, Secrets)` into a wired `CsvTriggerPipeline`.
4. **`src/cmcourier/cli/app.py`** — Click group exposing
   `cmcourier csv-trigger-pipeline run --config <yaml>` plus minimal
   logging setup driven by `--log-level`.

After this change, an operator runs:

```
export CMIS_USERNAME=tester
export CMIS_PASSWORD=secret
cmcourier csv-trigger-pipeline run --config config/config.yaml
```

---

## 2. Scope

### In scope

- **Pydantic v2 schema** with frozen models for every config segment:
  trigger CSV path + columns, indexing source (CSV path + column map),
  mapping (CSV path + column map), metadata (field aliases + per-field
  source chain + sources registry), assembly (source_root + temp_dir +
  image_type_map), CMIS (base_url + repo_id + retry knobs +
  bandwidth), tracking (sqlite db path), batch_size.
- **YAML loader** with strict mode: unknown YAML keys raise. Missing
  required fields raise with a path-style error message. Numeric /
  enum coercions are explicit (no implicit `int(str)` cast surprises).
- **Env-var secrets reader**: `load_secrets()` reads `CMIS_USERNAME`
  and `CMIS_PASSWORD`. Missing or empty values raise
  `ConfigurationError`. `AS400_USERNAME` / `AS400_PASSWORD` reserved
  but optional (read if present, ignored otherwise — for the future
  AS400 adapter).
- **`build_pipeline(config, secrets) -> CsvTriggerPipeline`**: pure
  function. No I/O at this layer — instantiates `TabularDataSource`
  per CSV path, wires every service / adapter, returns the pipeline.
- **Click CLI** at `cmcourier/cli/app.py`:
  - Root group `cmcourier` with one sub-group `csv-trigger-pipeline`
    with one command `run`.
  - `run` flags: `--config PATH` (required), `--batch-id TEXT`
    (optional), `--from-stage INT` (default 1), `--batch-size INT`
    (overrides config if given), `--triggers PATH` (overrides config
    trigger csv if given), `--log-level [DEBUG|INFO|WARNING|ERROR]`
    (default INFO).
- **Logging setup**: `cmcourier.cli.logging_setup.configure(level)`
  installs a stderr `StreamHandler` with format
  `%(asctime)s %(levelname)s %(name)s: %(message)s`. The setup
  function is called once at the start of every CLI command.
- **`cmcourier --help`**: lists the pipeline group; `cmcourier
  csv-trigger-pipeline run --help` lists every flag with its
  description.
- **End-to-end CLI test**: a `tests/integration/cli/test_cli.py`
  smoke test that uses `click.testing.CliRunner` to invoke
  `cmcourier csv-trigger-pipeline run --config <yaml>` against the
  pipeline fixtures from change 011, with `responses` mocking CMIS.

### Out of scope

- Other pipelines (`rvabrep-pipeline`, `as400-trigger-pipeline`,
  `local-scan-pipeline`, `single-doc`) — each lands as its own change
  but reuses 011's stage skeleton and 012's CLI / config plumbing.
- The full REBIRTH §11 CLI tree (`batch list/status/retry-failed`,
  `doctor`, `inspect`) — separate change.
- `pydantic-settings` library — secrets read manually per user
  direction.
- Logging tiers (REBIRTH §17.4 application/pipeline/network/system/
  slow-ops) — separate change. 012 ships a single stderr handler.
- AS400 ODBC adapter — config schema reserves `as400` fields as
  optional but the adapter does not yet exist; passing AS400 source
  types raises `ConfigurationError("not_yet_supported")`.
- File rotation, JSON logging, structured trace IDs — separate change.
- Config-file watch / hot-reload — out of scope.

---

## 3. Functional requirements (RFC 2119)

### Dependencies

- **REQ-001** `pyproject.toml` MUST add `"PyYAML>=6.0,<7.0"` to runtime
  dependencies. No new dev deps.

### Pydantic schema

- **REQ-002** Every config model MUST be a Pydantic v2 `BaseModel`
  with `model_config = ConfigDict(frozen=True, extra="forbid")` so
  unknown YAML keys raise.
- **REQ-003** Path fields MUST use `pydantic.types.FilePath` for
  required-to-exist inputs (modelo doc CSV, RVABREP CSV, trigger CSV,
  metadata source CSVs, assembly source_root) AND `pathlib.Path` for
  outputs (temp_dir, sqlite db) — the latter may not exist yet at
  load time.
- **REQ-004** The top-level `PipelineConfig` MUST aggregate:
  `trigger: TriggerCsvConfig`, `indexing: IndexingSourceConfig`,
  `mapping: MappingConfig`, `metadata: MetadataConfigModel`,
  `assembly: AssemblyConfig`, `cmis: CmisConfigModel`,
  `tracking: TrackingConfig`, `batch_size: int = 1000` (with
  `Field(ge=1)`).
- **REQ-005** `MetadataConfigModel` MUST accept a `sources: list[MetadataSourceConfig]`
  where each item has `alias: str` + `csv_path: FilePath`, plus
  `field_aliases: dict[str, str] = {}` and `field_sources:
  dict[str, FieldConfig]`. `FieldConfig` MUST have `sources:
  list[FieldSourceItem]` (at least one) and an optional `default_value`.
- **REQ-006** `FieldSourceItem.source_type` MUST validate against the
  allowed prefixes: `trigger`, `rvabrep`, `csv:<alias>`. Any other
  value MUST raise during schema validation.
- **REQ-007** `CmisConfigModel` MUST include `base_url: str`,
  `repo_id: str`, `timeout_seconds: float = 300.0`,
  `verify_ssl: bool = False`, `max_bandwidth_mbps: float = 0.0`
  (`Field(ge=0)`), `retry_max_attempts: int = 3` (`Field(ge=1)`),
  `retry_base_delay_s: float = 2.0` (`Field(ge=0)`). Credentials are
  NOT in the schema (env-var only — REQ-013).

### YAML loader

- **REQ-008** `load_config(path: Path) -> PipelineConfig` MUST read
  the YAML file with `yaml.safe_load`, then construct
  `PipelineConfig.model_validate(data)`. The default loader MUST NOT
  permit `!!python/object` tags (`safe_load` enforces this).
- **REQ-009** Missing `path` raises `ConfigurationError(message,
  config_path=...)`.
- **REQ-010** Invalid YAML syntax raises `ConfigurationError(message,
  reason=...)` wrapping the underlying `yaml.YAMLError`.
- **REQ-011** Pydantic validation failure raises
  `ConfigurationError(message, errors=...)` with the list of
  Pydantic error dicts attached for diagnosability.

### Secrets reader

- **REQ-012** `load_secrets() -> Secrets` MUST read `CMIS_USERNAME`
  and `CMIS_PASSWORD` from `os.environ`. Both MUST be non-empty;
  missing or empty raises `ConfigurationError(message,
  missing_vars=[...])`.
- **REQ-013** `Secrets` MUST be a `frozen=True, slots=True` dataclass
  with `cmis_username: str`, `cmis_password: str`. `as400_username`
  and `as400_password` MAY be present (read if env vars set, empty
  strings otherwise — reserved for future AS400 adapter).

### Adapter factory

- **REQ-014** `build_pipeline(config, secrets) -> CsvTriggerPipeline`
  MUST construct all collaborators and return the wired pipeline:
  - `TabularDataSource` instances for trigger CSV, RVABREP CSV, mapping
    CSV, each metadata source CSV.
  - `CsvTriggerStrategy`, `IndexingService`, `MappingService`,
    `MetadataService` (config translated from Pydantic into the
    service's existing `MetadataConfig` shape).
  - `PdfAssembler` with `AssemblerConfig` from the schema.
  - `CmisUploader` with `CmisConfig` populated from the schema +
    secrets.
  - `SQLiteTrackingStore` at `config.tracking.db_path`.
- **REQ-015** `build_pipeline` MUST raise `ConfigurationError` if any
  `FieldSourceItem.source_type` is `as400:<alias>` (not yet supported
  in MVP). The error MUST name the field and the unsupported source
  type.
- **REQ-016** `build_pipeline` MUST be a pure function — repeated
  calls with the same `(config, secrets)` MUST produce equivalent
  pipeline objects (distinct instances are fine; equivalence is by
  field equality of the configs).

### CLI command

- **REQ-017** The Click root group MUST be named `cmcourier` and MUST
  be registered as the `cmcourier` console script in `pyproject.toml`
  (already wired).
- **REQ-018** The sub-group MUST be `csv-trigger-pipeline` (matching
  REBIRTH §11 pipeline-as-command convention).
- **REQ-019** The `run` command MUST accept the following Click
  options:
  - `--config PATH` — required; passed to `load_config`.
  - `--batch-id TEXT` — optional; default `None`.
  - `--from-stage INT` — default 1; passed to `run(from_stage=...)`.
  - `--batch-size INT` — optional; overrides `config.batch_size` if
    given.
  - `--triggers PATH` — optional; overrides `config.trigger.csv_path`
    if given.
  - `--log-level [DEBUG|INFO|WARNING|ERROR]` — default `INFO`.
- **REQ-020** The command MUST:
  1. Call `logging_setup.configure(level)` first.
  2. Call `load_config(config_path)`; on `ConfigurationError` print
     the error to stderr and exit with code 2.
  3. Call `load_secrets()`; on `ConfigurationError` print + exit 2.
  4. Apply CLI overrides for `batch_size` and `triggers` to the
     loaded config (constructing an updated `PipelineConfig` via
     Pydantic `model_copy(update=...)` so frozen-ness is preserved).
  5. Call `build_pipeline(config, secrets)`.
  6. Call `pipeline.run(source_descriptor=str(triggers_path),
     batch_size=batch_size, batch_id=batch_id,
     from_stage=from_stage)`.
  7. Print a structured summary line to stdout containing
     `batch_id`, `total_docs`, `s5_done`, `s5_failed`,
     `elapsed_seconds`.
  8. Exit 0 if `report.s5_failed == 0`, else exit 1.
- **REQ-021** Any unhandled exception inside the command MUST be
  caught, logged at ERROR (with stack), and the command MUST exit
  with code 3.
- **REQ-022** `cmcourier --help` and `cmcourier csv-trigger-pipeline
  run --help` MUST show flag descriptions.

### Logging setup

- **REQ-023** `logging_setup.configure(level: str) -> None` MUST
  install a `StreamHandler(sys.stderr)` on the root logger with
  format `%(asctime)s %(levelname)s %(name)s: %(message)s` and the
  given level. Subsequent calls MUST replace existing handlers (so
  re-invocation in tests is safe).
- **REQ-024** The setup MUST NOT touch loggers other than the root —
  no per-module silencing, no Pillow/PIL muting (out of scope for 012;
  the tier-based config is a future change).

---

## 4. Acceptance scenarios

### 4.1 Valid YAML loads into PipelineConfig
- Given a YAML file matching the schema.
- When `load_config(path)` is called.
- Then a `PipelineConfig` instance is returned with the expected
  fields populated.

### 4.2 Unknown top-level key raises
- Given a YAML file with an extra `cosmic_settings` top-level key.
- When `load_config(path)` is called.
- Then `ConfigurationError` is raised; its `errors` context contains
  the offending key.

### 4.3 Missing required field raises with path
- Given a YAML missing `cmis.base_url`.
- When `load_config(path)` is called.
- Then `ConfigurationError` is raised; the message identifies
  `cmis.base_url` as missing.

### 4.4 Invalid source_type raises during validation
- Given a `field_sources.BAC_X.sources[0].source_type` of `"http:remote"`.
- When `load_config(path)` is called.
- Then `ConfigurationError` is raised; the error names the offending
  source type.

### 4.5 `load_secrets()` reads env vars
- Given `CMIS_USERNAME=u`, `CMIS_PASSWORD=p` in env.
- When `load_secrets()` is called.
- Then `Secrets(cmis_username='u', cmis_password='p')` is returned.

### 4.6 Missing secret raises
- Given `CMIS_USERNAME` unset.
- When `load_secrets()` is called.
- Then `ConfigurationError` is raised; `missing_vars` includes
  `CMIS_USERNAME`.

### 4.7 `build_pipeline` produces a working pipeline
- Given a valid config that points at the pipeline test fixtures
  + valid secrets.
- When `build_pipeline(config, secrets)` is called.
- Then a `CsvTriggerPipeline` is returned; calling `.run(...)`
  against `responses`-mocked CMIS produces `RunReport.s5_done > 0`.

### 4.8 `build_pipeline` rejects unsupported AS400 source type
- Given a config with `field_sources.BAC_X.sources[0].source_type = "as400:default"`.
- When `build_pipeline(config, secrets)` is called.
- Then `ConfigurationError` is raised naming the field and the
  unsupported source type.

### 4.9 CLI `run` happy path
- Given a YAML config + env vars + `responses`-mocked CMIS.
- When `runner.invoke(app, ["csv-trigger-pipeline", "run", "--config", str(yaml)])`
  is called.
- Then exit code is 0; stdout contains a summary line with
  `s5_done=` and `batch_id=`; stderr contains the logging records.

### 4.10 CLI exit code 2 on bad config
- Given a missing YAML file.
- When `runner.invoke(...)` is called.
- Then exit code is 2; stderr contains "ConfigurationError" and the
  offending path.

### 4.11 CLI exit code 1 on stage failures
- Given a config that points at the unmapped-trigger fixture (every
  doc fails S2).
- When `runner.invoke(...)` is called.
- Then exit code is 1 (some `s5_failed`/upstream failures); the
  stdout summary shows `s5_done=0`.

### 4.12 `--triggers` overrides config path
- Given a config whose `trigger.csv_path` is one CSV; the CLI invoked
  with `--triggers other.csv`.
- When the run completes.
- Then the pipeline used `other.csv` as the trigger source. Test
  asserts via the resulting `migration_log` rows / `RunReport.total_triggers`.

### 4.13 `--batch-id` + `--from-stage` resume an existing batch
- Given a prior run that produced a batch.
- When the CLI is invoked again with `--batch-id <id> --from-stage 3`.
- Then the run reuses the batch; idempotent resume semantics hold.

### 4.14 `--log-level DEBUG` enables debug output
- Given any valid config + a `--log-level DEBUG` flag.
- When the command runs.
- Then stderr contains records at DEBUG level (verified via caplog or
  by `runner.invoke` capturing stderr).

---

## 5. Non-functional requirements

- **NFR-001** Module length cap (Constitution III): each new module
  ≤ 200 lines, each method ≤ 50 lines.
- **NFR-002** Branch coverage on the four new modules MUST be ≥ 85%
  combined.
- **NFR-003** The CLI invocation overhead (import + setup, before
  `pipeline.run`) MUST stay under 1 second on a warm Python on the
  developer's machine. Verified informally — no automated test.

---

## 6. Tooling expectations

- `ruff check src/ tests/`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean.
- `pre-commit run --all-files`: clean.
- `pytest`: full suite passes; net positive test count.

---

## 7. Open questions / risks

- **Risk**: `pydantic.FilePath` validates path existence at schema
  construction. For tests using `tmp_path`, the file must be created
  BEFORE `model_validate` runs. Mitigation: every test writes fixtures
  before calling `load_config`.
- **Risk**: Click's `CliRunner` runs the command in the same process;
  if logging is reconfigured, subsequent tests inherit the state.
  Mitigation: `logging_setup.configure` replaces existing root
  handlers, so a fresh call between tests resets cleanly. A pytest
  autouse fixture in the CLI test module resets logging at teardown.
- **Risk**: the metadata schema in the YAML is naturally nested
  (sources → field_sources → field → sources list). Pydantic v2's
  error messages might be hard to read for operators. Mitigation:
  `ConfigurationError.errors` includes the full Pydantic error list
  — the CLI prints them line-by-line.
- **Open question**: should `--config` default to `./config/config.yaml`?
  **Resolved**: no — explicit is better. The operator passes the path
  in every invocation. A shell alias in deployment scripts fills the
  ergonomics gap.
- **Open question**: should `print` lines from the CLI go to stdout
  (machine-readable summary) or stderr (human-readable status)?
  **Resolved**: stdout for the summary line (one JSON-like KV
  format), stderr for everything else (logging). Operators who pipe
  stdout to a logfile get the summary; everything else is interactive.

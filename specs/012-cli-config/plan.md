# Plan — 012-cli-config

**Status**: Draft
**Spec**: `specs/012-cli-config/spec.md`

---

## 1. Architecture in one paragraph

Four small modules layered on top of the existing orchestrator and
adapters: (1) `config/schema.py` declares Pydantic v2 models, (2)
`config/loader.py` reads YAML + env vars into the schema, (3)
`config/wiring.py` turns the schema into a wired `CsvTriggerPipeline`,
(4) `cli/app.py` is the Click entry point that ties them together. No
new dependencies except PyYAML. Logging setup lives in
`cli/logging_setup.py` as a single function so the CLI tests can
reset state between invocations.

---

## 2. Module layout

```
src/cmcourier/
├── config/
│   ├── __init__.py             # re-exports PipelineConfig, Secrets, load_config, load_secrets
│   ├── schema.py               # Pydantic v2 models
│   ├── loader.py               # load_config + load_secrets + Secrets
│   └── wiring.py               # build_pipeline(config, secrets) -> CsvTriggerPipeline
└── cli/
    ├── __init__.py
    ├── app.py                  # Click root + csv-trigger-pipeline run command
    └── logging_setup.py        # configure(level)
```

All modules ≤ 200 lines; all methods ≤ 50 lines.

---

## 3. Public API contracts

### 3.1 `config/schema.py`

```python
class TriggerCsvConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    csv_path: FilePath
    shortname_column: str = "ShortName"
    cif_column: str = "CIF"
    system_id_column: str = "SystemID"


class IndexingColumnsModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    shortname_column: str = "ABABCD"
    system_id_column: str = "ABAACD"
    delete_code_column: str = "ABACST"
    txn_num_column: str = "ABAANB"
    index2_column: str = "ABACCD"
    index3_column: str = "ABADCD"
    index4_column: str = "ABAECD"
    index5_column: str = "ABAFCD"
    index6_column: str = "ABAGCD"
    index7_column: str = "ABAHCD"
    image_type_column: str = "ABABST"
    image_path_column: str = "ABAICD"
    file_name_column: str = "ABAJCD"
    creation_date_column: str = "ABAADT"
    last_view_date_column: str = "ABABDT"
    total_pages_column: str = "ABABUN"


class IndexingSourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    csv_path: FilePath
    columns: IndexingColumnsModel = Field(default_factory=IndexingColumnsModel)
    batch_size: int = Field(default=50, ge=1)


class MappingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    csv_path: FilePath
    id_rvi_column: str = "ID RVI"
    clase_id_column: str = "ID CLASE DOCUMENTAL"
    id_corto_column: str = "ID Corto"
    clase_name_column: str = "CLASE DOCUMENTAL"
    metadata_list_column: str = "METADATOS"


class MetadataSourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    alias: str
    csv_path: FilePath


class ValidationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    allowed_pattern: str | None = None


class FieldSourceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_type: str
    lookup_value_column: str
    lookup_key_column: str | None = None
    validation: ValidationModel | None = None

    @field_validator("source_type")
    @classmethod
    def _validate_source_type(cls, v: str) -> str:
        if v in ("trigger", "rvabrep"):
            return v
        if v.startswith("csv:") or v.startswith("as400:"):
            return v
        raise ValueError(f"unknown source_type: {v!r}")


class FieldConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sources: list[FieldSourceItem] = Field(min_length=1)
    default_value: str | None = None


class MetadataConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    field_aliases: dict[str, str] = Field(default_factory=dict)
    field_sources: dict[str, FieldConfig]
    sources: list[MetadataSourceConfig] = Field(default_factory=list)
    prefetch_enabled: bool = True


class AssemblyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_root: DirectoryPath
    temp_dir: Path
    image_type_map: dict[str, str] = Field(
        default_factory=lambda: {"B": "image/tiff", "O": "application/pdf", "C": "image/jpeg"}
    )


class CmisConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    base_url: str
    repo_id: str
    timeout_seconds: float = Field(default=300.0, gt=0)
    verify_ssl: bool = False
    max_bandwidth_mbps: float = Field(default=0.0, ge=0)
    retry_max_attempts: int = Field(default=3, ge=1)
    retry_base_delay_s: float = Field(default=2.0, ge=0)


class TrackingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    db_path: Path


class PipelineConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    trigger: TriggerCsvConfig
    indexing: IndexingSourceConfig
    mapping: MappingConfig
    metadata: MetadataConfigModel
    assembly: AssemblyConfig
    cmis: CmisConfigModel
    tracking: TrackingConfig
    batch_size: int = Field(default=1000, ge=1)
```

### 3.2 `config/loader.py`

```python
@dataclass(frozen=True, slots=True)
class Secrets:
    cmis_username: str
    cmis_password: str
    as400_username: str = ""
    as400_password: str = ""


def load_config(path: Path) -> PipelineConfig:
    """Read + validate. Raises ConfigurationError on any failure."""

def load_secrets() -> Secrets:
    """Read env vars; raises ConfigurationError if CMIS creds missing."""
```

### 3.3 `config/wiring.py`

```python
def build_pipeline(config: PipelineConfig, secrets: Secrets) -> CsvTriggerPipeline:
    """Construct every adapter / service and wire the orchestrator."""
```

### 3.4 `cli/app.py`

```python
@click.group()
def cli() -> None:
    """CMCourier — RVI to Content Manager migration tool."""


@cli.group(name="csv-trigger-pipeline")
def csv_trigger_pipeline() -> None:
    """csv-trigger-pipeline subcommands (REBIRTH §10.2)."""


@csv_trigger_pipeline.command(name="run")
@click.option("--config", "config_path", type=click.Path(...), required=True)
@click.option("--batch-id", default=None)
@click.option("--from-stage", type=int, default=1)
@click.option("--batch-size", type=int, default=None)
@click.option("--triggers", "triggers_override", type=click.Path(...), default=None)
@click.option("--log-level", type=click.Choice([...]), default="INFO")
def run_command(...):
    ...


def main() -> None:
    """Console-script entry point. Used by pyproject `[project.scripts]`."""
    cli()  # type: ignore[no-untyped-call]
```

### 3.5 `cli/logging_setup.py`

```python
def configure(level: str = "INFO") -> None:
    """Install a stderr StreamHandler on the root logger. Idempotent."""
```

---

## 4. Algorithm sketches

### 4.1 `load_config`

```python
def load_config(path):
    if not path.is_file():
        raise ConfigurationError("config file not found", config_path=str(path))
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigurationError("invalid YAML", reason=str(exc)) from exc
    if not isinstance(data, dict):
        raise ConfigurationError("config root must be a mapping",
                                 actual_type=type(data).__name__)
    try:
        return PipelineConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationError("config validation failed",
                                 errors=exc.errors()) from exc
```

### 4.2 `load_secrets`

```python
def load_secrets():
    missing: list[str] = []
    cmis_u = os.environ.get("CMIS_USERNAME", "").strip()
    cmis_p = os.environ.get("CMIS_PASSWORD", "").strip()
    if not cmis_u:
        missing.append("CMIS_USERNAME")
    if not cmis_p:
        missing.append("CMIS_PASSWORD")
    if missing:
        raise ConfigurationError("missing required env vars", missing_vars=missing)
    return Secrets(
        cmis_username=cmis_u,
        cmis_password=cmis_p,
        as400_username=os.environ.get("AS400_USERNAME", "").strip(),
        as400_password=os.environ.get("AS400_PASSWORD", "").strip(),
    )
```

### 4.3 `build_pipeline`

```python
def build_pipeline(config, secrets):
    # 1. Validate that no field uses as400:* (not yet supported).
    for field_name, fc in config.metadata.field_sources.items():
        for src in fc.sources:
            if src.source_type.startswith("as400:"):
                raise ConfigurationError(
                    "as400 source not yet supported",
                    field=field_name, source_type=src.source_type,
                )

    # 2. Open data sources.
    trigger_src = TabularDataSource(config.trigger.csv_path)
    rvabrep_src = TabularDataSource(config.indexing.csv_path)
    mapping_src = TabularDataSource(config.mapping.csv_path)
    metadata_sources = {s.alias: TabularDataSource(s.csv_path)
                        for s in config.metadata.sources}

    # 3. Build services + adapters.
    trigger_strategy = CsvTriggerStrategy(
        trigger_src,
        CsvTriggerColumnsConfig(
            col_shortname=config.trigger.shortname_column,
            col_cif=config.trigger.cif_column,
            col_system_id=config.trigger.system_id_column,
        ),
    )
    indexing_service = IndexingService(
        rvabrep_src,
        _indexing_columns_from_schema(config.indexing.columns),
        batch_size=config.indexing.batch_size,
    )
    mapping_service = MappingService(
        mapping_src,
        _mapping_columns_from_schema(config.mapping),
    )
    metadata_service = MetadataService(
        _metadata_config_from_schema(config.metadata),
        metadata_sources,
    )
    assembler = PdfAssembler(
        AssemblerConfig(
            source_root=config.assembly.source_root,
            temp_dir=config.assembly.temp_dir,
            image_type_map=config.assembly.image_type_map,
        )
    )
    uploader = CmisUploader(
        CmisConfig(
            base_url=config.cmis.base_url,
            repo_id=config.cmis.repo_id,
            username=secrets.cmis_username,
            password=secrets.cmis_password,
            timeout_seconds=config.cmis.timeout_seconds,
            verify_ssl=config.cmis.verify_ssl,
            max_bandwidth_mbps=config.cmis.max_bandwidth_mbps,
            retry_max_attempts=config.cmis.retry_max_attempts,
            retry_base_delay_s=config.cmis.retry_base_delay_s,
        )
    )
    tracking_store = SQLiteTrackingStore(config.tracking.db_path)
    return CsvTriggerPipeline(
        trigger_strategy=trigger_strategy,
        indexing_service=indexing_service,
        mapping_service=mapping_service,
        metadata_service=metadata_service,
        assembler=assembler,
        uploader=uploader,
        tracking_store=tracking_store,
    )
```

Plus private converters `_indexing_columns_from_schema`,
`_mapping_columns_from_schema`, `_metadata_config_from_schema` that
translate the Pydantic models into the services' existing
dataclass-based configs (preserving the layer separation — the
services don't import Pydantic).

### 4.4 CLI `run` command body

```python
def run_command(config_path, batch_id, from_stage, batch_size,
                triggers_override, log_level):
    configure(log_level)
    try:
        config = load_config(Path(config_path))
        secrets = load_secrets()
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

    if triggers_override:
        config = config.model_copy(
            update={"trigger": config.trigger.model_copy(
                update={"csv_path": Path(triggers_override)})}
        )
    if batch_size is not None:
        config = config.model_copy(update={"batch_size": batch_size})

    try:
        pipeline = build_pipeline(config, secrets)
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

    try:
        report = pipeline.run(
            source_descriptor=str(config.trigger.csv_path),
            batch_size=config.batch_size,
            batch_id=batch_id,
            from_stage=from_stage,
        )
    except Exception:
        _log.exception("pipeline run failed unexpectedly")
        sys.exit(3)

    click.echo(
        f"batch_id={report.batch_id} total_docs={report.total_docs} "
        f"s5_done={report.s5_done} s5_failed={report.s5_failed} "
        f"elapsed_seconds={report.elapsed_seconds:.2f}"
    )
    sys.exit(0 if report.s5_failed == 0 else 1)
```

### 4.5 `logging_setup.configure`

```python
def configure(level: str = "INFO") -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper()))
```

---

## 5. Test plan

### 5.1 Tests in `tests/unit/config/test_schema.py`

~6 tests:
- Valid full config validates.
- `extra="forbid"` rejects unknown keys at top level.
- `extra="forbid"` rejects unknown keys at nested level (e.g.,
  `mapping.extra: 1`).
- Field validator on `source_type` accepts `trigger`, `rvabrep`,
  `csv:X`, `as400:X` and rejects others.
- `batch_size` defaults to 1000; explicit zero raises.
- Numeric constraints: `cmis.timeout_seconds` > 0,
  `cmis.retry_max_attempts >= 1`.

### 5.2 Tests in `tests/unit/config/test_loader.py`

~6 tests:
- Valid YAML loads into PipelineConfig.
- Missing file → ConfigurationError(config_path=...).
- Invalid YAML syntax → ConfigurationError(reason=...).
- YAML root is a list (not dict) → ConfigurationError.
- Validation failure surfaces `errors` context.
- `load_secrets` happy path + missing var + empty-string var.

### 5.3 Tests in `tests/integration/config/test_wiring.py`

~3 tests:
- `build_pipeline` returns a `CsvTriggerPipeline` that runs end-to-end
  against the pipeline fixtures with responses-mocked CMIS.
- `build_pipeline` rejects `as400:*` source_type.
- `_metadata_config_from_schema` round-trips: a Pydantic
  `MetadataConfigModel` produces an equivalent `MetadataConfig`
  (assert on field_sources keys / source_type strings).

### 5.4 Tests in `tests/integration/cli/test_cli.py`

~8 tests:
- `cmcourier --help` lists `csv-trigger-pipeline`.
- `cmcourier csv-trigger-pipeline run --help` lists every flag.
- Run with valid config + env vars + mocked CMIS → exit 0, stdout
  has summary line.
- Run with missing config file → exit 2, stderr has error.
- Run with missing env vars → exit 2.
- Run with `--triggers` override → uses override path (assert via
  RunReport / migration_log).
- Run with `--from-stage` + `--batch-id` → resume works.
- Run with `--log-level DEBUG` → debug logs appear in stderr.

### 5.5 Test harness

- `tests/fixtures/cli/valid_config.yaml` — a complete config that
  points at the existing pipeline fixtures.
- A `cli_runner` fixture wrapping `click.testing.CliRunner` with
  `mix_stderr=False` so stdout and stderr are separable.
- A `set_env` fixture (or `monkeypatch.setenv`) for CMIS credentials.
- A pytest autouse fixture in `tests/integration/cli/conftest.py`
  that resets root logging handlers between tests.

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001 (PyYAML dep) | — | smoke test importing yaml |
| REQ-002..007 (schema) | §3.1 | test_schema.py |
| REQ-008..011 (loader) | §4.1 | test_loader.py |
| REQ-012..013 (secrets) | §4.2 | test_loader.py |
| REQ-014..016 (wiring) | §4.3 | test_wiring.py |
| REQ-017..022 (CLI) | §4.4 | test_cli.py |
| REQ-023..024 (logging) | §4.5 | test_cli.py (log-level test) |
| NFR-001 (size cap) | — | visual review |
| NFR-002 (coverage ≥85%) | — | `pytest --cov` |

---

## 7. Files touched

```
NEW   src/cmcourier/config/schema.py
NEW   src/cmcourier/config/loader.py
NEW   src/cmcourier/config/wiring.py
EDIT  src/cmcourier/config/__init__.py        # re-exports
NEW   src/cmcourier/cli/logging_setup.py
EDIT  src/cmcourier/cli/app.py                # full implementation
NEW   tests/unit/config/test_schema.py
NEW   tests/unit/config/test_loader.py
NEW   tests/integration/config/test_wiring.py
NEW   tests/integration/cli/conftest.py
NEW   tests/integration/cli/test_cli.py
NEW   tests/fixtures/cli/valid_config.yaml
EDIT  pyproject.toml                          # PyYAML
EDIT  CHANGELOG.md                            # [0.14.0]
EDIT  README.md                               # Status checklist
NEW   specs/012-cli-config/{spec,plan,tasks}.md
```

---

## 8. Risks

- **Risk**: `pydantic.FilePath` raises during `model_validate` if the
  path does not exist. Test fixtures must be created before
  `load_config`. The pipeline fixtures already exist on disk —
  pipeline tests use them directly. CLI tests reuse them.
- **Risk**: the CLI `run` command's body grows past 50 lines as flags
  + overrides accumulate. Mitigation: extract `_apply_overrides(config,
  triggers, batch_size)` and `_emit_summary(report)` helpers.
- **Risk**: `model_copy(update={"trigger": ...})` doesn't recursively
  rebuild the `trigger` model. Need to build the new `TriggerCsvConfig`
  explicitly. Mitigation: tests cover the `--triggers` override path.
- **Risk**: `responses.activate` outside `@responses.activate` block
  doesn't intercept the CLI's request layer when invoked via
  `CliRunner`. Mitigation: use the context-manager form inside the
  test function and pass the mocked CMIS URL through the test YAML.
- **Risk**: a misconfigured logging level might leak verbose
  third-party logs (Pillow, requests) into test stderr. Mitigation:
  the per-test logging reset fixture; if it becomes noisy, silencing
  `PIL`/`urllib3` becomes its own change.

---

## 9. Estimated effort

- Spec / plan / tasks: done
- Phase 1 (PyYAML + schema): 45 min
- Phase 2 (loader + secrets): 30 min
- Phase 3 (wiring): 45 min
- Phase 4 (CLI + logging): 45 min
- Phase 5 (verification): 20 min
- Phase 6 (docs + commit + merge): 15 min
- **Total**: ~3 h 20 min

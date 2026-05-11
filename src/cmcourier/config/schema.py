"""Pydantic v2 config schema for the CMCourier pipeline.

Every model is ``frozen=True, extra="forbid"`` so:

* Mutation of validated configs raises (matches the project's
  "frozen dataclasses everywhere" pattern).
* Unknown YAML keys raise at load time — operators get an immediate
  error rather than silently mis-configured runs.

Path fields use :class:`pydantic.FilePath` for inputs that MUST already
exist (CSVs, source_root) and :class:`pathlib.Path` for outputs that
will be created at run time (temp_dir, sqlite db).

Constitution Principle V: this module is the single declarative source
of truth for the pipeline's configurable surface. The orchestrator and
adapters do NOT import this module — translation happens in
:mod:`cmcourier.config.wiring`.
"""

from __future__ import annotations

__all__ = [
    "As400ConnectionConfig",
    "As400MetadataSourceConfig",
    "As400TriggerConfig",
    "AssemblyConfig",
    "AutoTuneConfig",
    "CmisConfigModel",
    "CsvMetadataSourceConfig",
    "CsvTriggerConfig",
    "FieldConfig",
    "FieldSourceItem",
    "HeavyLightLanesConfig",
    "IndexingColumnsModel",
    "IndexingSourceConfig",
    "LocalScanTriggerConfig",
    "MappingConfig",
    "MetadataCacheConfig",
    "SingleDocTriggerConfig",
    "MetadataConfigModel",
    "MetadataSourceConfig",
    "ObservabilityConfig",
    "PipelineConfig",
    "RvabrepFiltersModel",
    "RvabrepTriggerConfig",
    "TrackingConfig",
    "TriggerConfigUnion",
    "TriggerCsvConfig",
    "ValidationModel",
]

from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    DirectoryPath,
    Field,
    FilePath,
    field_validator,
    model_validator,
)

_STRICT = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# AS400 connection (used by rvabrep and as400 trigger kinds)
# ---------------------------------------------------------------------------


class As400ConnectionConfig(BaseModel):
    """AS400 ODBC connection parameters. Credentials live in env vars."""

    model_config = _STRICT
    host: str
    port: int = Field(default=446, ge=1, le=65535)
    database: str = "RVILIB"
    driver: str = "iSeries Access ODBC Driver"
    table: str | None = None


# ---------------------------------------------------------------------------
# Trigger kinds (discriminated union by `kind`)
# ---------------------------------------------------------------------------


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


class As400TriggerConfig(BaseModel):
    model_config = _STRICT
    kind: Literal["as400"]
    query: str
    as400_connection: As400ConnectionConfig


class LocalScanTriggerConfig(BaseModel):
    """REBIRTH §5.1 mode ``local_scan``."""

    model_config = _STRICT
    kind: Literal["local_scan"]
    scan_path: DirectoryPath


class SingleDocTriggerConfig(BaseModel):
    """REBIRTH §10.2 single-doc diagnostic pipeline.

    No extra fields — the trigger (shortname / cif / system_id) comes
    from CLI args at run time, not from the YAML.
    """

    model_config = _STRICT
    kind: Literal["single_doc"]


TriggerConfigUnion = Annotated[
    CsvTriggerConfig
    | RvabrepTriggerConfig
    | As400TriggerConfig
    | LocalScanTriggerConfig
    | SingleDocTriggerConfig,
    Field(discriminator="kind"),
]


# Backwards-compatible alias: existing code that imports TriggerCsvConfig
# still works. The discriminated union is the new shape.
TriggerCsvConfig = CsvTriggerConfig


class IndexingColumnsModel(BaseModel):
    """Logical → physical column map for the RVABREP source."""

    model_config = _STRICT
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
    model_config = _STRICT
    csv_path: FilePath
    columns: IndexingColumnsModel = Field(default_factory=IndexingColumnsModel)
    batch_size: int = Field(default=50, ge=1)


class MappingConfig(BaseModel):
    """Modelo Documental config in one of two mutually-exclusive modes.

    Consolidated (legacy / test fixtures): a single CSV with all
    columns inline and a comma-separated ``METADATOS`` cell. Set
    ``csv_path`` and leave the split fields ``None``.

    Split (production / bank format, 035): two CSVs joined by
    ``IDCM ↔ IDCorto`` — ``MapeoRVI_CM.csv`` (one row per IDRVI) plus
    ``MetadatosCM.csv`` (multiple rows per IDCorto). Set both
    ``rvi_cm_csv_path`` and ``metadatos_csv_path`` and leave
    ``csv_path`` ``None``.
    """

    model_config = _STRICT
    csv_path: FilePath | None = None
    rvi_cm_csv_path: FilePath | None = None
    metadatos_csv_path: FilePath | None = None
    id_rvi_column: str = "ID RVI"
    clase_id_column: str = "ID CLASE DOCUMENTAL"
    id_corto_column: str = "ID Corto"
    clase_name_column: str = "CLASE DOCUMENTAL"
    metadata_list_column: str = "METADATOS"
    cmis_type_column: str = "CMISType"
    rvi_cm_id_rvi_column: str = "IDRVI"
    rvi_cm_id_cm_column: str = "IDCM"
    rvi_cm_clase_id_column: str = "IDClaseDocumental"
    rvi_cm_cmis_type_column: str = "CMISType"
    metadatos_id_corto_column: str = "IDCorto"
    metadatos_metadata_column: str = "Metadato"
    metadatos_required_column: str = "Requerido"
    required_marker: str = "Yes"

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> MappingConfig:
        has_consolidated = self.csv_path is not None
        has_rvi = self.rvi_cm_csv_path is not None
        has_meta = self.metadatos_csv_path is not None
        if has_consolidated and (has_rvi or has_meta):
            raise ValueError(
                "MappingConfig: pick either consolidated `csv_path` "
                "OR split (`rvi_cm_csv_path` + `metadatos_csv_path`), not both"
            )
        if not has_consolidated and not (has_rvi or has_meta):
            raise ValueError(
                "MappingConfig: must provide consolidated `csv_path` "
                "OR split (`rvi_cm_csv_path` + `metadatos_csv_path`)"
            )
        if (has_rvi and not has_meta) or (has_meta and not has_rvi):
            raise ValueError(
                "MappingConfig: split mode requires BOTH `rvi_cm_csv_path` and `metadatos_csv_path`"
            )
        return self


class CsvMetadataSourceConfig(BaseModel):
    """A named CSV source available to metadata resolution."""

    model_config = _STRICT
    kind: Literal["csv"] = "csv"
    alias: str
    csv_path: FilePath


class As400MetadataSourceConfig(BaseModel):
    """A named AS400 source available to metadata resolution.

    Prefetch runs ``SELECT * FROM <table>`` (table mode) or
    ``SELECT * FROM (<query>) AS T`` (query mode) over the configured
    connection. Exactly one of ``table`` / ``query`` MUST be set —
    the operator picks the form that scales to their data volume.
    """

    model_config = _STRICT
    kind: Literal["as400"]
    alias: str
    as400_connection: As400ConnectionConfig
    table: str | None = Field(default=None, min_length=1)
    query: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one_table_or_query(self) -> As400MetadataSourceConfig:
        if bool(self.table) == bool(self.query):
            raise ValueError("as400 metadata source requires exactly one of `table` or `query`")
        return self


# Backwards-compatible name for the legacy CSV-only shape.
MetadataSourceConfig = Annotated[
    CsvMetadataSourceConfig | As400MetadataSourceConfig,
    Field(discriminator="kind"),
]


class ValidationModel(BaseModel):
    model_config = _STRICT
    allowed_pattern: str | None = None


class FieldSourceItem(BaseModel):
    model_config = _STRICT
    source_type: str
    lookup_value_column: str
    lookup_key_column: str | None = None
    validation: ValidationModel | None = None

    @field_validator("source_type")
    @classmethod
    def _validate_source_type(cls, value: str) -> str:
        if value in ("trigger", "rvabrep"):
            return value
        if value.startswith("csv:") or value.startswith("as400:"):
            return value
        raise ValueError(f"unknown source_type: {value!r}")


class FieldConfig(BaseModel):
    model_config = _STRICT
    sources: list[FieldSourceItem] = Field(min_length=1)
    default_value: str | None = None


class MetadataCacheConfig(BaseModel):
    """POST-MVP §9 — cross-batch metadata cache configuration (037).

    When ``enabled`` is ``True``, ``StagedPipeline`` consults a
    SQLite-backed ``document_cache`` table before invoking S3
    (Metadata Resolution). A hit whose ``cached_at`` is within
    ``ttl_minutes`` short-circuits the resolver; a miss runs the
    resolver and upserts the result. Default off — single-batch
    behavior is byte-identical to pre-037.
    """

    model_config = _STRICT
    enabled: bool = False
    ttl_minutes: int = Field(default=60, gt=0, le=43200)  # cap: 30 days


class MetadataConfigModel(BaseModel):
    model_config = _STRICT
    field_aliases: dict[str, str] = Field(default_factory=dict)
    field_sources: dict[str, FieldConfig]
    sources: list[MetadataSourceConfig] = Field(default_factory=list)
    prefetch_enabled: bool = True
    cache: MetadataCacheConfig = Field(default_factory=MetadataCacheConfig)


class AssemblyConfig(BaseModel):
    model_config = _STRICT
    source_root: DirectoryPath
    temp_dir: Path
    image_type_map: dict[str, str] = Field(
        default_factory=lambda: {
            "B": "image/tiff",
            "O": "application/pdf",
            "C": "image/jpeg",
        }
    )


class AutoTuneConfig(BaseModel):
    """AIMD auto-tune for the S5 worker pool (REBIRTH §12).

    When ``enabled=True``, a background controller adjusts the
    thread count and (optionally) the CMIS request timeout based
    on observed S5 p95 latency vs ``target_p95_ms``.
    """

    model_config = _STRICT
    enabled: bool = False
    min_threads: int = Field(default=2, ge=1)
    max_threads: int = Field(default=50, ge=1)
    target_p95_ms: float = Field(default=5000.0, gt=0)
    adjustment_interval_s: int = Field(default=30, ge=1)
    warmup_seconds: int = Field(default=60, ge=0)
    timeout_auto_adjust: bool = True
    min_timeout_s: int = Field(default=30, ge=1)
    max_timeout_s: int = Field(default=600, ge=1)

    @model_validator(mode="after")
    def _validate_ranges(self) -> AutoTuneConfig:
        if self.min_threads > self.max_threads:
            raise ValueError(
                "auto_tune.min_threads must be <= max_threads "
                f"(got {self.min_threads} > {self.max_threads})"
            )
        if self.min_timeout_s > self.max_timeout_s:
            raise ValueError(
                "auto_tune.min_timeout_s must be <= max_timeout_s "
                f"(got {self.min_timeout_s} > {self.max_timeout_s})"
            )
        return self


class CmisConfigModel(BaseModel):
    """CMIS connection knobs. Credentials live in env vars, not here."""

    model_config = _STRICT
    base_url: str
    repo_id: str
    timeout_seconds: float = Field(default=300.0, gt=0)
    verify_ssl: bool = False
    max_bandwidth_mbps: float = Field(default=0.0, ge=0)
    retry_max_attempts: int = Field(default=3, ge=1)
    retry_base_delay_s: float = Field(default=2.0, ge=0)
    workers: int = Field(default=4, ge=1)
    auto_tune: AutoTuneConfig = Field(default_factory=AutoTuneConfig)


class As400SyncConfig(BaseModel):
    """POST-MVP §4 — distributed idempotency coordination via AS400 NIARVILOG.

    Default ``enabled=False`` preserves the pre-034 SQLite-only
    behavior. When enabled, the pipeline coordinates with the
    centralized ``RVILIB.NIARVILOG`` table for cross-batch
    idempotency, atomic claim against concurrent processes, and
    operator-visible upload state.
    """

    model_config = _STRICT
    enabled: bool = False
    connection: As400ConnectionConfig | None = None
    library: str = "RVILIB"
    table: str = "NIARVILOG"
    stale_in_progress_minutes: int = Field(default=30, ge=1, le=1440)
    retry_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_delay_s: float = Field(default=5.0, gt=0)

    @model_validator(mode="after")
    def _connection_required_when_enabled(self) -> As400SyncConfig:
        if self.enabled and self.connection is None:
            msg = (
                "tracking.as400_sync.enabled=true requires tracking.as400_sync.connection to be set"
            )
            raise ValueError(msg)
        return self


class TrackingConfig(BaseModel):
    model_config = _STRICT
    db_path: Path
    as400_sync: As400SyncConfig = Field(default_factory=As400SyncConfig)


class HeavyLightLanesConfig(BaseModel):
    """POST-MVP §1 — adaptive heavy/light upload lane configuration (036).

    When ``enabled`` is ``True`` and a batch has at least
    ``heavy_lane_min_batch`` items, S5 splits documents by
    ``file_size_bytes >= heavy_threshold_bytes`` into two lanes that
    share the total worker budget. The total budget is owned by AIMD
    (when active); ``heavy_initial_ratio`` plus a drain-driven
    rebalance daemon (``rebalance_interval_s`` /
    ``idle_threshold_s``) own the lane split.

    Default ``enabled = False`` preserves the pre-036 single-pool
    behavior byte-for-byte.
    """

    model_config = _STRICT
    enabled: bool = False
    heavy_threshold_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    heavy_lane_min_batch: int = Field(default=50, ge=1)
    heavy_initial_ratio: float = Field(default=0.2, ge=0.0, le=1.0)
    rebalance_interval_s: float = Field(default=10.0, gt=0.0, le=600.0)
    idle_threshold_s: float = Field(default=15.0, gt=0.0, le=3600.0)


class ProcessingConfig(BaseModel):
    """POST-MVP §7 + §1 — multi-batch orchestration + dual-lane knobs.

    ``batches_in_flight`` controls the producer-consumer overlap:
    while batch N uploads (S5), batches N+1..N+(K-1) prepare
    (S0–S4) concurrently. Default ``2`` is the canonical
    "one preparing + one uploading" model.

    ``heavy_light_lanes`` carries the dual-lane (POST-MVP §1) config —
    default-off; see :class:`HeavyLightLanesConfig`.
    """

    model_config = _STRICT
    batches_in_flight: int = Field(default=2, ge=1, le=2)
    heavy_light_lanes: HeavyLightLanesConfig = Field(default_factory=HeavyLightLanesConfig)


class SystemMetricsConfig(BaseModel):
    """POST-MVP §2 — tier 5 system resource sampling via ``psutil``.

    ``enabled`` defaults ON: when a pipeline runs, a daemon thread
    samples host- and process-level metrics every
    ``sample_interval_s`` seconds and writes JSONL to
    ``observability.log_dir/system-{date}.jsonl``. Set
    ``enabled: false`` (or the legacy ``system_metrics: false``
    bool form) to opt out for low-overhead environments.
    """

    model_config = _STRICT
    enabled: bool = True
    sample_interval_s: float = Field(default=5.0, ge=1.0, le=60.0)


class ObservabilityConfig(BaseModel):
    """REBIRTH §17.4 observability — per-tier toggles + log dir + thresholds.

    Tiers 1-4 (app log, pipeline metrics, network metrics,
    slow-ops report) ship since 020. Tier 5 (system metrics via
    psutil) shipped in 026 — see ``SystemMetricsConfig``.
    """

    model_config = _STRICT
    enabled: bool = True
    pipeline_metrics: bool = True
    network_metrics: bool = True
    system_metrics: SystemMetricsConfig = Field(default_factory=SystemMetricsConfig)
    log_dir: Path = Path("./logs")
    log_format: Literal["json", "text"] = "json"
    rotation_mb: int = Field(default=100, ge=1)
    retention_days: int = Field(default=30, ge=1)
    slow_op_threshold_ms: int = Field(default=5000, ge=0)
    slow_op_top_n: int = Field(default=20, ge=1)

    @field_validator("system_metrics", mode="before")
    @classmethod
    def _coerce_system_metrics(cls, value: object) -> object:
        # REQ-002: accept legacy bool form (`system_metrics: false`)
        # from pre-026 YAMLs and lift it to the structured model.
        if isinstance(value, bool):
            return {"enabled": value}
        return value


class PipelineConfig(BaseModel):
    """Top-level config aggregating every per-stage configuration block."""

    model_config = _STRICT
    trigger: TriggerConfigUnion
    indexing: IndexingSourceConfig
    mapping: MappingConfig
    metadata: MetadataConfigModel
    assembly: AssemblyConfig
    cmis: CmisConfigModel
    tracking: TrackingConfig
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    batch_size: int = Field(default=1000, ge=1)

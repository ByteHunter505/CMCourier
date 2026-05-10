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
    "As400TriggerConfig",
    "AssemblyConfig",
    "CmisConfigModel",
    "CsvTriggerConfig",
    "FieldConfig",
    "FieldSourceItem",
    "IndexingColumnsModel",
    "IndexingSourceConfig",
    "MappingConfig",
    "MetadataConfigModel",
    "MetadataSourceConfig",
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


TriggerConfigUnion = Annotated[
    CsvTriggerConfig | RvabrepTriggerConfig | As400TriggerConfig,
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
    model_config = _STRICT
    csv_path: FilePath
    id_rvi_column: str = "ID RVI"
    clase_id_column: str = "ID CLASE DOCUMENTAL"
    id_corto_column: str = "ID Corto"
    clase_name_column: str = "CLASE DOCUMENTAL"
    metadata_list_column: str = "METADATOS"


class MetadataSourceConfig(BaseModel):
    """One named CSV source available to metadata resolution."""

    model_config = _STRICT
    alias: str
    csv_path: FilePath


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


class MetadataConfigModel(BaseModel):
    model_config = _STRICT
    field_aliases: dict[str, str] = Field(default_factory=dict)
    field_sources: dict[str, FieldConfig]
    sources: list[MetadataSourceConfig] = Field(default_factory=list)
    prefetch_enabled: bool = True


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


class TrackingConfig(BaseModel):
    model_config = _STRICT
    db_path: Path


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
    batch_size: int = Field(default=1000, ge=1)

"""Adapter factory: turn :class:`PipelineConfig` into a wired pipeline.

The orchestrator and adapters do NOT import Pydantic. This module owns
the translation between the schema (Pydantic) and each service's
existing dataclass-based config. Constitution Principle I (layer
separation) holds.
"""

from __future__ import annotations

__all__ = ["build_pipeline"]

from cmcourier.adapters.assembly import AssemblerConfig, PdfAssembler
from cmcourier.adapters.sources import TabularDataSource
from cmcourier.adapters.tracking import SQLiteTrackingStore
from cmcourier.adapters.upload.cmis_uploader import CmisConfig, CmisUploader
from cmcourier.config.loader import Secrets
from cmcourier.config.schema import (
    IndexingColumnsModel,
    MetadataConfigModel,
    PipelineConfig,
)
from cmcourier.config.schema import (
    MappingConfig as MappingConfigModel,
)
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.ports import IDataSource
from cmcourier.orchestrators.csv_trigger import CsvTriggerPipeline
from cmcourier.services.indexing import IndexingColumnsConfig, IndexingService
from cmcourier.services.mapping import MappingColumnsConfig, MappingService
from cmcourier.services.metadata import (
    FieldSourceConfig,
    MetadataConfig,
    MetadataService,
    SourceConfig,
    ValidationConfig,
)
from cmcourier.services.triggers.csv import (
    CsvTriggerColumnsConfig,
    CsvTriggerStrategy,
)


def build_pipeline(config: PipelineConfig, secrets: Secrets) -> CsvTriggerPipeline:
    """Construct every adapter / service and return the wired pipeline."""
    _reject_unsupported_source_types(config.metadata)

    trigger_src = TabularDataSource(config.trigger.csv_path)
    rvabrep_src = TabularDataSource(config.indexing.csv_path)
    mapping_src = TabularDataSource(config.mapping.csv_path)
    metadata_sources: dict[str, IDataSource] = {
        s.alias: TabularDataSource(s.csv_path) for s in config.metadata.sources
    }

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


# ---------------------------------------------------------------------------
# Schema → service-config converters
# ---------------------------------------------------------------------------


def _reject_unsupported_source_types(metadata: MetadataConfigModel) -> None:
    for field_name, fc in metadata.field_sources.items():
        for src in fc.sources:
            if src.source_type.startswith("as400:"):
                raise ConfigurationError(
                    "as400 source not yet supported",
                    field=field_name,
                    source_type=src.source_type,
                )


def _indexing_columns_from_schema(model: IndexingColumnsModel) -> IndexingColumnsConfig:
    return IndexingColumnsConfig(
        shortname_column=model.shortname_column,
        system_id_column=model.system_id_column,
        delete_code_column=model.delete_code_column,
        txn_num_column=model.txn_num_column,
        index2_column=model.index2_column,
        index3_column=model.index3_column,
        index4_column=model.index4_column,
        index5_column=model.index5_column,
        index6_column=model.index6_column,
        index7_column=model.index7_column,
        image_type_column=model.image_type_column,
        image_path_column=model.image_path_column,
        file_name_column=model.file_name_column,
        creation_date_column=model.creation_date_column,
        last_view_date_column=model.last_view_date_column,
        total_pages_column=model.total_pages_column,
    )


def _mapping_columns_from_schema(model: MappingConfigModel) -> MappingColumnsConfig:
    return MappingColumnsConfig(
        col_clase_id=model.clase_id_column,
        col_id_rvi=model.id_rvi_column,
        col_id_corto=model.id_corto_column,
        col_clase_name=model.clase_name_column,
        col_metadata_list=model.metadata_list_column,
    )


def _metadata_config_from_schema(model: MetadataConfigModel) -> MetadataConfig:
    field_sources: dict[str, FieldSourceConfig] = {}
    for canonical, fc in model.field_sources.items():
        field_sources[canonical] = FieldSourceConfig(
            sources=tuple(
                SourceConfig(
                    source_type=src.source_type,
                    lookup_value_column=src.lookup_value_column,
                    lookup_key_column=src.lookup_key_column,
                    validation=(
                        ValidationConfig(allowed_pattern=src.validation.allowed_pattern)
                        if src.validation is not None
                        else None
                    ),
                )
                for src in fc.sources
            ),
            default_value=fc.default_value,
        )
    return MetadataConfig(
        field_aliases=dict(model.field_aliases),
        field_sources=field_sources,
        prefetch_enabled=model.prefetch_enabled,
    )

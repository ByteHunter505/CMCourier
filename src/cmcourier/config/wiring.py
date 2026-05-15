"""Adapter factory: turn :class:`PipelineConfig` into a wired pipeline.

The orchestrator and adapters do NOT import Pydantic. This module owns
the translation between the schema (Pydantic) and each service's
existing dataclass-based config. Constitution Principle I (layer
separation) holds.
"""

from __future__ import annotations

__all__ = ["build_pipeline"]

import atexit
from concurrent.futures import ProcessPoolExecutor

from cmcourier.adapters.assembly import (
    AssemblerConfig,
    PdfAssembler,
    build_s4_process_pool,
)
from cmcourier.adapters.sources import As400DataSource, TabularDataSource
from cmcourier.adapters.tracking import SqliteDocumentCache, SQLiteTrackingStore
from cmcourier.adapters.tracking.as400_niarvilog import (
    As400NiarvilogStore,
    NiarvilogColumns,
)
from cmcourier.adapters.upload.cmis_uploader import CmisConfig, CmisUploader
from cmcourier.config.loader import Secrets
from cmcourier.config.schema import (
    As400RvabrepSource,
    CsvMetadataSourceConfig,
    CsvRvabrepSource,
    CsvTriggerConfig,
    IndexingColumnsModel,
    IndexingConfig,
    LocalScanTriggerConfig,
    MetadataConfigModel,
    MetadataSourceConfig,
    NiarvilogColumnsModel,
    PipelineConfig,
    RvabrepTriggerConfig,
    SingleDocTriggerConfig,
)
from cmcourier.config.schema import (
    MappingConfig as MappingConfigModel,
)
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.ports import IDataSource, S0Strategy
from cmcourier.observability.metrics import MetricsRecorder
from cmcourier.observability.system_metrics import (
    build_sampler as build_system_metrics_sampler,
)
from cmcourier.orchestrators.staged import StagedPipeline
from cmcourier.services.document_cache import DocumentCacheService
from cmcourier.services.idempotency import IdempotencyCoordinator
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
from cmcourier.services.triggers.direct_rvabrep import (
    DirectRvabrepTriggerStrategy,
    RvabrepColumnsConfig,
    RvabrepFilters,
)
from cmcourier.services.triggers.local_scan import LocalScanTriggerStrategy


def build_pipeline(
    config: PipelineConfig,
    secrets: Secrets,
    *,
    trigger_strategy_override: S0Strategy | None = None,
    pipeline_name: str = "csv-trigger",
) -> StagedPipeline:
    """Construct every adapter / service and return the wired pipeline.

    Pass ``trigger_strategy_override`` to bypass the schema-driven
    dispatch — used by the single-doc CLI to inject a strategy built
    from CLI args (REBIRTH §10.2).
    """
    # 048: the RVABREP source is pluggable (CSV ↔ AS400). Built once here
    # and shared by S0 (DirectRvabrepTriggerStrategy / LocalScanTriggerStrategy)
    # AND S1 (IndexingService) — the RVABREP table is the same data
    # regardless of where it lives.
    rvabrep_src = _build_rvabrep_source(config.indexing, secrets)
    metadata_sources = _build_metadata_sources(config.metadata.sources, secrets)

    indexing_service = IndexingService(
        rvabrep_src,
        _indexing_columns_from_schema(config.indexing.columns),
        batch_size=config.indexing.batch_size,
    )
    trigger_strategy = trigger_strategy_override or _build_trigger_strategy(
        config, secrets, rvabrep_src, indexing_service
    )
    mapping_service = build_mapping_service(config.mapping)
    metadata_service = MetadataService(
        _metadata_config_from_schema(config.metadata),
        metadata_sources,
    )
    assembler_config = AssemblerConfig(
        source_root=config.assembly.source_root,
        temp_dir=config.assembly.temp_dir,
        image_type_map=config.assembly.image_type_map,
    )
    assembler = PdfAssembler(assembler_config)
    # 066: optional ProcessPoolExecutor for S4 (PDF assembly).
    # Bypasses the GIL for the CPU-bound img2pdf/PIL/PyPDF2 work;
    # default-on via ``processing.s4_use_processes`` because every
    # benchmark above ~5 docs/s benefits. The pool is shut down at
    # process exit via ``atexit`` — a follow-up spec can move it to
    # a pipeline ``close()`` if explicit lifecycle is needed.
    s4_process_pool: ProcessPoolExecutor | None = None
    if config.processing.s4_use_processes:
        s4_process_pool = build_s4_process_pool(
            assembler_config,
            max_workers=config.processing.s4_max_processes,
        )
        atexit.register(s4_process_pool.shutdown, wait=True)
    # 038: size the connection pool to the highest worker count AIMD
    # might reach so the urllib3 default (10) is never the bottleneck
    # at peak concurrency.
    cmis_pool_size = (
        max(config.cmis.workers, config.cmis.auto_tune.max_threads)
        if config.cmis.auto_tune.enabled
        else config.cmis.workers
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
            pool_size=cmis_pool_size,
            unmask_pii=config.observability.unmask_pii,
        )
    )
    tracking_store = SQLiteTrackingStore(config.tracking.db_path)
    metrics_recorder = MetricsRecorder(
        log_dir=config.observability.log_dir,
        slow_op_threshold_ms=float(config.observability.slow_op_threshold_ms),
        slow_op_top_n=config.observability.slow_op_top_n,
        enabled=config.observability.enabled,
        pipeline_metrics_enabled=config.observability.pipeline_metrics,
    )
    sampler = build_system_metrics_sampler(
        config.observability, log_dir=config.observability.log_dir
    )
    # 034 phase 3: optional AS400 NIARVILOG coordination layer. When
    # tracking.as400_sync.enabled is false (default), this is None and
    # the pipeline runs in legacy SQLite-only mode.
    coordinator = _build_idempotency_coordinator(
        config=config, secrets=secrets, sqlite_store=tracking_store
    )
    document_cache = _build_document_cache_service(config=config)
    return StagedPipeline(
        trigger_strategy=trigger_strategy,
        indexing_service=indexing_service,
        mapping_service=mapping_service,
        metadata_service=metadata_service,
        assembler=assembler,
        metrics_recorder=metrics_recorder,
        pipeline_name=pipeline_name,
        uploader=uploader,
        tracking_store=tracking_store,
        workers=config.cmis.workers,
        prep_workers=config.processing.prep_workers,
        auto_tune=config.cmis.auto_tune,
        sampler=sampler,
        coordinator=coordinator,
        heavy_light_lanes=config.processing.heavy_light_lanes,
        document_cache=document_cache,
        s4_process_pool=s4_process_pool,
    )


def _build_document_cache_service(*, config: PipelineConfig) -> DocumentCacheService | None:
    """037: return a service iff ``metadata.cache.enabled``, else None."""
    if not config.metadata.cache.enabled:
        return None
    sqlite_cache = SqliteDocumentCache(config.tracking.db_path)
    return DocumentCacheService(
        cache=sqlite_cache,
        ttl_minutes=config.metadata.cache.ttl_minutes,
    )


def _build_idempotency_coordinator(
    *,
    config: PipelineConfig,
    secrets: Secrets,
    sqlite_store: SQLiteTrackingStore,
) -> IdempotencyCoordinator | None:
    """Wire the SQLite + (optional) AS400 NIARVILOG coordinator (034).

    Returns ``None`` when ``tracking.as400_sync.enabled=false`` so the
    StagedPipeline stays in legacy pre-034 mode.
    """
    sync_cfg = config.tracking.as400_sync
    if not sync_cfg.enabled:
        return None
    if sync_cfg.connection is None:  # pragma: no cover — schema enforces this
        raise ConfigurationError(
            "tracking.as400_sync.enabled=true requires connection settings",
        )
    if not secrets.as400_username or not secrets.as400_password:
        raise ConfigurationError(
            "AS400 credentials missing in environment (set AS400_USERNAME / AS400_PASSWORD)",
        )
    as400_store = As400NiarvilogStore(
        connection=sync_cfg.connection,
        username=secrets.as400_username,
        password=secrets.as400_password,
        library=sync_cfg.library,
        table=sync_cfg.table,
        columns=_niarvilog_columns_from_schema(sync_cfg.columns),
        stale_in_progress_minutes=sync_cfg.stale_in_progress_minutes,
        retry_attempts=sync_cfg.retry_attempts,
        retry_base_delay_s=sync_cfg.retry_base_delay_s,
    )
    return IdempotencyCoordinator(sqlite_store=sqlite_store, as400_store=as400_store)


# ---------------------------------------------------------------------------
# RVABREP source dispatch (048)
# ---------------------------------------------------------------------------


def _build_rvabrep_source(indexing_cfg: IndexingConfig, secrets: Secrets) -> IDataSource:
    """Build the RVABREP ``IDataSource`` from ``indexing.source`` (048).

    ``csv`` → ``TabularDataSource`` over the CSV file.
    ``as400`` → ``As400DataSource`` in query mode — the operator's SELECT
    (JOINs / filters allowed) is wrapped as ``(query) AS T`` so the full
    IDataSource contract works transparently. The single returned source
    feeds both S0 (trigger discovery) and S1 (doc lookup).
    """
    source = indexing_cfg.source
    if isinstance(source, CsvRvabrepSource):
        return TabularDataSource(source.csv_path)
    if isinstance(source, As400RvabrepSource):
        if not secrets.as400_username or not secrets.as400_password:
            raise ConfigurationError(
                "indexing.source.kind 'as400' requires AS400_USERNAME and AS400_PASSWORD env vars",
                missing_vars=[
                    name
                    for name, value in (
                        ("AS400_USERNAME", secrets.as400_username),
                        ("AS400_PASSWORD", secrets.as400_password),
                    )
                    if not value
                ],
            )
        return As400DataSource(
            host=source.connection.host,
            port=source.connection.port,
            database=source.connection.database,
            driver=source.connection.driver,
            username=secrets.as400_username,
            password=secrets.as400_password,
            query=source.query,
        )
    raise ConfigurationError(
        "unknown indexing.source.kind",
        kind=getattr(source, "kind", "<missing>"),
    )


# ---------------------------------------------------------------------------
# Trigger strategy dispatch
# ---------------------------------------------------------------------------


def _build_trigger_strategy(
    config: PipelineConfig,
    secrets: Secrets,
    rvabrep_src: IDataSource,
    indexing_service: IndexingService,
) -> S0Strategy:
    trigger_cfg = config.trigger
    if isinstance(trigger_cfg, CsvTriggerConfig):
        trigger_src = TabularDataSource(trigger_cfg.csv_path)
        return CsvTriggerStrategy(
            trigger_src,
            CsvTriggerColumnsConfig(
                col_shortname=trigger_cfg.shortname_column,
                col_cif=trigger_cfg.cif_column,
                col_system_id=trigger_cfg.system_id_column,
            ),
        )
    if isinstance(trigger_cfg, RvabrepTriggerConfig):
        return DirectRvabrepTriggerStrategy(
            rvabrep_src,
            filters=RvabrepFilters(
                systems=tuple(trigger_cfg.filters.systems),
                document_types=tuple(trigger_cfg.filters.document_types),
            ),
            columns=RvabrepColumnsConfig(
                col_shortname=config.indexing.columns.shortname_column,
                col_cif=config.indexing.columns.index2_column,
                col_system_id=config.indexing.columns.system_id_column,
                col_id_rvi=config.indexing.columns.index7_column,
            ),
        )
    if isinstance(trigger_cfg, LocalScanTriggerConfig):
        return LocalScanTriggerStrategy(
            scan_path=trigger_cfg.scan_path,
            rvabrep_source=rvabrep_src,
            columns=RvabrepColumnsConfig(
                col_shortname=config.indexing.columns.shortname_column,
                col_cif=config.indexing.columns.index2_column,
                col_system_id=config.indexing.columns.system_id_column,
                col_id_rvi=config.indexing.columns.index7_column,
                file_name_column=config.indexing.columns.file_name_column,
            ),
        )
    if isinstance(trigger_cfg, SingleDocTriggerConfig):
        raise ConfigurationError(
            "single_doc trigger requires CLI-provided shortname/system_id; "
            "use `cmcourier single-doc run` with --shortname/--system/--cif "
            "and trigger_strategy_override",
            kind="single_doc",
        )
    # 048: ``trigger.kind: as400`` was removed — "AS400" is a source choice
    # (``indexing.source.kind: as400``), not a trigger kind. The loader
    # rejects it with a directive error before we ever reach here.
    raise ConfigurationError(
        "unknown trigger.kind",
        kind=getattr(trigger_cfg, "kind", "<unknown>"),
    )


# ---------------------------------------------------------------------------
# Metadata source dispatch (015)
# ---------------------------------------------------------------------------


def _build_metadata_sources(
    sources: list[MetadataSourceConfig],
    secrets: Secrets,
) -> dict[str, IDataSource]:
    """Open every metadata source and return the alias→adapter registry."""
    registry: dict[str, IDataSource] = {}
    for src_cfg in sources:
        if isinstance(src_cfg, CsvMetadataSourceConfig):
            registry[src_cfg.alias] = TabularDataSource(src_cfg.csv_path)
            continue
        # as400 — credentials required.
        if not secrets.as400_username or not secrets.as400_password:
            missing = [
                name
                for name, value in (
                    ("AS400_USERNAME", secrets.as400_username),
                    ("AS400_PASSWORD", secrets.as400_password),
                )
                if not value
            ]
            raise ConfigurationError(
                "AS400 credentials required for as400 metadata source",
                alias=src_cfg.alias,
                missing_vars=missing,
            )
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
    return registry


# ---------------------------------------------------------------------------
# Schema → service-config converters
# ---------------------------------------------------------------------------


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


def _niarvilog_columns_from_schema(model: NiarvilogColumnsModel) -> NiarvilogColumns:
    return NiarvilogColumns(
        system_id=model.system_id_column,
        txn_num=model.txn_num_column,
        doc_format=model.doc_format_column,
        image_archive=model.image_archive_column,
        image_type=model.image_type_column,
        client_cif=model.client_cif_column,
        client_num=model.client_num_column,
        status=model.status_column,
        idcm=model.idcm_column,
        cm_type=model.cm_type_column,
        cm_object_id=model.cm_object_id_column,
        retry_count=model.retry_count_column,
        started_at=model.started_at_column,
        finished_at=model.finished_at_column,
        error_message=model.error_message_column,
    )


def _mapping_columns_from_schema(model: MappingConfigModel) -> MappingColumnsConfig:
    return MappingColumnsConfig(
        col_clase_id=model.clase_id_column,
        col_id_rvi=model.id_rvi_column,
        col_id_corto=model.id_corto_column,
        col_clase_name=model.clase_name_column,
        col_metadata_list=model.metadata_list_column,
        col_cmis_type=model.cmis_type_column,
        col_rvi_cm_id_rvi=model.rvi_cm_id_rvi_column,
        col_rvi_cm_id_cm=model.rvi_cm_id_cm_column,
        col_rvi_cm_clase_id=model.rvi_cm_clase_id_column,
        col_rvi_cm_cmis_type=model.rvi_cm_cmis_type_column,
        col_rvi_cm_cmis_folder=model.rvi_cm_cmis_folder_column,
        col_metadatos_id_corto=model.metadatos_id_corto_column,
        col_metadatos_metadata=model.metadatos_metadata_column,
        col_metadatos_required=model.metadatos_required_column,
        col_metadatos_cmis_property_id=model.metadatos_cmis_property_id_column,
        required_marker=model.required_marker,
    )


def build_mapping_service(model: MappingConfigModel) -> MappingService:
    """Build a fully-loaded :class:`MappingService` from a ``MappingConfig``.

    Picks consolidated or split mode based on which paths are set
    (035). Opens the underlying ``TabularDataSource``(s), loads the
    cache, then closes the source(s) — ``MappingService`` reads
    everything at construction.
    """
    columns = _mapping_columns_from_schema(model)
    if model.csv_path is not None:
        source = TabularDataSource(model.csv_path)
        try:
            return MappingService(source, columns)
        finally:
            source.close()
    assert model.rvi_cm_csv_path is not None  # noqa: S101 - validator guarantees this
    assert model.metadatos_csv_path is not None  # noqa: S101 - validator guarantees this
    rvi_src = TabularDataSource(model.rvi_cm_csv_path)
    metadatos_src = TabularDataSource(model.metadatos_csv_path)
    try:
        return MappingService(rvi_src, columns, metadata_source=metadatos_src)
    finally:
        rvi_src.close()
        metadatos_src.close()


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

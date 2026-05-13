"""Stage S0..S6 orchestrator for the ``csv-trigger-pipeline`` (REBIRTH §10.2).

Wires the seven collaborators (S0 trigger strategy + S1..S5 services /
adapters + S6 tracking store) into one runnable pipeline. The orchestrator
contains no business logic — only coordination, error handling, and
counting (Constitution Principle III).

Two top-level behaviors:

* **Cross-batch idempotency** (REBIRTH §10): docs whose ``txn_num`` is
  already at ``S5_DONE`` in any prior batch are skipped silently — no new
  ``migration_log`` row, just a counter and an INFO log line.
* **Stage-by-stage resume** (REBIRTH §10.3): ``run(batch_id=..., from_stage=N)``
  re-uses an existing batch and SCOPES the run to its prior set of
  ``txn_num``s. Within each stage, ``is_stage_done`` per-doc short-circuits
  re-doing successful work — so re-running with ``from_stage=1`` against a
  completed batch performs zero uploads.

Logging discipline (Constitution VIII): every record carries ``batch_id``
in ``extra``; per-doc records add ``txn_num``; per-stage records add
``stage``. Resolved property values (CIF, Nombre_Cliente, …) NEVER appear
in log records.
"""

from __future__ import annotations

__all__ = ["StagedPipeline", "RunReport"]

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from cmcourier.services.idempotency import IdempotencyCoordinator

from cmcourier.adapters.assembly import PdfAssembler
from cmcourier.adapters.upload.cmis_uploader import CmisUploader
from cmcourier.config.schema import AutoTuneConfig, HeavyLightLanesConfig
from cmcourier.domain.exceptions import (
    CMISClientError,
    CMISServerError,
    DefaultValidationFailedError,
    IDRViNotMappedError,
    IndexingError,
    PDFAssemblyFailedError,
    RetriesExhaustedError,
    RVABREPDeletedError,
    RVABREPNotFoundError,
    SourceFailedError,
    SourceFileMissingError,
)
from cmcourier.domain.models import (
    CMMapping,
    MigrationRecord,
    ResolvedMetadata,
    RVABREPDocument,
    StagedFile,
    StageStatus,
    TriggerRecord,
)
from cmcourier.domain.ports import ITrackingStore, S0Strategy
from cmcourier.observability.metrics import MetricsRecorder, StageTimer
from cmcourier.observability.system_metrics import SystemMetricsSampler
from cmcourier.services.auto_tune import AutoTuneController
from cmcourier.services.document_cache import DocumentCacheService
from cmcourier.services.indexing import IndexingService
from cmcourier.services.lane_controller import LaneController
from cmcourier.services.lane_splitter import Lane
from cmcourier.services.lane_splitter import split as split_lanes
from cmcourier.services.mapping import MappingService
from cmcourier.services.metadata import MetadataService
from cmcourier.services.worker_pool_stats import ResizableSemaphore, WorkerPoolStats

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunReport:
    """Outcome summary returned by :meth:`StagedPipeline.run`."""

    batch_id: str
    total_triggers: int
    total_docs: int
    s1_done: int
    s1_skipped_cross_batch: int
    s2_done: int
    s2_failed: int
    s3_done: int
    s3_failed: int
    s4_done: int
    s4_failed: int
    s5_done: int
    s5_failed: int
    elapsed_seconds: float


# ---------------------------------------------------------------------------
# Internal stage state
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _StageItem:
    """Mutable per-doc state threaded through stages S1..S5."""

    trigger: TriggerRecord
    document: RVABREPDocument
    mapping: CMMapping | None = None
    metadata: ResolvedMetadata | None = None
    staged_file: StagedFile | None = None
    cm_object_id: str | None = None


def _size_of_stage_item(item: _StageItem) -> int:
    """Size accessor for the lane splitter (036). 0 when staged_file missing."""
    return item.staged_file.size_bytes if item.staged_file is not None else 0


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class StagedPipeline:
    """``csv-trigger-pipeline`` orchestrator (S0..S6)."""

    def __init__(
        self,
        *,
        trigger_strategy: S0Strategy,
        indexing_service: IndexingService,
        mapping_service: MappingService,
        metadata_service: MetadataService,
        assembler: PdfAssembler,
        uploader: CmisUploader,
        tracking_store: ITrackingStore,
        metrics_recorder: MetricsRecorder | None = None,
        pipeline_name: str = "csv-trigger",
        workers: int = 1,
        pool_stats: WorkerPoolStats | None = None,
        auto_tune: AutoTuneConfig | None = None,
        sampler: SystemMetricsSampler | None = None,
        coordinator: IdempotencyCoordinator | None = None,
        heavy_light_lanes: HeavyLightLanesConfig | None = None,
        document_cache: DocumentCacheService | None = None,
    ) -> None:
        self._trigger_strategy = trigger_strategy
        self._indexing_service = indexing_service
        self._mapping_service = mapping_service
        self._metadata_service = metadata_service
        self._assembler = assembler
        self._uploader = uploader
        self._tracking_store = tracking_store
        self._metrics = metrics_recorder or MetricsRecorder(
            log_dir=Path("./logs"),
            slow_op_threshold_ms=5000.0,
            slow_op_top_n=20,
            enabled=False,
            pipeline_metrics_enabled=False,
        )
        self._pipeline_name = pipeline_name
        self._workers = max(1, int(workers))
        self._pool_stats = pool_stats or WorkerPoolStats()
        # 025 phase 2: soft-cap concurrency limit. Auto-tune adjusts it.
        self._auto_tune_cfg = auto_tune
        self._concurrency_limit = ResizableSemaphore(self._workers)
        # 025 phase 3: build the controller eagerly so the TUI can reference
        # it before run() starts. The controller stays idle (no thread) until
        # ``start()`` is called inside _stage_s5.
        self._auto_tune_controller: AutoTuneController | None = self._build_auto_tune_controller()
        # 026: tier-5 system metrics sampler. The factory returns None when
        # disabled in config; we late-bind the pool stats so a sampler
        # constructed by the wiring layer can report active_workers.
        self._sampler = sampler
        if self._sampler is not None:
            self._sampler.attach_pool_stats(self._pool_stats)
        # 034 phase 3: distributed-idempotency coordinator. When None,
        # is_uploaded / mark_uploaded / mark_failed go straight to the
        # tracking_store (pre-034 behavior). When set, the coordinator
        # adds the AS400 NIARVILOG path on top.
        self._coordinator = coordinator
        # 037: cross-batch metadata cache. None when disabled (default)
        # — S3 always invokes MetadataService.resolve (pre-037 behavior).
        self._document_cache = document_cache
        # 036: heavy/light lane coordinator. None when dual mode is off
        # (the default) — S5 keeps the legacy single-pool path.
        self._lanes_config = heavy_light_lanes
        self._lane_controller: LaneController | None = None
        if heavy_light_lanes is not None and heavy_light_lanes.enabled:
            self._lane_controller = LaneController(
                total_budget=self._workers,
                heavy_initial_ratio=heavy_light_lanes.heavy_initial_ratio,
                rebalance_interval_s=heavy_light_lanes.rebalance_interval_s,
                idle_threshold_s=heavy_light_lanes.idle_threshold_s,
            )

    # ------------------------------------------------- TUI accessors

    @property
    def metrics_recorder(self) -> MetricsRecorder:
        return self._metrics

    @property
    def pool_stats(self) -> WorkerPoolStats:
        return self._pool_stats

    @property
    def concurrency_limit(self) -> ResizableSemaphore:
        return self._concurrency_limit

    @property
    def uploader(self) -> CmisUploader:
        return self._uploader

    @property
    def pipeline_name(self) -> str:
        return self._pipeline_name

    @property
    def auto_tune_controller(self) -> AutoTuneController | None:
        return self._auto_tune_controller

    @property
    def sampler(self) -> SystemMetricsSampler | None:
        return self._sampler

    @property
    def lane_controller(self) -> LaneController | None:
        """036: read-only handle for TUI / tests. ``None`` when dual mode is off."""
        return self._lane_controller

    # --------------------------------------------------- auto-tune wiring

    def _build_auto_tune_controller(self) -> AutoTuneController | None:
        """Return a controller iff ``cmis.auto_tune.enabled``; else None.

        In dual-lane mode (036), AIMD steers the TOTAL worker budget;
        the lane controller owns the per-lane split. ``on_pool_resize``
        dispatches to whichever controller is active.
        """
        if self._auto_tune_cfg is None or not self._auto_tune_cfg.enabled:
            return None
        return AutoTuneController(
            config=self._auto_tune_cfg,
            p95_provider=lambda: self._metrics.current_stage_p95("S5"),
            current_workers_provider=self._current_total_workers,
            current_timeout_provider=lambda: self._uploader._timeout_s,
            on_pool_resize=self._on_pool_resize,
            on_timeout_change=self._set_upload_timeout,
        )

    def _current_total_workers(self) -> int:
        """Return the current TOTAL worker budget across both modes (036)."""
        if self._lane_controller is not None:
            return self._lane_controller.snapshot().total_budget
        return self._concurrency_limit.capacity

    def _on_pool_resize(self, new_total: int) -> None:
        """AIMD pool-resize hook. Dispatches by mode (036)."""
        if self._lane_controller is not None:
            self._lane_controller.set_total_budget(new_total)
        else:
            self._concurrency_limit.set_capacity(new_total)

    def _set_upload_timeout(self, new_timeout_s: float) -> None:
        """AIMD pushes a new timeout; uploader picks it up on the next call."""
        self._uploader._timeout_s = float(new_timeout_s)

    # ----------------------------------------------------------- public API

    def run(
        self,
        *,
        source_descriptor: str,
        batch_size: int = 1000,
        batch_id: str | None = None,
        from_stage: int = 1,
        total: int | None = None,
    ) -> RunReport:
        """Run the csv-trigger pipeline end-to-end.

        ``total`` (033) caps the number of triggers processed after the
        S0 acquire — useful for validating a config against a small
        subset before launching the full migration.
        """
        start = time.monotonic()
        self._validate_parameters(batch_size, from_stage, batch_id)
        resolved_batch_id = self._resolve_batch_id(batch_id, from_stage, batch_size)
        self._metrics.start_batch(pipeline=self._pipeline_name, batch_id=resolved_batch_id)

        if self._sampler is not None:
            self._sampler.start()
        try:
            s0_start = time.monotonic()
            triggers = list(self._trigger_strategy.acquire(source_descriptor))
            if total is not None:
                triggers = triggers[: max(0, total)]
            self._metrics.record_stage(
                stage="S0", duration_ms=(time.monotonic() - s0_start) * 1000.0
            )
            resume_scope = (
                self._tracking_store.list_txn_nums_for_batch(resolved_batch_id)
                if from_stage > 1
                else None
            )

            items, skipped = self._stage_s0_s1(triggers, resolved_batch_id, resume_scope)
            s1_done = len(items)
            items, s2_failed = self._stage_s2(items, resolved_batch_id)
            s2_done = len(items)
            items, s3_failed = self._stage_s3(items, resolved_batch_id)
            s3_done = len(items)
            items, s4_failed = self._stage_s4(items, resolved_batch_id)
            s4_done = len(items)
            controller = self._auto_tune_controller
            try:
                if controller is not None:
                    controller.start()
                # 038: pre-open the S5 TCP+TLS+JSESSIONID connection
                # pool so the first ``self._workers`` uploads do not
                # each pay the handshake on their critical path.
                self._uploader.warm_connection_pool(self._workers)
                s5_done, s5_failed = self._stage_s5(items, resolved_batch_id)
            finally:
                if controller is not None:
                    controller.stop(timeout=2.0)

            self._tracking_store.flush()
            self._tracking_store.complete_batch(resolved_batch_id)
        finally:
            if self._sampler is not None:
                self._sampler.stop()

        elapsed = time.monotonic() - start
        total_docs = s1_done + skipped
        self._metrics.close_batch(
            pipeline=self._pipeline_name,
            batch_id=resolved_batch_id,
            total_docs=total_docs,
            elapsed_s=elapsed,
        )

        return RunReport(
            batch_id=resolved_batch_id,
            total_triggers=len(triggers),
            total_docs=total_docs,
            s1_done=s1_done,
            s1_skipped_cross_batch=skipped,
            s2_done=s2_done,
            s2_failed=s2_failed,
            s3_done=s3_done,
            s3_failed=s3_failed,
            s4_done=s4_done,
            s4_failed=s4_failed,
            s5_done=s5_done,
            s5_failed=s5_failed,
            elapsed_seconds=elapsed,
        )

    # ----------------------------------------------------------- helpers

    @staticmethod
    def _validate_parameters(batch_size: int, from_stage: int, batch_id: str | None) -> None:
        if batch_size < 1:
            raise ValueError(f"batch_size must be >= 1, got {batch_size}")
        if not 1 <= from_stage <= 5:
            raise ValueError(f"from_stage must be in [1, 5], got {from_stage}")
        if from_stage > 1 and batch_id is None:
            raise ValueError("from_stage > 1 requires batch_id")

    def _resolve_batch_id(self, batch_id: str | None, from_stage: int, batch_size: int) -> str:
        if batch_id is not None:
            return batch_id
        return self._tracking_store.start_batch(total_records=batch_size)

    # ----------------------------------------------------- multi-batch entry points
    # 028: prep_chunk / upload_chunk let MultiBatchOrchestrator drive each chunk
    # with its own MetricsRecorder while sharing the rest of the pipeline's
    # state (S5 worker pool, tracking, services, AIMD controller).

    def prep_chunk(
        self,
        *,
        triggers: list[TriggerRecord],
        batch_id: str,
        recorder: MetricsRecorder,
        from_stage: int = 1,
    ) -> tuple[list[_StageItem], int, int, int, int, int]:
        """Run S0..S4 on a pre-acquired chunk of triggers.

        Returns ``(items, skipped, s1_done, s2_failed, s3_failed, s4_failed)``.
        Trigger acquisition is the orchestrator's responsibility — this
        method takes the list directly.
        """
        resume_scope = (
            self._tracking_store.list_txn_nums_for_batch(batch_id) if from_stage > 1 else None
        )
        items, skipped = self._stage_s0_s1(triggers, batch_id, resume_scope, recorder=recorder)
        s1_done = len(items)
        items, s2_failed = self._stage_s2(items, batch_id, recorder=recorder)
        items, s3_failed = self._stage_s3(items, batch_id, recorder=recorder)
        items, s4_failed = self._stage_s4(items, batch_id, recorder=recorder)
        return items, skipped, s1_done, s2_failed, s3_failed, s4_failed

    def upload_chunk(
        self,
        *,
        items: list[_StageItem],
        batch_id: str,
        recorder: MetricsRecorder,
    ) -> tuple[int, int]:
        """Run S5 on a prepared chunk. Returns ``(s5_done, s5_failed)``."""
        return self._stage_s5(items, batch_id, recorder=recorder)

    def _build_record(
        self,
        item: _StageItem,
        batch_id: str,
        stage: StageStatus,
    ) -> MigrationRecord:
        return MigrationRecord(
            trigger_shortname=item.trigger.shortname,
            trigger_cif=item.trigger.cif or "",
            trigger_system_id=item.trigger.system_id,
            rvabrep_txn_num=item.document.txn_num,
            rvabrep_file_name=item.document.file_name,
            batch_id=batch_id,
            status=stage,
            created_at=datetime.now(),  # noqa: DTZ005 — wall-clock for human-readable audit
            cm_folder=item.mapping.cm_folder if item.mapping else None,
            cm_object_type=item.mapping.cm_object_type if item.mapping else None,
            source_file_path=str(item.staged_file.path) if item.staged_file else None,
            page_count=item.staged_file.page_count if item.staged_file else None,
            file_size_bytes=item.staged_file.size_bytes if item.staged_file else None,
        )

    # ----------------------------------------------------------- stages

    def _stage_s0_s1(
        self,
        triggers: list[TriggerRecord],
        batch_id: str,
        resume_scope: set[str] | None,
        *,
        recorder: MetricsRecorder | None = None,
    ) -> tuple[list[_StageItem], int]:
        rec = recorder or self._metrics
        items: list[_StageItem] = []
        skipped_cross_batch = 0
        for trigger in triggers:
            docs: list[RVABREPDocument] = []
            with StageTimer(
                rec,
                pipeline=self._pipeline_name,
                stage="S1",
                batch_id=batch_id,
                txn_num=trigger.shortname,
            ) as timer:
                try:
                    docs = self._indexing_service.find_documents(trigger)
                except RVABREPNotFoundError:
                    timer.mark_failed()
                    _log.warning(
                        "pipeline: trigger has no rvabrep rows",
                        extra={"batch_id": batch_id, "shortname": trigger.shortname},
                    )
                    continue
                except RVABREPDeletedError:
                    timer.mark_failed()
                    _log.warning(
                        "pipeline: every rvabrep row deleted",
                        extra={"batch_id": batch_id, "shortname": trigger.shortname},
                    )
                    continue
                except IndexingError:
                    timer.mark_failed()
                    _log.exception(
                        "pipeline: indexing failed",
                        extra={"batch_id": batch_id, "shortname": trigger.shortname},
                    )
                    continue
            for doc in docs:
                if resume_scope is not None and doc.txn_num not in resume_scope:
                    _log.info(
                        "pipeline: doc out of resume scope",
                        extra={
                            "batch_id": batch_id,
                            "txn_num": doc.txn_num,
                            "reason": "resume_out_of_scope",
                        },
                    )
                    continue
                already_in_batch = self._tracking_store.is_stage_done(
                    doc.txn_num, batch_id, StageStatus.S1_DONE
                )
                if not already_in_batch and self._tracking_store.is_uploaded(doc.txn_num):
                    _log.info(
                        "pipeline: doc already uploaded in prior batch",
                        extra={
                            "batch_id": batch_id,
                            "txn_num": doc.txn_num,
                            "reason": "cross_batch_uploaded",
                        },
                    )
                    skipped_cross_batch += 1
                    continue
                item = _StageItem(trigger=trigger, document=doc)
                if not already_in_batch:
                    record = self._build_record(item, batch_id, StageStatus.S1_PENDING)
                    self._tracking_store.mark_stage_pending(record, StageStatus.S1_PENDING)
                    self._tracking_store.mark_stage_done(doc.txn_num, batch_id, StageStatus.S1_DONE)
                items.append(item)
        return items, skipped_cross_batch

    def _stage_s2(
        self,
        items: list[_StageItem],
        batch_id: str,
        *,
        recorder: MetricsRecorder | None = None,
    ) -> tuple[list[_StageItem], int]:
        rec = recorder or self._metrics
        survivors: list[_StageItem] = []
        failed = 0
        for item in items:
            txn = item.document.txn_num
            with StageTimer(
                rec,
                pipeline=self._pipeline_name,
                stage="S2",
                batch_id=batch_id,
                txn_num=txn,
            ) as timer:
                try:
                    mapping = self._mapping_service.get_mapping(item.document.index7)
                except IDRViNotMappedError as exc:
                    timer.mark_failed()
                    if not self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S2_DONE):
                        record = self._build_record(item, batch_id, StageStatus.S2_PENDING)
                        self._tracking_store.mark_stage_pending(record, StageStatus.S2_PENDING)
                        self._tracking_store.mark_stage_failed(
                            txn, batch_id, StageStatus.S2_FAILED, str(exc)
                        )
                        failed += 1
                    continue
            if not self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S2_DONE):
                record = self._build_record(item, batch_id, StageStatus.S2_PENDING)
                self._tracking_store.mark_stage_pending(record, StageStatus.S2_PENDING)
                self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S2_DONE)
            item.mapping = mapping
            survivors.append(item)
        return survivors, failed

    def _stage_s3(
        self,
        items: list[_StageItem],
        batch_id: str,
        *,
        recorder: MetricsRecorder | None = None,
    ) -> tuple[list[_StageItem], int]:
        rec = recorder or self._metrics
        survivors: list[_StageItem] = []
        failed = 0
        for item in items:
            assert item.mapping is not None
            txn = item.document.txn_num
            fields = item.mapping.required_metadata_fields
            with StageTimer(
                rec,
                pipeline=self._pipeline_name,
                stage="S3",
                batch_id=batch_id,
                txn_num=txn,
            ) as timer:
                cached = (
                    self._document_cache.try_get(txn_num=txn, fields=fields)
                    if self._document_cache is not None
                    else None
                )
                if cached is not None:
                    # 037: cache hit — short-circuit MetadataService. Restore
                    # the healed CIF on the trigger so downstream stages see
                    # the same TriggerRecord shape as a fresh resolve.
                    metadata = ResolvedMetadata.from_dict(dict(cached.properties))
                    healed_trigger = TriggerRecord(
                        shortname=item.trigger.shortname,
                        cif=cached.trigger_cif,
                        system_id=item.trigger.system_id,
                    )
                else:
                    try:
                        resolution = self._metadata_service.resolve(
                            item.trigger, item.document, item.mapping
                        )
                    except (SourceFailedError, DefaultValidationFailedError) as exc:
                        timer.mark_failed()
                        if not self._tracking_store.is_stage_done(
                            txn, batch_id, StageStatus.S3_DONE
                        ):
                            record = self._build_record(item, batch_id, StageStatus.S3_PENDING)
                            self._tracking_store.mark_stage_pending(record, StageStatus.S3_PENDING)
                            self._tracking_store.mark_stage_failed(
                                txn, batch_id, StageStatus.S3_FAILED, str(exc)
                            )
                            failed += 1
                        continue
                    metadata = resolution.metadata
                    healed_trigger = resolution.healed_trigger
                    if self._document_cache is not None:
                        self._document_cache.put(
                            txn_num=txn,
                            fields=fields,
                            metadata=metadata,
                            trigger_cif=healed_trigger.cif,
                        )
            if not self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S3_DONE):
                record = self._build_record(item, batch_id, StageStatus.S3_PENDING)
                self._tracking_store.mark_stage_pending(record, StageStatus.S3_PENDING)
                self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S3_DONE)
            item.metadata = metadata
            item.trigger = healed_trigger
            survivors.append(item)
        return survivors, failed

    def _stage_s4(
        self,
        items: list[_StageItem],
        batch_id: str,
        *,
        recorder: MetricsRecorder | None = None,
    ) -> tuple[list[_StageItem], int]:
        rec = recorder or self._metrics
        survivors: list[_StageItem] = []
        failed = 0
        for item in items:
            txn = item.document.txn_num
            with StageTimer(
                rec,
                pipeline=self._pipeline_name,
                stage="S4",
                batch_id=batch_id,
                txn_num=txn,
            ) as timer:
                try:
                    staged = self._assembler.assemble(item.document)
                except (SourceFileMissingError, PDFAssemblyFailedError) as exc:
                    timer.mark_failed()
                    if not self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S4_DONE):
                        record = self._build_record(item, batch_id, StageStatus.S4_PENDING)
                        self._tracking_store.mark_stage_pending(record, StageStatus.S4_PENDING)
                        self._tracking_store.mark_stage_failed(
                            txn, batch_id, StageStatus.S4_FAILED, str(exc)
                        )
                        failed += 1
                    continue
            if not self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S4_DONE):
                record = self._build_record(item, batch_id, StageStatus.S4_PENDING)
                self._tracking_store.mark_stage_pending(record, StageStatus.S4_PENDING)
                self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S4_DONE)
            item.staged_file = staged
            survivors.append(item)
        return survivors, failed

    def _stage_s5(
        self,
        items: list[_StageItem],
        batch_id: str,
        *,
        recorder: MetricsRecorder | None = None,
    ) -> tuple[int, int]:
        """S5 uploads, parallelized over ``self._workers`` threads (025).

        Tracking-store calls remain serialized by the writer queue;
        `CmisUploader` is thread-safe per 025 R011/R012; per-stage
        metrics use a lock under the hood. Outcomes are tallied in
        the main thread from ``as_completed`` results.

        028: ``recorder`` lets the multi-batch orchestrator route
        S5 timings to the per-chunk recorder.
        """
        rec = recorder or self._metrics
        # 036: when dual-lane is configured AND the splitter says it's
        # worth it, dispatch each item with its lane tag. Otherwise the
        # legacy single-pool path runs byte-identically to pre-036.
        assignment = self._partition_for_lanes(items)
        if assignment is None:
            return self._stage_5_single(items, batch_id, rec)
        return self._stage_5_dual(assignment, batch_id, rec)

    def _stage_5_single(
        self,
        items: list[_StageItem],
        batch_id: str,
        rec: MetricsRecorder,
    ) -> tuple[int, int]:
        """Legacy single-pool S5 (pre-036). Byte-identical to 025."""
        self._pool_stats.set_pool_size(self._workers)
        self._pool_stats.set_queue_depth(len(items))
        s5_done = 0
        failed = 0
        with ThreadPoolExecutor(
            max_workers=self._workers,
            thread_name_prefix="cmcourier-s5",
        ) as pool:
            futures = {pool.submit(self._upload_one, item, batch_id, rec): item for item in items}
            for fut in as_completed(futures):
                outcome = fut.result()
                if outcome == "done":
                    s5_done += 1
                elif outcome == "failed":
                    failed += 1
                self._pool_stats.set_queue_depth(self._pool_stats.snapshot().queue_depth - 1)
        return s5_done, failed

    def _partition_for_lanes(
        self, items: list[_StageItem]
    ) -> tuple[tuple[_StageItem, ...], tuple[_StageItem, ...]] | None:
        """Return ``(heavy, light)`` items when dual mode applies, else ``None``."""
        if self._lane_controller is None or self._lanes_config is None:
            return None
        if not self._lanes_config.enabled:
            return None
        assignment = split_lanes(
            items,
            threshold_bytes=self._lanes_config.heavy_threshold_bytes,
            min_batch=self._lanes_config.heavy_lane_min_batch,
            size_of=_size_of_stage_item,
        )
        if assignment.is_single_lane:
            return None
        return assignment.heavy, assignment.light

    def _stage_5_dual(
        self,
        assignment: tuple[tuple[_StageItem, ...], tuple[_StageItem, ...]],
        batch_id: str,
        rec: MetricsRecorder,
    ) -> tuple[int, int]:
        """036: dual heavy/light dispatch via two cooperating executors.

        Each lane gets its own ``ThreadPoolExecutor`` sized to the
        TOTAL worker budget; the per-lane semaphore inside the
        ``LaneController`` caps actual concurrency. Two executors
        avoid the starvation that would occur if a single executor's
        workers grabbed heavies first and then blocked on the heavy
        semaphore — leaving light items queued without a thread to
        run them.
        """
        assert self._lane_controller is not None
        heavy_items, light_items = assignment
        depths: dict[Lane, int] = {"heavy": len(heavy_items), "light": len(light_items)}
        self._lane_controller.set_queue_depth("heavy", depths["heavy"])
        self._lane_controller.set_queue_depth("light", depths["light"])
        self._lane_controller.start()
        s5_done = 0
        failed = 0
        try:
            with (
                ThreadPoolExecutor(
                    max_workers=self._workers,
                    thread_name_prefix="cmcourier-s5-heavy",
                ) as heavy_pool,
                ThreadPoolExecutor(
                    max_workers=self._workers,
                    thread_name_prefix="cmcourier-s5-light",
                ) as light_pool,
            ):
                futures: dict[Future[Literal["done", "failed", "skipped"]], Lane] = {}
                for item in heavy_items:
                    futures[heavy_pool.submit(self._upload_one, item, batch_id, rec, "heavy")] = (
                        "heavy"
                    )
                for item in light_items:
                    futures[light_pool.submit(self._upload_one, item, batch_id, rec, "light")] = (
                        "light"
                    )
                for fut in as_completed(futures):
                    lane = futures[fut]
                    outcome = fut.result()
                    if outcome == "done":
                        s5_done += 1
                    elif outcome == "failed":
                        failed += 1
                    depths[lane] = max(0, depths[lane] - 1)
                    self._lane_controller.set_queue_depth(lane, depths[lane])
        finally:
            self._lane_controller.stop()
        return s5_done, failed

    def _upload_one(
        self,
        item: _StageItem,
        batch_id: str,
        recorder: MetricsRecorder | None = None,
        lane: Lane | None = None,
    ) -> Literal["done", "failed", "skipped"]:
        """Per-doc S5 work executed inside a worker thread (025 + 036).

        When ``lane`` is None, the legacy single-pool semaphore +
        stats path runs (pre-036). When set, the per-lane semaphore
        and counters of the :class:`LaneController` are used instead.
        """
        assert item.mapping is not None
        assert item.metadata is not None
        assert item.staged_file is not None
        txn = item.document.txn_num
        worker_name = threading.current_thread().name

        # 025 phase 2: respect the auto-tune semaphore cap before
        # actually consuming a worker slot.
        if lane is None:
            self._concurrency_limit.acquire()
            self._pool_stats.mark_busy(worker_name)
        else:
            assert self._lane_controller is not None
            self._lane_controller.acquire(lane)
        try:
            if self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S5_DONE):
                self._mark_completed(lane)
                return "done"
            record = self._build_record(item, batch_id, StageStatus.S5_PENDING)
            self._tracking_store.mark_stage_pending(record, StageStatus.S5_PENDING)
            # 034 phase 3: distributed claim. When the coordinator is
            # None (legacy path), try_claim is always True. When
            # active, the coordinator goes to AS400 NIARVILOG; if
            # someone else already owns the row (Java competitor or
            # another CMCourier instance), we skip.
            if self._coordinator is not None and not self._coordinator.try_claim(
                record=record,
                document=item.document,
                mapping=item.mapping,
                trigger=item.trigger,
            ):
                _log.info(
                    "pipeline: doc claimed by another process",
                    extra={
                        "batch_id": batch_id,
                        "txn_num": txn,
                        "reason": "as400_claim_lost",
                    },
                )
                self._mark_completed(lane)
                return "skipped"
            with StageTimer(
                recorder or self._metrics,
                pipeline=self._pipeline_name,
                stage="S5",
                batch_id=batch_id,
                txn_num=txn,
            ) as timer:
                try:
                    # 039: ``cmis_type`` (MapeoRVI_CM.CMISType, 035)
                    # overrides the derived ``cm_object_type`` when set.
                    # 038: ``cmis_folder`` (MapeoRVI_CM.CMISFolder)
                    # overrides the derived ``cm_folder`` when set. Both
                    # let non-IBM-CM repositories (Alfresco staging, or
                    # future bank types that don't follow the
                    # ``$t!-N_BAC_…v-1`` pattern) work without code change.
                    object_type_id = item.mapping.cmis_type or item.mapping.cm_object_type
                    folder_path = item.mapping.cmis_folder or item.mapping.cm_folder
                    cm_object_id = self._uploader.upload(
                        file=item.staged_file,
                        folder_path=folder_path,
                        object_type_id=object_type_id,
                        document_name=f"{txn}.pdf",
                        mime_type="application/pdf",
                        properties=dict(item.metadata.properties),
                    )
                except (CMISClientError, CMISServerError, RetriesExhaustedError) as exc:
                    timer.mark_failed()
                    if self._coordinator is not None:
                        self._coordinator.mark_failed(
                            record=record,
                            document=item.document,
                            mapping=item.mapping,
                            trigger=item.trigger,
                            stage=StageStatus.S5_FAILED,
                            error=str(exc),
                        )
                    else:
                        self._tracking_store.mark_stage_failed(
                            txn, batch_id, StageStatus.S5_FAILED, str(exc)
                        )
                    self._mark_failed(lane)
                    return "failed"
            if self._coordinator is not None:
                self._coordinator.mark_uploaded(
                    record=record,
                    document=item.document,
                    mapping=item.mapping,
                    trigger=item.trigger,
                    cm_object_id=cm_object_id,
                )
            else:
                self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S5_DONE)
            item.cm_object_id = cm_object_id
            self._mark_completed(lane)
            return "done"
        finally:
            if lane is None:
                self._pool_stats.mark_idle(worker_name)
                self._concurrency_limit.release()
            else:
                assert self._lane_controller is not None
                self._lane_controller.release(lane)

    def _mark_completed(self, lane: Lane | None) -> None:
        if lane is None:
            self._pool_stats.mark_completed()
        else:
            assert self._lane_controller is not None
            self._lane_controller.mark_completed(lane)

    def _mark_failed(self, lane: Lane | None) -> None:
        if lane is None:
            self._pool_stats.mark_failed()
        else:
            assert self._lane_controller is not None
            self._lane_controller.mark_failed(lane)

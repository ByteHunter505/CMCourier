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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from cmcourier.adapters.assembly import PdfAssembler
from cmcourier.adapters.upload.cmis_uploader import CmisUploader
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
from cmcourier.services.indexing import IndexingService
from cmcourier.services.mapping import MappingService
from cmcourier.services.metadata import MetadataService
from cmcourier.services.worker_pool_stats import WorkerPoolStats

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

    # ----------------------------------------------------------- public API

    def run(
        self,
        *,
        source_descriptor: str,
        batch_size: int = 1000,
        batch_id: str | None = None,
        from_stage: int = 1,
    ) -> RunReport:
        """Run the csv-trigger pipeline end-to-end."""
        start = time.monotonic()
        self._validate_parameters(batch_size, from_stage, batch_id)
        resolved_batch_id = self._resolve_batch_id(batch_id, from_stage, batch_size)
        self._metrics.start_batch(pipeline=self._pipeline_name, batch_id=resolved_batch_id)

        s0_start = time.monotonic()
        triggers = list(self._trigger_strategy.acquire(source_descriptor))
        self._metrics.record_stage(stage="S0", duration_ms=(time.monotonic() - s0_start) * 1000.0)
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
        s5_done, s5_failed = self._stage_s5(items, resolved_batch_id)

        self._tracking_store.flush()
        self._tracking_store.complete_batch(resolved_batch_id)

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
    ) -> tuple[list[_StageItem], int]:
        items: list[_StageItem] = []
        skipped_cross_batch = 0
        for trigger in triggers:
            docs: list[RVABREPDocument] = []
            with StageTimer(
                self._metrics,
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
    ) -> tuple[list[_StageItem], int]:
        survivors: list[_StageItem] = []
        failed = 0
        for item in items:
            txn = item.document.txn_num
            with StageTimer(
                self._metrics,
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
    ) -> tuple[list[_StageItem], int]:
        survivors: list[_StageItem] = []
        failed = 0
        for item in items:
            assert item.mapping is not None
            txn = item.document.txn_num
            with StageTimer(
                self._metrics,
                pipeline=self._pipeline_name,
                stage="S3",
                batch_id=batch_id,
                txn_num=txn,
            ) as timer:
                try:
                    resolution = self._metadata_service.resolve(
                        item.trigger, item.document, item.mapping
                    )
                except (SourceFailedError, DefaultValidationFailedError) as exc:
                    timer.mark_failed()
                    if not self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S3_DONE):
                        record = self._build_record(item, batch_id, StageStatus.S3_PENDING)
                        self._tracking_store.mark_stage_pending(record, StageStatus.S3_PENDING)
                        self._tracking_store.mark_stage_failed(
                            txn, batch_id, StageStatus.S3_FAILED, str(exc)
                        )
                        failed += 1
                    continue
            if not self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S3_DONE):
                record = self._build_record(item, batch_id, StageStatus.S3_PENDING)
                self._tracking_store.mark_stage_pending(record, StageStatus.S3_PENDING)
                self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S3_DONE)
            item.metadata = resolution.metadata
            item.trigger = resolution.healed_trigger
            survivors.append(item)
        return survivors, failed

    def _stage_s4(
        self,
        items: list[_StageItem],
        batch_id: str,
    ) -> tuple[list[_StageItem], int]:
        survivors: list[_StageItem] = []
        failed = 0
        for item in items:
            txn = item.document.txn_num
            with StageTimer(
                self._metrics,
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
    ) -> tuple[int, int]:
        """S5 uploads, parallelized over ``self._workers`` threads (025).

        Tracking-store calls remain serialized by the writer queue;
        `CmisUploader` is thread-safe per 025 R011/R012; per-stage
        metrics use a lock under the hood. Outcomes are tallied in
        the main thread from ``as_completed`` results.
        """
        self._pool_stats.set_pool_size(self._workers)
        self._pool_stats.set_queue_depth(len(items))
        s5_done = 0
        failed = 0
        with ThreadPoolExecutor(
            max_workers=self._workers,
            thread_name_prefix="cmcourier-s5",
        ) as pool:
            futures = {pool.submit(self._upload_one, item, batch_id): item for item in items}
            for fut in as_completed(futures):
                outcome = fut.result()
                if outcome == "done":
                    s5_done += 1
                elif outcome == "failed":
                    failed += 1
                self._pool_stats.set_queue_depth(self._pool_stats.snapshot().queue_depth - 1)
        return s5_done, failed

    def _upload_one(
        self,
        item: _StageItem,
        batch_id: str,
    ) -> Literal["done", "failed", "skipped"]:
        """Per-doc S5 work executed inside a worker thread (025)."""
        assert item.mapping is not None
        assert item.metadata is not None
        assert item.staged_file is not None
        txn = item.document.txn_num
        worker_name = threading.current_thread().name

        self._pool_stats.mark_busy(worker_name)
        try:
            if self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S5_DONE):
                self._pool_stats.mark_completed()
                return "done"
            record = self._build_record(item, batch_id, StageStatus.S5_PENDING)
            self._tracking_store.mark_stage_pending(record, StageStatus.S5_PENDING)
            with StageTimer(
                self._metrics,
                pipeline=self._pipeline_name,
                stage="S5",
                batch_id=batch_id,
                txn_num=txn,
            ) as timer:
                try:
                    cm_object_id = self._uploader.upload(
                        file=item.staged_file,
                        folder_path=item.mapping.cm_folder,
                        object_type_id=item.mapping.cm_object_type,
                        document_name=f"{txn}.pdf",
                        mime_type="application/pdf",
                        properties=dict(item.metadata.properties),
                    )
                except (CMISClientError, CMISServerError, RetriesExhaustedError) as exc:
                    timer.mark_failed()
                    self._tracking_store.mark_stage_failed(
                        txn, batch_id, StageStatus.S5_FAILED, str(exc)
                    )
                    self._pool_stats.mark_failed()
                    return "failed"
            self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S5_DONE)
            item.cm_object_id = cm_object_id
            self._pool_stats.mark_completed()
            return "done"
        finally:
            self._pool_stats.mark_idle(worker_name)

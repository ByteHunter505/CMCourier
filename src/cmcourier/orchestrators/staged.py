"""Stage S0..S6 orchestrator for the ``csv-trigger-pipeline`` (REBIRTH §10.2).

Wires the seven collaborators (S0 trigger strategy + S1..S5 services /
adapters + S6 tracking store) into one runnable pipeline. The orchestrator
contains no business logic — only coordination, error handling, and
counting (Constitution Principle III).

Two top-level behaviors:

* **Cross-batch idempotency** (REBIRTH §10): docs whose ``txn_num`` is
  already at ``S5_DONE`` in any prior batch are skipped — they don't
  re-upload, but 062 reversed §10's "silent skip" contract and the
  current batch now writes a ``migration_log`` row with
  ``status=S1_SKIPPED`` so the DETAIL tab + analyzer + ``batch show``
  can identify which specific docs landed in this bucket.
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
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from cmcourier.services.idempotency import IdempotencyCoordinator

from cmcourier.adapters.assembly import PdfAssembler
from cmcourier.adapters.assembly.pool import _pool_assemble
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
    ClientTrigger,
    CMMapping,
    MigrationRecord,
    ResolvedMetadata,
    RVABREPDocument,
    StagedFile,
    StageStatus,
    Trigger,
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
    s1_filtered: int
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

    trigger: Trigger
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
        prep_workers: int = 1,
        pool_stats: WorkerPoolStats | None = None,
        auto_tune: AutoTuneConfig | None = None,
        sampler: SystemMetricsSampler | None = None,
        coordinator: IdempotencyCoordinator | None = None,
        heavy_light_lanes: HeavyLightLanesConfig | None = None,
        document_cache: DocumentCacheService | None = None,
        s4_process_pool: ProcessPoolExecutor | None = None,
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
        # 056: fixed-size thread pool for the prep stages S2/S3/S4.
        # 1 == serial (byte-identical to pre-056). S0/S1 stay serial.
        self._prep_workers = max(1, int(prep_workers))
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
        # 066: optional process pool for S4 (PDF assembly). When set,
        # ``_s4_one`` submits to the pool instead of calling the
        # assembler directly — bypasses the GIL for CPU-bound work.
        # ``None`` runs S4 inline (pre-066 behaviour, byte-identical).
        self._s4_process_pool = s4_process_pool
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

    @property
    def tracking_store(self) -> ITrackingStore:
        """052: read-only handle for the TUI's per-chunk drill-down."""
        return self._tracking_store

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
            p95_provider=lambda: self._metrics.current_stage_p95_with_count("S5"),
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

    def _pool_ceiling(self) -> int:
        """057: the maximum thread count S5 could ever need.

        The S5 ``ThreadPoolExecutor`` must be sized to this — NOT to the
        initial ``cmis.workers``. AIMD resizes the ``ResizableSemaphore``
        / ``LaneController`` up to ``auto_tune.max_threads``; if the pool
        only has ``cmis.workers`` threads, those extra semaphore slots
        have no thread to run them and ``pool_in_use`` stays pinned at
        the initial count. With AIMD disabled nothing resizes the
        semaphore, so ``cmis.workers`` is already the correct ceiling.
        """
        if self._auto_tune_cfg is not None and self._auto_tune_cfg.enabled:
            return max(self._workers, self._auto_tune_cfg.max_threads)
        return self._workers

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

            items, skipped, s1_filtered = self._stage_s0_s1(
                triggers, resolved_batch_id, resume_scope
            )
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
            s1_filtered=s1_filtered,
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
        triggers: list[Trigger],
        batch_id: str,
        recorder: MetricsRecorder,
        from_stage: int = 1,
    ) -> tuple[list[_StageItem], int, int, int, int, int, int]:
        """Run S0..S4 on a pre-acquired chunk of triggers.

        Returns ``(items, skipped, s1_done, s1_filtered, s2_failed,
        s3_failed, s4_failed)``. Trigger acquisition is the
        orchestrator's responsibility — this method takes the list
        directly.
        """
        resume_scope = (
            self._tracking_store.list_txn_nums_for_batch(batch_id) if from_stage > 1 else None
        )
        items, skipped, s1_filtered = self._stage_s0_s1(
            triggers, batch_id, resume_scope, recorder=recorder
        )
        s1_done = len(items)
        items, s2_failed = self._stage_s2(items, batch_id, recorder=recorder)
        items, s3_failed = self._stage_s3(items, batch_id, recorder=recorder)
        items, s4_failed = self._stage_s4(items, batch_id, recorder=recorder)
        return items, skipped, s1_done, s1_filtered, s2_failed, s3_failed, s4_failed

    def upload_chunk(
        self,
        *,
        items: list[_StageItem],
        batch_id: str,
        recorder: MetricsRecorder,
    ) -> tuple[int, int]:
        """Run S5 on a prepared chunk. Returns ``(s5_done, s5_failed)``."""
        return self._stage_s5(items, batch_id, recorder=recorder)

    # ----------------------------------------------------- streaming (063)

    def streaming_prep_one(
        self,
        trigger: Trigger,
        batch_id: str,
        recorder: MetricsRecorder,
    ) -> tuple[_StageItem | None, int, int]:
        """063: run S1→S4 on a single trigger and return the survivor.

        Used by :class:`StreamingOrchestrator` producers. Returns
        ``(survivor, skipped_cross_batch, s1_filtered)``:

        * ``survivor`` is the sole surviving ``_StageItem`` or ``None``
          (filtered / cross-batch skipped / failed at S2-S4).
        * ``skipped_cross_batch`` is 1 when the trigger's RVABREP doc
          was already uploaded in a prior batch (062 ``S1_SKIPPED``).
        * ``s1_filtered`` is 1 when the RVABREP row was delete-coded
          (062 ``S1_FILTERED``).

        Failure / filter / skip persistence is done by the inner
        per-stage helpers — this method adds no behaviour of its own
        beyond sequencing.
        """
        items, skipped, filtered = self._stage_s0_s1(
            [trigger], batch_id, resume_scope=None, recorder=recorder
        )
        if not items:
            return None, skipped, filtered
        survivor, _ = self._s2_one(items[0], batch_id, recorder)
        if survivor is None:
            return None, skipped, filtered
        survivor, _ = self._s3_one(survivor, batch_id, recorder)
        if survivor is None:
            return None, skipped, filtered
        survivor, _ = self._s4_one(survivor, batch_id, recorder)
        return survivor, skipped, filtered

    def streaming_upload_one(
        self,
        item: _StageItem,
        batch_id: str,
        recorder: MetricsRecorder,
        lane: Lane | None = None,
    ) -> Literal["done", "failed", "skipped"]:
        """063: run S5 on a single prepared item.

        ``lane`` (065) selects between the single-pool semaphore +
        worker-pool-stats (``None``) and the per-lane semaphore inside
        the :class:`LaneController` (``"heavy"`` / ``"light"``). The
        existing ``_upload_one`` handles both paths uniformly — this
        is a thin public wrapper.
        """
        return self._upload_one(item, batch_id, recorder, lane)

    def warm_upload_pool(self, workers: int) -> None:
        """063: pre-open the S5 connection pool to ``workers`` sockets."""
        self._uploader.warm_connection_pool(workers)

    def _build_record(
        self,
        item: _StageItem,
        batch_id: str,
        stage: StageStatus,
    ) -> MigrationRecord:
        # 046: triggers are polymorphic; audit_row() returns the best-effort
        # projection for the trigger_* migration_log columns.
        audit = item.trigger.audit_row()
        return MigrationRecord(
            trigger_shortname=audit.get("shortname") or "",
            trigger_cif=audit.get("cif") or "",
            trigger_system_id=audit.get("system_id") or "",
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
        triggers: list[Trigger],
        batch_id: str,
        resume_scope: set[str] | None,
        *,
        recorder: MetricsRecorder | None = None,
    ) -> tuple[list[_StageItem], int, int]:
        rec = recorder or self._metrics
        items: list[_StageItem] = []
        skipped_cross_batch = 0
        # 051: a trigger whose RVABREP row is delete-coded is *filtered* —
        # a first-class outcome, NOT a failure and NOT a silent drop.
        filtered = 0
        for trigger in triggers:
            audit = trigger.audit_row()
            audit_shortname = audit.get("shortname") or "<unknown>"
            docs: list[RVABREPDocument] = []
            with StageTimer(
                rec,
                pipeline=self._pipeline_name,
                stage="S1",
                batch_id=batch_id,
                txn_num=audit_shortname,
            ) as timer:
                try:
                    docs = self._indexing_service.enrich(trigger)
                except RVABREPNotFoundError:
                    timer.mark_failed()
                    _log.warning(
                        "pipeline: trigger has no rvabrep rows",
                        extra={"batch_id": batch_id, "shortname": audit_shortname},
                    )
                    continue
                except RVABREPDeletedError as exc:
                    # 051: deleted-at-source is NOT a pipeline failure — the
                    # doc is correctly excluded. Count it, log it, move on.
                    # 062: persist a `S1_FILTERED` row in migration_log so the
                    # DETAIL tab + analyzer + `batch show` can see WHICH
                    # triggers were filtered and why. The exception fires
                    # before any txn_num is derived, so we use a synthetic
                    # key keyed on the trigger identity — re-runs collide
                    # idempotently via INSERT OR IGNORE.
                    filtered += 1
                    audit_system_id = audit.get("system_id") or ""
                    synthetic_txn = f"FILTERED__{audit_shortname}__{audit_system_id}"
                    filtered_record = MigrationRecord(
                        trigger_shortname=audit_shortname,
                        trigger_cif=audit.get("cif") or "",
                        trigger_system_id=audit_system_id,
                        rvabrep_txn_num=synthetic_txn,
                        rvabrep_file_name="",
                        batch_id=batch_id,
                        status=StageStatus.S1_PENDING,
                        created_at=datetime.now(),  # noqa: DTZ005
                    )
                    self._tracking_store.mark_stage_pending(filtered_record, StageStatus.S1_PENDING)
                    self._tracking_store.mark_stage_terminal(
                        synthetic_txn,
                        batch_id,
                        StageStatus.S1_FILTERED,
                        f"deleted_at_source; deleted_count={exc.deleted_count}",
                    )
                    _log.info(
                        "pipeline: doc filtered at S1",
                        extra={
                            "batch_id": batch_id,
                            "shortname": audit_shortname,
                            "reason": "deleted_at_source",
                        },
                    )
                    continue
                except IndexingError:
                    timer.mark_failed()
                    _log.exception(
                        "pipeline: indexing failed",
                        extra={"batch_id": batch_id, "shortname": audit_shortname},
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
                    # 062: persist a ``S1_SKIPPED`` row so the DETAIL tab +
                    # analyzer + `batch show` can see which docs were
                    # cross-batch skipped (REBIRTH §10's "silently skipped"
                    # contract is intentionally reversed for traceability).
                    skipped_cross_batch += 1
                    skip_item = _StageItem(trigger=trigger, document=doc)
                    skip_record = self._build_record(skip_item, batch_id, StageStatus.S1_PENDING)
                    self._tracking_store.mark_stage_pending(skip_record, StageStatus.S1_PENDING)
                    self._tracking_store.mark_stage_terminal(
                        doc.txn_num,
                        batch_id,
                        StageStatus.S1_SKIPPED,
                        "cross_batch_uploaded",
                    )
                    _log.info(
                        "pipeline: doc already uploaded in prior batch",
                        extra={
                            "batch_id": batch_id,
                            "txn_num": doc.txn_num,
                            "reason": "cross_batch_uploaded",
                        },
                    )
                    continue
                item = _StageItem(trigger=trigger, document=doc)
                if not already_in_batch:
                    record = self._build_record(item, batch_id, StageStatus.S1_PENDING)
                    self._tracking_store.mark_stage_pending(record, StageStatus.S1_PENDING)
                    self._tracking_store.mark_stage_done(doc.txn_num, batch_id, StageStatus.S1_DONE)
                items.append(item)
        return items, skipped_cross_batch, filtered

    def _run_prep_stage(
        self,
        items: list[_StageItem],
        worker: Callable[[_StageItem], tuple[_StageItem | None, bool]],
    ) -> tuple[list[_StageItem], int]:
        """056: dispatch one prep stage's per-item worker.

        ``prep_workers == 1`` runs serially — byte-identical to the
        pre-056 loop. Above 1, a fixed ``ThreadPoolExecutor`` runs the
        worker; ``pool.map`` preserves input order, so ``survivors``
        stays deterministic regardless of completion order. Each
        worker returns ``(survivor_or_None, counted_failure)``.
        """
        if self._prep_workers == 1:
            results = [worker(item) for item in items]
        else:
            with ThreadPoolExecutor(
                max_workers=self._prep_workers,
                thread_name_prefix="cmcourier-prep",
            ) as pool:
                results = list(pool.map(worker, items))
        survivors = [item for item, _ in results if item is not None]
        failed = sum(1 for _, counted in results if counted)
        return survivors, failed

    def _stage_s2(
        self,
        items: list[_StageItem],
        batch_id: str,
        *,
        recorder: MetricsRecorder | None = None,
    ) -> tuple[list[_StageItem], int]:
        rec = recorder or self._metrics
        return self._run_prep_stage(items, lambda item: self._s2_one(item, batch_id, rec))

    def _s2_one(
        self, item: _StageItem, batch_id: str, rec: MetricsRecorder
    ) -> tuple[_StageItem | None, bool]:
        """S2 mapping for one item. Returns ``(survivor_or_None,
        counted_failure)`` — a failure already marked done in a prior
        run is dropped without being counted."""
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
                    return None, True
                return None, False
        if not self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S2_DONE):
            record = self._build_record(item, batch_id, StageStatus.S2_PENDING)
            self._tracking_store.mark_stage_pending(record, StageStatus.S2_PENDING)
            self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S2_DONE)
        item.mapping = mapping
        return item, False

    def _stage_s3(
        self,
        items: list[_StageItem],
        batch_id: str,
        *,
        recorder: MetricsRecorder | None = None,
    ) -> tuple[list[_StageItem], int]:
        rec = recorder or self._metrics
        return self._run_prep_stage(items, lambda item: self._s3_one(item, batch_id, rec))

    def _s3_one(
        self, item: _StageItem, batch_id: str, rec: MetricsRecorder
    ) -> tuple[_StageItem | None, bool]:
        """S3 metadata resolution for one item. Returns
        ``(survivor_or_None, counted_failure)``."""
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
                # 037: cache hit — short-circuit MetadataService.
                # 046: triggers are polymorphic. For a ClientTrigger
                # we reconstruct with the cached CIF so downstream
                # code that reads ``.cif`` directly stays consistent;
                # for row-based triggers we keep the original (the row
                # is immutable, the cached cif lives in the metadata
                # bag's BAC_CIF property anyway).
                metadata = ResolvedMetadata.from_dict(dict(cached.properties))
                healed_trigger: Trigger
                if isinstance(item.trigger, ClientTrigger):
                    healed_trigger = ClientTrigger(
                        shortname=item.trigger.shortname,
                        cif=cached.trigger_cif,
                        system_id=item.trigger.system_id,
                    )
                else:
                    healed_trigger = item.trigger
                healed_cif: str | None = cached.trigger_cif
            else:
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
                        return None, True
                    return None, False
                metadata = resolution.metadata
                healed_trigger = resolution.healed_trigger
                healed_cif = resolution.healed_cif
                if self._document_cache is not None:
                    self._document_cache.put(
                        txn_num=txn,
                        fields=fields,
                        metadata=metadata,
                        trigger_cif=healed_cif,
                    )
        if not self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S3_DONE):
            record = self._build_record(item, batch_id, StageStatus.S3_PENDING)
            self._tracking_store.mark_stage_pending(record, StageStatus.S3_PENDING)
            self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S3_DONE)
        item.metadata = metadata
        item.trigger = healed_trigger
        return item, False

    def _stage_s4(
        self,
        items: list[_StageItem],
        batch_id: str,
        *,
        recorder: MetricsRecorder | None = None,
    ) -> tuple[list[_StageItem], int]:
        rec = recorder or self._metrics
        return self._run_prep_stage(items, lambda item: self._s4_one(item, batch_id, rec))

    def _s4_one(
        self, item: _StageItem, batch_id: str, rec: MetricsRecorder
    ) -> tuple[_StageItem | None, bool]:
        """S4 PDF assembly for one item. Returns ``(survivor_or_None,
        counted_failure)``.

        066: when ``_s4_process_pool`` is set, dispatches via
        ``pool.submit(_pool_assemble, ...).result()`` so the
        CPU-bound work runs in a separate process — bypassing the
        GIL. The producer thread blocks waiting for the future but
        releases the GIL, letting other producers run S1-S3 work.
        """
        txn = item.document.txn_num
        with StageTimer(
            rec,
            pipeline=self._pipeline_name,
            stage="S4",
            batch_id=batch_id,
            txn_num=txn,
        ) as timer:
            try:
                if self._s4_process_pool is not None:
                    staged = self._s4_process_pool.submit(_pool_assemble, item.document).result()
                else:
                    staged = self._assembler.assemble(item.document)
            except (SourceFileMissingError, PDFAssemblyFailedError) as exc:
                timer.mark_failed()
                if not self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S4_DONE):
                    record = self._build_record(item, batch_id, StageStatus.S4_PENDING)
                    self._tracking_store.mark_stage_pending(record, StageStatus.S4_PENDING)
                    self._tracking_store.mark_stage_failed(
                        txn, batch_id, StageStatus.S4_FAILED, str(exc)
                    )
                    return None, True
                return None, False
        if not self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S4_DONE):
            record = self._build_record(item, batch_id, StageStatus.S4_PENDING)
            self._tracking_store.mark_stage_pending(record, StageStatus.S4_PENDING)
            self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S4_DONE)
        item.staged_file = staged
        # 058: the row was INSERT-OR-IGNORE'd in S1 with NULL metadata
        # (item.staged_file was None then). Now that the assembler has
        # produced the real values, persist them so the DETAIL tab and
        # ``cmcourier batch show`` actually see the file's size + page
        # count + path. Outside the is_stage_done guard so resume runs
        # also backfill any pre-058 rows.
        self._tracking_store.record_staged_file_metadata(
            txn,
            batch_id,
            source_file_path=str(staged.path),
            page_count=staged.page_count,
            file_size_bytes=staged.size_bytes,
        )
        return item, False

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
        """Legacy single-pool S5 (pre-036). Byte-identical to 025.

        057: the pool is sized to ``_pool_ceiling()`` (the AIMD max),
        not the initial ``cmis.workers`` — otherwise the AIMD-resized
        ``ResizableSemaphore`` has no threads to honour its extra slots.
        """
        ceiling = self._pool_ceiling()
        self._pool_stats.set_pool_size(ceiling)
        self._pool_stats.set_queue_depth(len(items))
        s5_done = 0
        failed = 0
        with ThreadPoolExecutor(
            max_workers=ceiling,
            thread_name_prefix="cmcourier-s5",
        ) as pool:
            futures = {pool.submit(self._upload_one, item, batch_id, rec): item for item in items}
            for fut in as_completed(futures):
                outcome = fut.result()
                if outcome == "done":
                    s5_done += 1
                    rec.record_upload_done()
                elif outcome == "failed":
                    failed += 1
                    rec.record_upload_failed()
                elif outcome == "skipped":
                    rec.record_upload_skipped()
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
        TOTAL worker budget ceiling (057: ``_pool_ceiling()``, the AIMD
        max — not the initial ``cmis.workers``); the per-lane semaphore
        inside the ``LaneController`` caps actual concurrency. Two
        executors avoid the starvation that would occur if a single
        executor's workers grabbed heavies first and then blocked on
        the heavy semaphore — leaving light items queued without a
        thread to run them.
        """
        assert self._lane_controller is not None
        heavy_items, light_items = assignment
        depths: dict[Lane, int] = {"heavy": len(heavy_items), "light": len(light_items)}
        self._lane_controller.set_queue_depth("heavy", depths["heavy"])
        self._lane_controller.set_queue_depth("light", depths["light"])
        self._lane_controller.start()
        ceiling = self._pool_ceiling()
        s5_done = 0
        failed = 0
        try:
            with (
                ThreadPoolExecutor(
                    max_workers=ceiling,
                    thread_name_prefix="cmcourier-s5-heavy",
                ) as heavy_pool,
                ThreadPoolExecutor(
                    max_workers=ceiling,
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
                        rec.record_upload_done()
                    elif outcome == "failed":
                        failed += 1
                        rec.record_upload_failed()
                    elif outcome == "skipped":
                        rec.record_upload_skipped()
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
                        batch_id=batch_id,
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
                self._tracking_store.mark_stage_done(
                    txn, batch_id, StageStatus.S5_DONE, cm_object_id=cm_object_id
                )
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

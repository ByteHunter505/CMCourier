"""Multi-batch producer-consumer orchestrator (028 — POST-MVP §7).

Wraps a :class:`StagedPipeline` to run multiple chunks of the
trigger source with up to ``batches_in_flight`` chunks in
flight at once. For ``batches_in_flight == 1`` the orchestrator
delegates straight to ``pipeline.run(...)`` (zero overhead). For
``N == 2`` it spawns one prep thread (S0..S4) and one upload
thread (S5) communicating via a small bounded queue.

Per-chunk semantics:
    * Each chunk gets its **own** ``batch_id`` from the
      tracking store.
    * Each chunk gets its **own** :class:`MetricsRecorder`
      so per-chunk slow-ops files + per-chunk batch_summary
      events stay isolated. The recorders' slow-op handlers
      filter by ``record.batch_id`` (see 028 phase 2).
    * The S5 worker pool (semaphore + ThreadPoolExecutor) is
      **shared** across chunks — total upload concurrency
      stays at ``cmis.workers``.

Failure isolation: an exception in one chunk's prep or upload
is logged at ERROR and the chunk is added to
``failed_chunks``. Remaining chunks continue. The aggregate
report's exit code reflects whether any chunk reported s5
failures or crashed outright.
"""

from __future__ import annotations

__all__ = ["MultiBatchOrchestrator", "MultiBatchRunReport"]

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from cmcourier.config.schema import PipelineConfig
from cmcourier.domain.models import TriggerRecord
from cmcourier.observability.metrics import MetricsRecorder
from cmcourier.orchestrators.chunked import chunked
from cmcourier.orchestrators.staged import RunReport, StagedPipeline, _StageItem

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MultiBatchRunReport:
    """Aggregated outcome of a multi-batch run."""

    chunks: list[RunReport]
    failed_chunks: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total_triggers(self) -> int:
        return sum(r.total_triggers for r in self.chunks)

    @property
    def total_docs(self) -> int:
        return sum(r.total_docs for r in self.chunks)

    @property
    def s5_done(self) -> int:
        return sum(r.s5_done for r in self.chunks)

    @property
    def s5_failed(self) -> int:
        return sum(r.s5_failed for r in self.chunks)

    @property
    def elapsed_seconds(self) -> float:
        return sum(r.elapsed_seconds for r in self.chunks)


# ---------------------------------------------------------------------------
# Internal handoff shape
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _PreparedChunk:
    """Hand-off from prep thread to upload thread."""

    batch_id: str
    chunk_idx: int
    triggers: list[TriggerRecord]
    items: list[_StageItem]
    skipped: int
    s1_done: int
    s2_failed: int
    s3_failed: int
    s4_failed: int
    recorder: MetricsRecorder
    started_at: float
    prep_failure: BaseException | None = None


# Sentinel placed on the upload queue by the prep thread to signal "no more
# chunks". The upload thread drains and exits.
_PREP_DONE = object()


class MultiBatchOrchestrator:
    """Run a ``StagedPipeline`` with producer-consumer overlap."""

    def __init__(
        self,
        *,
        pipeline: StagedPipeline,
        config: PipelineConfig,
        log_dir: Path,
    ) -> None:
        self._pipeline = pipeline
        self._config = config
        self._log_dir = log_dir

    # ----- public API -------------------------------------------------

    def run(
        self,
        *,
        source_descriptor: str,
        batch_size: int,
        batches_in_flight: int,
        from_stage: int = 1,
        resume_batch_id: str | None = None,
    ) -> MultiBatchRunReport:
        """Acquire triggers, chunk, then run them per ``batches_in_flight``."""
        if resume_batch_id is not None or batches_in_flight == 1 or from_stage > 1:
            # Resume + single-in-flight + non-default from_stage all force the
            # legacy single-batch path: it preserves byte-identical semantics
            # of pre-028 ``pipeline.run`` invocations.
            return self._run_single(
                source_descriptor=source_descriptor,
                batch_size=batch_size,
                resume_batch_id=resume_batch_id,
                from_stage=from_stage,
            )
        if batches_in_flight != 2:
            raise ValueError(
                f"batches_in_flight={batches_in_flight} not supported "
                "(spec 028 ships only 1 and 2; 3..5 deferred to a future change)"
            )
        return self._run_overlapped(
            source_descriptor=source_descriptor,
            batch_size=batch_size,
        )

    # ----- N=1 path ---------------------------------------------------

    def _run_single(
        self,
        *,
        source_descriptor: str,
        batch_size: int,
        resume_batch_id: str | None,
        from_stage: int,
    ) -> MultiBatchRunReport:
        report = self._pipeline.run(
            source_descriptor=source_descriptor,
            batch_size=batch_size,
            batch_id=resume_batch_id,
            from_stage=from_stage,
        )
        return MultiBatchRunReport(chunks=[report])

    # ----- N=2 path ---------------------------------------------------

    def _run_overlapped(
        self,
        *,
        source_descriptor: str,
        batch_size: int,
    ) -> MultiBatchRunReport:
        triggers = list(self._pipeline._trigger_strategy.acquire(source_descriptor))  # noqa: SLF001
        chunks_iter = chunked(triggers, batch_size)
        chunk_list = list(chunks_iter)
        if not chunk_list:
            return MultiBatchRunReport(chunks=[])

        upload_queue: queue.Queue[object] = queue.Queue(maxsize=2)
        results: list[RunReport] = []
        failed: list[tuple[str, str]] = []
        results_lock = threading.Lock()

        def _prep_loop() -> None:
            for idx, chunk in enumerate(chunk_list):
                try:
                    batch_id = self._pipeline._resolve_batch_id(  # noqa: SLF001
                        None, from_stage=1, batch_size=len(chunk)
                    )
                    recorder = self._build_chunk_recorder()
                    recorder.start_batch(pipeline=self._pipeline.pipeline_name, batch_id=batch_id)
                    started = time.monotonic()
                    items, skipped, s1d, s2f, s3f, s4f = self._pipeline.prep_chunk(
                        triggers=chunk,
                        batch_id=batch_id,
                        recorder=recorder,
                    )
                    upload_queue.put(
                        _PreparedChunk(
                            batch_id=batch_id,
                            chunk_idx=idx,
                            triggers=chunk,
                            items=items,
                            skipped=skipped,
                            s1_done=s1d,
                            s2_failed=s2f,
                            s3_failed=s3f,
                            s4_failed=s4f,
                            recorder=recorder,
                            started_at=started,
                        )
                    )
                except BaseException as exc:  # noqa: BLE001 — handed off through queue
                    _log.exception(
                        "multi-batch: prep failed",
                        extra={"chunk_idx": idx, "reason": type(exc).__name__},
                    )
                    with results_lock:
                        failed.append((f"chunk-{idx}", type(exc).__name__))
            upload_queue.put(_PREP_DONE)

        def _upload_loop() -> None:
            controller = self._pipeline.auto_tune_controller
            try:
                if controller is not None:
                    controller.start()
                while True:
                    item = upload_queue.get()
                    if item is _PREP_DONE:
                        return
                    assert isinstance(item, _PreparedChunk)
                    try:
                        s5_done, s5_failed = self._pipeline.upload_chunk(
                            items=item.items,
                            batch_id=item.batch_id,
                            recorder=item.recorder,
                        )
                        self._pipeline._tracking_store.flush()  # noqa: SLF001
                        self._pipeline._tracking_store.complete_batch(item.batch_id)  # noqa: SLF001
                        elapsed = time.monotonic() - item.started_at
                        total_docs = item.s1_done + item.skipped
                        item.recorder.close_batch(
                            pipeline=self._pipeline.pipeline_name,
                            batch_id=item.batch_id,
                            total_docs=total_docs,
                            elapsed_s=elapsed,
                        )
                        with results_lock:
                            results.append(
                                RunReport(
                                    batch_id=item.batch_id,
                                    total_triggers=len(item.triggers),
                                    total_docs=total_docs,
                                    s1_done=item.s1_done,
                                    s1_skipped_cross_batch=item.skipped,
                                    s2_done=len(item.items) + item.s2_failed,
                                    s2_failed=item.s2_failed,
                                    s3_done=len(item.items) + item.s3_failed,
                                    s3_failed=item.s3_failed,
                                    s4_done=len(item.items),
                                    s4_failed=item.s4_failed,
                                    s5_done=s5_done,
                                    s5_failed=s5_failed,
                                    elapsed_seconds=elapsed,
                                )
                            )
                    except BaseException as exc:  # noqa: BLE001
                        _log.exception(
                            "multi-batch: upload failed",
                            extra={
                                "batch_id": item.batch_id,
                                "chunk_idx": item.chunk_idx,
                                "reason": type(exc).__name__,
                            },
                        )
                        with results_lock:
                            failed.append((item.batch_id, type(exc).__name__))
            finally:
                if controller is not None:
                    controller.stop(timeout=2.0)

        sampler = self._pipeline.sampler
        if sampler is not None:
            sampler.start()
        try:
            prep_thread = threading.Thread(
                target=_prep_loop, name="cmcourier-multi-prep", daemon=False
            )
            upload_thread = threading.Thread(
                target=_upload_loop, name="cmcourier-multi-upload", daemon=False
            )
            prep_thread.start()
            upload_thread.start()
            prep_thread.join()
            upload_thread.join()
        finally:
            if sampler is not None:
                sampler.stop()

        # Sort results by chunk start time so the output stream is stable.
        results.sort(key=lambda r: r.batch_id)
        return MultiBatchRunReport(chunks=results, failed_chunks=failed)

    # ----- internals --------------------------------------------------

    def _build_chunk_recorder(self) -> MetricsRecorder:
        cfg = self._config.observability
        return MetricsRecorder(
            log_dir=self._log_dir,
            slow_op_threshold_ms=float(cfg.slow_op_threshold_ms),
            slow_op_top_n=cfg.slow_op_top_n,
            enabled=cfg.enabled,
            pipeline_metrics_enabled=cfg.pipeline_metrics,
        )

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

__all__ = ["ChunkState", "MultiBatchOrchestrator", "MultiBatchRunReport"]

import logging
import queue
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from cmcourier.config.schema import PipelineConfig
from cmcourier.domain.models import TriggerRecord
from cmcourier.observability.metrics import MetricsRecorder
from cmcourier.orchestrators.chunked import chunked
from cmcourier.orchestrators.staged import RunReport, StagedPipeline, _StageItem

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChunkState:
    """One row in the orchestrator's chunk-state machine (030, TUI binding).

    Statuses: ``QUEUED``, ``PREP``, ``UPLOAD``, ``DONE``, ``FAILED``.

    041 adds the per-stage breakdown that drives the CHUNKS tab table and
    the UPLOAD tab's chunk-scoped MB/timer/ETA display. The ``*_monotonic``
    fields are populated when the chunk transitions into the stage; the
    ``*_elapsed_s`` fields are frozen when it leaves. While the chunk is
    live in a stage, the consumer derives elapsed = ``now - started``.
    """

    chunk_idx: int
    batch_id: str
    status: str
    s5_done: int = 0
    s5_failed: int = 0
    # 041 — per-chunk plan + per-stage stats
    doc_count: int = 0
    total_bytes: int = 0
    prep_done: int = 0
    prep_skipped: int = 0
    prep_failed: int = 0
    upload_skipped: int = 0
    prep_started_monotonic: float | None = None
    prep_elapsed_s: float = 0.0
    upload_started_monotonic: float | None = None
    upload_elapsed_s: float = 0.0


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


def _items_total_bytes(items: Sequence[object]) -> int:
    """Sum ``staged_file.size_bytes`` defensively across a chunk's items.

    Production items always carry a ``staged_file`` after S4. Unit-test
    stubs (``SimpleNamespace`` etc.) sometimes don't — fall back to 0
    for any item that doesn't expose the chain.
    """
    total = 0
    for it in items:
        staged = getattr(it, "staged_file", None)
        if staged is None:
            continue
        size = getattr(staged, "size_bytes", None)
        if isinstance(size, int):
            total += size
    return total


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
        # 030: chunk-state machine for the TUI's CHUNKS tab. Indexed by
        # chunk_idx so prep / upload threads can update without lookups.
        # The active recorder feeds the live PREP/UPLOAD tab bindings.
        self._chunks_state: dict[int, ChunkState] = {}
        self._active_recorder: MetricsRecorder | None = None
        self._state_lock = threading.Lock()

    # ----- TUI binding hooks (030) -----------------------------------

    def chunks_snapshot(self) -> list[ChunkState]:
        """Read-only snapshot of every chunk's status for the TUI."""
        with self._state_lock:
            return [self._chunks_state[k] for k in sorted(self._chunks_state)]

    def active_recorder(self) -> MetricsRecorder | None:
        """The most recently started chunk's recorder, or ``None``."""
        with self._state_lock:
            return self._active_recorder

    def _update_chunk_state(
        self,
        *,
        chunk_idx: int,
        batch_id: str,
        status: str,
        s5_done: int = 0,
        s5_failed: int = 0,
        doc_count: int | None = None,
        total_bytes: int | None = None,
        prep_done: int | None = None,
        prep_skipped: int | None = None,
        prep_failed: int | None = None,
        upload_skipped: int | None = None,
        prep_started_monotonic: float | None = None,
        prep_elapsed_s: float | None = None,
        upload_started_monotonic: float | None = None,
        upload_elapsed_s: float | None = None,
    ) -> None:
        """Atomic transition for one chunk. ``None`` means "keep previous value"
        for that field — so callers only have to supply what actually changed.
        """
        with self._state_lock:
            prev = self._chunks_state.get(chunk_idx)
            self._chunks_state[chunk_idx] = ChunkState(
                chunk_idx=chunk_idx,
                batch_id=batch_id,
                status=status,
                s5_done=s5_done,
                s5_failed=s5_failed,
                doc_count=(doc_count if doc_count is not None else (prev.doc_count if prev else 0)),
                total_bytes=(
                    total_bytes if total_bytes is not None else (prev.total_bytes if prev else 0)
                ),
                prep_done=(prep_done if prep_done is not None else (prev.prep_done if prev else 0)),
                prep_skipped=(
                    prep_skipped if prep_skipped is not None else (prev.prep_skipped if prev else 0)
                ),
                prep_failed=(
                    prep_failed if prep_failed is not None else (prev.prep_failed if prev else 0)
                ),
                upload_skipped=(
                    upload_skipped
                    if upload_skipped is not None
                    else (prev.upload_skipped if prev else 0)
                ),
                prep_started_monotonic=(
                    prep_started_monotonic
                    if prep_started_monotonic is not None
                    else (prev.prep_started_monotonic if prev else None)
                ),
                prep_elapsed_s=(
                    prep_elapsed_s
                    if prep_elapsed_s is not None
                    else (prev.prep_elapsed_s if prev else 0.0)
                ),
                upload_started_monotonic=(
                    upload_started_monotonic
                    if upload_started_monotonic is not None
                    else (prev.upload_started_monotonic if prev else None)
                ),
                upload_elapsed_s=(
                    upload_elapsed_s
                    if upload_elapsed_s is not None
                    else (prev.upload_elapsed_s if prev else 0.0)
                ),
            )

    def _set_active_recorder(self, recorder: MetricsRecorder | None) -> None:
        with self._state_lock:
            self._active_recorder = recorder

    # ----- public API -------------------------------------------------

    def run(
        self,
        *,
        source_descriptor: str,
        batch_size: int,
        batches_in_flight: int,
        from_stage: int = 1,
        resume_batch_id: str | None = None,
        total: int | None = None,
    ) -> MultiBatchRunReport:
        """Acquire triggers, chunk, then run them per ``batches_in_flight``.

        ``total`` (033) caps the trigger count after acquire. Applied
        uniformly to both N=1 and N=2 paths.
        """
        if resume_batch_id is not None or batches_in_flight == 1 or from_stage > 1:
            # Resume + single-in-flight + non-default from_stage all force the
            # legacy single-batch path: it preserves byte-identical semantics
            # of pre-028 ``pipeline.run`` invocations.
            return self._run_single(
                source_descriptor=source_descriptor,
                batch_size=batch_size,
                resume_batch_id=resume_batch_id,
                from_stage=from_stage,
                total=total,
            )
        if batches_in_flight != 2:
            raise ValueError(
                f"batches_in_flight={batches_in_flight} not supported "
                "(spec 028 ships only 1 and 2; 3..5 deferred to a future change)"
            )
        return self._run_overlapped(
            source_descriptor=source_descriptor,
            batch_size=batch_size,
            total=total,
        )

    # ----- N=1 path ---------------------------------------------------

    def _run_single(
        self,
        *,
        source_descriptor: str,
        batch_size: int,
        resume_batch_id: str | None,
        from_stage: int,
        total: int | None = None,
    ) -> MultiBatchRunReport:
        report = self._pipeline.run(
            source_descriptor=source_descriptor,
            batch_size=batch_size,
            batch_id=resume_batch_id,
            from_stage=from_stage,
            total=total,
        )
        return MultiBatchRunReport(chunks=[report])

    # ----- N=2 path ---------------------------------------------------

    def _run_overlapped(
        self,
        *,
        source_descriptor: str,
        batch_size: int,
        total: int | None = None,
    ) -> MultiBatchRunReport:
        triggers = list(self._pipeline._trigger_strategy.acquire(source_descriptor))  # noqa: SLF001
        if total is not None:
            triggers = triggers[: max(0, total)]
        chunks_iter = chunked(triggers, batch_size)
        chunk_list = list(chunks_iter)
        if not chunk_list:
            return MultiBatchRunReport(chunks=[])

        upload_queue: queue.Queue[object] = queue.Queue(maxsize=2)
        results: list[RunReport] = []
        failed: list[tuple[str, str]] = []
        results_lock = threading.Lock()

        # 030: seed the chunk-state machine so the TUI's CHUNKS tab can
        # render the full plan immediately (all chunks start as QUEUED).
        for idx in range(len(chunk_list)):
            self._update_chunk_state(chunk_idx=idx, batch_id="", status="QUEUED")

        def _prep_loop() -> None:
            for idx, chunk in enumerate(chunk_list):
                try:
                    batch_id = self._pipeline._resolve_batch_id(  # noqa: SLF001
                        None, from_stage=1, batch_size=len(chunk)
                    )
                    recorder = self._build_chunk_recorder()
                    recorder.start_batch(pipeline=self._pipeline.pipeline_name, batch_id=batch_id)
                    started = time.monotonic()
                    self._update_chunk_state(
                        chunk_idx=idx,
                        batch_id=batch_id,
                        status="PREP",
                        prep_started_monotonic=started,
                    )
                    self._set_active_recorder(recorder)
                    items, skipped, s1d, s2f, s3f, s4f = self._pipeline.prep_chunk(
                        triggers=chunk,
                        batch_id=batch_id,
                        recorder=recorder,
                    )
                    prep_elapsed = time.monotonic() - started
                    total_bytes = _items_total_bytes(items)
                    # Freeze the PREP-side breakdown the moment prep wraps; the
                    # chunk will sit in the upload queue with status=PREP until
                    # picked up, but its prep numbers are already final.
                    self._update_chunk_state(
                        chunk_idx=idx,
                        batch_id=batch_id,
                        status="PREP",
                        doc_count=s1d + skipped,
                        total_bytes=total_bytes,
                        prep_done=len(items),
                        prep_skipped=skipped,
                        prep_failed=s2f + s3f + s4f,
                        prep_elapsed_s=prep_elapsed,
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
                    self._update_chunk_state(
                        chunk_idx=idx,
                        batch_id=self._chunks_state.get(
                            idx, ChunkState(chunk_idx=idx, batch_id="", status="FAILED")
                        ).batch_id,
                        status="FAILED",
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
                    upload_started = time.monotonic()
                    self._update_chunk_state(
                        chunk_idx=item.chunk_idx,
                        batch_id=item.batch_id,
                        status="UPLOAD",
                        upload_started_monotonic=upload_started,
                    )
                    self._set_active_recorder(item.recorder)
                    try:
                        s5_done, s5_failed = self._pipeline.upload_chunk(
                            items=item.items,
                            batch_id=item.batch_id,
                            recorder=item.recorder,
                        )
                        self._pipeline._tracking_store.flush()  # noqa: SLF001
                        self._pipeline._tracking_store.complete_batch(item.batch_id)  # noqa: SLF001
                        elapsed = time.monotonic() - item.started_at
                        upload_elapsed = time.monotonic() - upload_started
                        total_docs = item.s1_done + item.skipped
                        item.recorder.close_batch(
                            pipeline=self._pipeline.pipeline_name,
                            batch_id=item.batch_id,
                            total_docs=total_docs,
                            elapsed_s=elapsed,
                        )
                        self._update_chunk_state(
                            chunk_idx=item.chunk_idx,
                            batch_id=item.batch_id,
                            status="DONE",
                            s5_done=s5_done,
                            s5_failed=s5_failed,
                            upload_skipped=item.recorder.upload_skipped_count(),
                            upload_elapsed_s=upload_elapsed,
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
                        self._update_chunk_state(
                            chunk_idx=item.chunk_idx,
                            batch_id=item.batch_id,
                            status="FAILED",
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

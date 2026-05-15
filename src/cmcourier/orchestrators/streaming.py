"""Streaming orchestrator (063 — POST-MVP §13).

Coexists with :class:`MultiBatchOrchestrator`. Selected by
``processing.mode == "streaming"`` in the operator's YAML.

Shape:

* **One** logical batch_id for the whole run.
* **One** :class:`MetricsRecorder` for the run — AIMD reads
  ``current_stage_p95_with_count("S5")`` from this single recorder.
* A bounded :class:`queue.Queue` (the *bucket*) sits between PREP
  (S1-S4 producers) and UPLOAD (S5 consumers). Producers push
  prepared items into the bucket; consumers pop them out.
  ``bucket.put`` blocks when the bucket is full → automatic
  back-pressure on PREP. ``bucket.get`` blocks when the bucket is
  empty → consumers idle on a futex, not a spinloop.
* Producers (``processing.prep_workers``) pull triggers from a
  shared, lock-guarded iterator over the trigger source. When the
  iterator is exhausted, the observing producer pushes ``N`` poison
  pills (one per consumer) into the bucket and exits.
* Consumers (sized to ``_pool_ceiling()``, like the batched path's
  S5 pool — spec 057) call the existing ``streaming_upload_one``.
  A consumer that pops a poison pill exits.

Result: memory peak collapses to ``bucket_size`` (independent of
total trigger count); S5 never waits for a chunk's PREP to finish;
PREP never blocks on an in-flight chunk slot.

Resume is rejected in streaming mode (``from_stage > 1`` or
non-None ``resume_batch_id`` → ``ValueError``). Cross-batch
idempotency (062, ``S1_SKIPPED`` rows) gives traceability for docs
already uploaded in prior runs.
"""

from __future__ import annotations

__all__ = ["StreamingOrchestrator", "_TriggerIter"]

import itertools
import logging
import queue
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from cmcourier.config.schema import PipelineConfig
from cmcourier.domain.models import Trigger
from cmcourier.observability.metrics import MetricsRecorder
from cmcourier.orchestrators.multi_batch import ChunkState, MultiBatchRunReport
from cmcourier.orchestrators.staged import RunReport, StagedPipeline, _StageItem

_log = logging.getLogger(__name__)

_POISON: object = object()


class _TriggerIter:
    """Thread-safe wrapper over a single trigger iterator.

    Producers all share one instance. ``next()`` is guarded by a
    ``threading.Lock`` so a trigger is delivered to exactly one
    producer. ``StopIteration`` is raised on exhaustion (standard
    iterator contract — the producer that observes it is responsible
    for fan-out shutdown).
    """

    __slots__ = ("_inner", "_lock", "_count")

    def __init__(self, inner: Iterator[Trigger]) -> None:
        self._inner = inner
        self._lock = threading.Lock()
        self._count = 0

    def __iter__(self) -> _TriggerIter:
        return self

    def __next__(self) -> Trigger:
        with self._lock:
            value = next(self._inner)
            self._count += 1
            return value

    @property
    def count(self) -> int:
        with self._lock:
            return self._count


@dataclass(slots=True)
class _StreamingTally:
    """Mutable per-run counters owned by consumers + producers."""

    s5_done: int = 0
    s5_failed: int = 0
    s5_skipped: int = 0
    s1_filtered: int = 0
    prep_failed: int = 0
    cross_batch_skipped: int = 0


class StreamingOrchestrator:
    """Continuous producer-consumer pipeline (063).

    Exposes the same ``.run(...)`` shape as
    :class:`MultiBatchOrchestrator` for CLI parity. Returns a
    :class:`MultiBatchRunReport` carrying a single synthetic
    :class:`RunReport` summarising the whole run.
    """

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
        self._bucket_size = max(1, int(config.processing.streaming.bucket_size))
        self._prep_workers = max(1, int(config.processing.prep_workers))
        self._consumer_count = max(1, int(pipeline._pool_ceiling()))  # noqa: SLF001
        self._state_lock = threading.Lock()
        self._chunk_state: ChunkState | None = None
        self._recorder: MetricsRecorder | None = None
        self._bucket: queue.Queue[_StageItem | object] | None = None
        self._peak_qsize = 0

    # ------------------------------------------- TUI binding hooks (063)

    def chunks_snapshot(self) -> list[ChunkState]:
        """Single synthetic-chunk view of the run.

        The CHUNKS tab degrades gracefully in streaming mode — spec
        064 replaces it with a real BUCKET tab.
        """
        with self._state_lock:
            return [self._chunk_state] if self._chunk_state is not None else []

    def active_recorder(self) -> MetricsRecorder | None:
        with self._state_lock:
            return self._recorder

    def upload_recorder(self) -> MetricsRecorder | None:
        with self._state_lock:
            return self._recorder

    @property
    def bucket_size(self) -> int:
        return self._bucket_size

    @property
    def peak_qsize(self) -> int:
        return self._peak_qsize

    # ----------------------------------------------------------- public API

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
        """Drive the streaming pipeline end-to-end.

        ``batch_size`` and ``batches_in_flight`` are accepted for CLI
        parity but **ignored** — streaming uses the configured
        ``bucket_size`` as its single memory-control knob. ``from_stage
        > 1`` or non-None ``resume_batch_id`` raises ``ValueError``;
        resume in streaming mode = re-run + 062's ``S1_SKIPPED`` rows.
        """
        if from_stage > 1:
            raise ValueError(
                "streaming mode does not support --from-stage > 1; "
                "re-run with --from-stage 1 (cross-batch idempotency "
                "produces S1_SKIPPED rows for already-uploaded docs)"
            )
        if resume_batch_id is not None:
            raise ValueError(
                "streaming mode does not support --batch-id (resume); "
                "each run uses a fresh batch_id"
            )

        triggers: Iterator[Trigger] = self._pipeline._trigger_strategy.acquire(  # noqa: SLF001
            source_descriptor
        )
        if total is not None:
            triggers = itertools.islice(triggers, max(0, total))
        trigger_iter = _TriggerIter(triggers)

        batch_id = self._pipeline._tracking_store.start_batch(total_records=0)  # noqa: SLF001
        recorder = self._build_run_recorder()
        recorder.start_batch(pipeline=self._pipeline.pipeline_name, batch_id=batch_id)
        with self._state_lock:
            self._recorder = recorder
            self._chunk_state = ChunkState(
                chunk_idx=0,
                batch_id=batch_id,
                status="PREP",
            )

        bucket: queue.Queue[_StageItem | object] = queue.Queue(maxsize=self._bucket_size)
        self._bucket = bucket
        self._peak_qsize = 0
        tally = _StreamingTally()
        tally_lock = threading.Lock()

        start = time.monotonic()
        sampler = self._pipeline.sampler
        controller = self._pipeline.auto_tune_controller
        if sampler is not None:
            sampler.start()
        if controller is not None:

            def _p95_provider() -> tuple[float, int]:
                return recorder.current_stage_p95_with_count("S5")

            controller.set_p95_provider(_p95_provider)
            controller.start()
        try:
            # 038: pre-open the S5 connection pool so the first batch of
            # uploads does not pay TCP+TLS+session handshake on critical path.
            self._pipeline.warm_upload_pool(self._consumer_count)

            producers = [
                threading.Thread(
                    target=self._prep_loop,
                    args=(trigger_iter, bucket, batch_id, recorder, tally, tally_lock),
                    name=f"cmcourier-stream-prep-{i}",
                    daemon=False,
                )
                for i in range(self._prep_workers)
            ]
            consumers = [
                threading.Thread(
                    target=self._upload_loop,
                    args=(bucket, batch_id, recorder, tally, tally_lock),
                    name=f"cmcourier-stream-upload-{i}",
                    daemon=False,
                )
                for i in range(self._consumer_count)
            ]
            for p in producers:
                p.start()
            for c in consumers:
                c.start()

            for p in producers:
                p.join()
            # Producers are done; ensure consumers get N poison pills.
            for _ in range(self._consumer_count):
                bucket.put(_POISON)
            for c in consumers:
                c.join()
        finally:
            if controller is not None:
                controller.stop(timeout=2.0)
            if sampler is not None:
                sampler.stop()

        elapsed = time.monotonic() - start
        self._pipeline._tracking_store.flush()  # noqa: SLF001
        self._pipeline._tracking_store.complete_batch(batch_id)  # noqa: SLF001

        with tally_lock:
            snapshot = _StreamingTally(
                s5_done=tally.s5_done,
                s5_failed=tally.s5_failed,
                s5_skipped=tally.s5_skipped,
                s1_filtered=tally.s1_filtered,
                prep_failed=tally.prep_failed,
                cross_batch_skipped=tally.cross_batch_skipped,
            )

        total_triggers = trigger_iter.count
        total_docs = snapshot.s5_done + snapshot.s5_failed + snapshot.s5_skipped
        recorder.close_batch(
            pipeline=self._pipeline.pipeline_name,
            batch_id=batch_id,
            total_docs=total_docs,
            elapsed_s=elapsed,
        )

        with self._state_lock:
            self._chunk_state = ChunkState(
                chunk_idx=0,
                batch_id=batch_id,
                status="DONE",
                s5_done=snapshot.s5_done,
                s5_failed=snapshot.s5_failed,
                doc_count=total_docs,
                prep_done=snapshot.s5_done + snapshot.s5_failed + snapshot.s5_skipped,
                prep_skipped=snapshot.cross_batch_skipped,
                prep_filtered=snapshot.s1_filtered,
                upload_skipped=snapshot.s5_skipped,
                upload_elapsed_s=elapsed,
            )

        report = RunReport(
            batch_id=batch_id,
            total_triggers=total_triggers,
            total_docs=total_docs,
            s1_done=total_docs,
            s1_skipped_cross_batch=snapshot.cross_batch_skipped,
            s1_filtered=snapshot.s1_filtered,
            s2_done=total_docs,
            s2_failed=0,
            s3_done=total_docs,
            s3_failed=0,
            s4_done=total_docs,
            s4_failed=0,
            s5_done=snapshot.s5_done,
            s5_failed=snapshot.s5_failed,
            elapsed_seconds=elapsed,
        )
        return MultiBatchRunReport(chunks=[report])

    # ------------------------------------------------------ producer / consumer

    def _prep_loop(
        self,
        trigger_iter: _TriggerIter,
        bucket: queue.Queue[_StageItem | object],
        batch_id: str,
        recorder: MetricsRecorder,
        tally: _StreamingTally,
        tally_lock: threading.Lock,
    ) -> None:
        while True:
            try:
                trigger = next(trigger_iter)
            except StopIteration:
                return
            try:
                survivor, skipped, filtered = self._pipeline.streaming_prep_one(
                    trigger, batch_id, recorder
                )
            except BaseException as exc:  # noqa: BLE001 — log + count, run continues
                _log.exception(
                    "streaming: prep failed",
                    extra={"batch_id": batch_id, "reason": type(exc).__name__},
                )
                with tally_lock:
                    tally.prep_failed += 1
                continue
            with tally_lock:
                tally.cross_batch_skipped += skipped
                tally.s1_filtered += filtered
            if survivor is None:
                # filtered / cross-batch-skipped / failed at S2-S4. Already
                # persisted by the inner helpers; counters above capture
                # the outcome for the synthetic RunReport.
                continue
            bucket.put(survivor)
            current = bucket.qsize()
            if current > self._peak_qsize:
                self._peak_qsize = current

    def _upload_loop(
        self,
        bucket: queue.Queue[_StageItem | object],
        batch_id: str,
        recorder: MetricsRecorder,
        tally: _StreamingTally,
        tally_lock: threading.Lock,
    ) -> None:
        while True:
            item = bucket.get()
            try:
                if item is _POISON:
                    return
                # ``bucket`` carries _StageItem instances except for the
                # poison sentinel (handled above).
                stage_item: _StageItem = item  # type: ignore[assignment]
                try:
                    outcome = self._pipeline.streaming_upload_one(stage_item, batch_id, recorder)
                except BaseException as exc:  # noqa: BLE001
                    _log.exception(
                        "streaming: upload crashed",
                        extra={"batch_id": batch_id, "reason": type(exc).__name__},
                    )
                    with tally_lock:
                        tally.s5_failed += 1
                    continue
                with tally_lock:
                    if outcome == "done":
                        tally.s5_done += 1
                        recorder.record_upload_done()
                    elif outcome == "failed":
                        tally.s5_failed += 1
                        recorder.record_upload_failed()
                    elif outcome == "skipped":
                        tally.s5_skipped += 1
                        recorder.record_upload_skipped()
            finally:
                bucket.task_done()

    # ------------------------------------------------------ internals

    def _build_run_recorder(self) -> MetricsRecorder:
        cfg = self._config.observability
        return MetricsRecorder(
            log_dir=self._log_dir,
            slow_op_threshold_ms=float(cfg.slow_op_threshold_ms),
            slow_op_top_n=cfg.slow_op_top_n,
            enabled=cfg.enabled,
            pipeline_metrics_enabled=cfg.pipeline_metrics,
        )

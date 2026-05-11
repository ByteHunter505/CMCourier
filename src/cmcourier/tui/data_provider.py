"""Read-only snapshot adapter for the TUI (025 phase 3).

The TUI runs in its own thread; the pipeline runs in the main
thread. They never share mutable state directly. Instead, every
~250 ms the TUI calls :meth:`TUIDataProvider.snapshot` which builds
an immutable :class:`TUISnapshot` from the live state of:

* :class:`MetricsRecorder` — stage timings + bandwidth sampler +
  slow-op aggregator.
* :class:`WorkerPoolStats` — pool capacity/busy/queue.
* :class:`AutoTuneController` (optional) — last AIMD decision +
  countdown.
* :class:`CmisConfigModel` + :class:`CmisUploader` — endpoint,
  bandwidth ceiling, live request timeout.

The provider intentionally hides every mutable handle so the TUI
cannot accidentally mutate orchestration state.
"""

from __future__ import annotations

__all__ = ["TUIDataProvider", "TUISnapshot"]

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cmcourier.adapters.upload.cmis_uploader import CmisUploader
from cmcourier.config.schema import CmisConfigModel
from cmcourier.observability.metrics import MetricsRecorder
from cmcourier.services.auto_tune import AutoTuneController
from cmcourier.services.lane_controller import LaneController, LaneSnapshot
from cmcourier.services.worker_pool_stats import ResizableSemaphore, WorkerPoolStats

# Stages displayed on the PREP tab. S5 lives on UPLOAD.
PREP_STAGES: tuple[str, ...] = ("S0", "S1", "S2", "S3", "S4")
UPLOAD_STAGE: str = "S5"


@dataclass(frozen=True, slots=True)
class TUISnapshot:
    """Immutable view of every field the TUI needs at one instant."""

    # ---------- header
    pipeline: str
    batch_id: str
    elapsed_s: float
    throughput_docs_per_s: float
    is_complete: bool

    # ---------- per-stage (S0..S5)
    stages: dict[str, dict[str, float | int]] = field(default_factory=dict)

    # ---------- workers
    pool_capacity: int = 0
    pool_in_use: int = 0
    pool_idle: int = 0
    queue_depth: int = 0

    # ---------- auto-tune
    auto_tune_enabled: bool = False
    auto_tune_target_p95_ms: float = 0.0
    auto_tune_observed_p95_ms: float = 0.0
    auto_tune_adjust_interval_s: int = 0
    auto_tune_next_in_s: float = 0.0
    auto_tune_timeout_s: float = 0.0
    auto_tune_timeout_min_s: int = 0
    auto_tune_timeout_max_s: int = 0
    auto_tune_last_action: str = "—"
    auto_tune_last_workers_after: int = 0
    auto_tune_seconds_since_last_decision: float | None = None

    # ---------- network (CMIS)
    cmis_endpoint: str = ""
    bandwidth_current_mbps: float = 0.0
    bandwidth_peak_mbps: float = 0.0
    bandwidth_ceiling_mbps: float = 0.0  # 0 == auto-scale
    bandwidth_series: tuple[tuple[int, float], ...] = ()

    # ---------- slow ops + recent uploads
    slow_ops_all: tuple[dict[str, object], ...] = ()

    # ---------- 030: chunks state (multi-batch view)
    chunks_state: tuple[dict[str, object], ...] = ()

    # ---------- 036: heavy/light lane state (None when single-lane mode)
    lane_snapshot: LaneSnapshot | None = None


class TUIDataProvider:
    """Snapshot factory the TUI polls every refresh tick.

    All accessor calls hit ``MetricsRecorder`` / ``WorkerPoolStats``
    snapshot APIs which are thread-safe by construction (Phase 1+2).
    """

    def __init__(
        self,
        *,
        pipeline_name: str,
        metrics_recorder: MetricsRecorder,
        pool_stats: WorkerPoolStats,
        concurrency_limit: ResizableSemaphore,
        cmis_config: CmisConfigModel,
        uploader: CmisUploader,
        auto_tune: AutoTuneController | None = None,
        recorder_provider: Callable[[], MetricsRecorder | None] | None = None,
        chunks_provider: Callable[[], list[Any]] | None = None,
        lane_controller: LaneController | None = None,
    ) -> None:
        self._pipeline_name = pipeline_name
        self._fallback_recorder = metrics_recorder
        # 030: when the multi-batch orchestrator drives the run, the
        # provider keeps pointing at the currently-active chunk's
        # recorder. For single-batch runs the fallback (== the
        # pipeline's own recorder) is used.
        self._recorder_provider: Callable[[], MetricsRecorder | None] | None = recorder_provider
        self._chunks_provider: Callable[[], list[Any]] | None = chunks_provider
        self._pool_stats = pool_stats
        self._concurrency_limit = concurrency_limit
        self._cmis_config = cmis_config
        self._uploader = uploader
        self._auto_tune = auto_tune
        self._lane_controller = lane_controller
        self._batch_id: str = ""
        self._batch_started_monotonic: float | None = None
        self._is_complete = False

    @property
    def _metrics(self) -> MetricsRecorder:
        """Live-bound active recorder; falls back to the constructed one."""
        if self._recorder_provider is not None:
            live = self._recorder_provider()
            if live is not None:
                return live
        return self._fallback_recorder

    # ------------------------------------------------------- lifecycle hooks

    def mark_batch_started(self, batch_id: str) -> None:
        self._batch_id = batch_id
        self._batch_started_monotonic = time.monotonic()
        self._is_complete = False

    def mark_batch_complete(self) -> None:
        self._is_complete = True

    # ------------------------------------------------------- snapshot

    def snapshot(self) -> TUISnapshot:
        stages = self._metrics.stages_snapshot()
        pool = self._pool_stats.snapshot()
        elapsed = (
            time.monotonic() - self._batch_started_monotonic
            if self._batch_started_monotonic is not None
            else 0.0
        )
        completed = pool.completed
        throughput = (completed / elapsed) if elapsed > 0 and completed > 0 else 0.0

        bw_cfg = self._cmis_config.auto_tune
        return TUISnapshot(
            pipeline=self._pipeline_name,
            batch_id=self._batch_id,
            elapsed_s=elapsed,
            throughput_docs_per_s=throughput,
            is_complete=self._is_complete,
            stages=stages,
            pool_capacity=self._concurrency_limit.capacity,
            pool_in_use=pool.busy,
            pool_idle=max(0, self._concurrency_limit.capacity - pool.busy),
            queue_depth=pool.queue_depth,
            auto_tune_enabled=bw_cfg.enabled,
            auto_tune_target_p95_ms=bw_cfg.target_p95_ms,
            auto_tune_observed_p95_ms=self._metrics.current_stage_p95(UPLOAD_STAGE),
            auto_tune_adjust_interval_s=bw_cfg.adjustment_interval_s,
            auto_tune_next_in_s=(self._auto_tune.seconds_to_next_tick if self._auto_tune else 0.0),
            auto_tune_timeout_s=self._uploader._timeout_s,
            auto_tune_timeout_min_s=bw_cfg.min_timeout_s,
            auto_tune_timeout_max_s=bw_cfg.max_timeout_s,
            auto_tune_last_action=self._last_action(),
            auto_tune_last_workers_after=self._last_workers_after(),
            auto_tune_seconds_since_last_decision=(
                self._auto_tune.seconds_since_last_decision if self._auto_tune else None
            ),
            cmis_endpoint=self._cmis_config.base_url,
            bandwidth_current_mbps=self._metrics.bandwidth.current_mbps(),
            bandwidth_peak_mbps=self._metrics.bandwidth.peak_mbps(),
            bandwidth_ceiling_mbps=self._cmis_config.max_bandwidth_mbps,
            bandwidth_series=tuple(self._metrics.bandwidth.series(60)),
            slow_ops_all=tuple(self._metrics.aggregator_snapshot()),
            chunks_state=self._chunks_state_snapshot(),
            lane_snapshot=(
                self._lane_controller.snapshot() if self._lane_controller is not None else None
            ),
        )

    def _chunks_state_snapshot(self) -> tuple[dict[str, object], ...]:
        """Render the orchestrator's chunk-state machine for the TUI."""
        if self._chunks_provider is None:
            return ()
        chunks = self._chunks_provider()
        out: list[dict[str, object]] = []
        for chunk in chunks:
            out.append(
                {
                    "chunk_idx": getattr(chunk, "chunk_idx", -1),
                    "batch_id": getattr(chunk, "batch_id", ""),
                    "status": getattr(chunk, "status", "?"),
                    "s5_done": getattr(chunk, "s5_done", 0),
                    "s5_failed": getattr(chunk, "s5_failed", 0),
                }
            )
        return tuple(out)

    # ------------------------------------------------------- helpers

    def _last_action(self) -> str:
        if self._auto_tune is None or self._auto_tune.last_decision is None:
            return "—"
        return self._auto_tune.last_decision.action

    def _last_workers_after(self) -> int:
        if self._auto_tune is None or self._auto_tune.last_decision is None:
            return 0
        return self._auto_tune.last_decision.workers

"""Pipeline metrics aggregators (tier 2) + network events (tier 3) + slow ops (tier 4).

Owned by the orchestrator. Per-stage timings flow through
:class:`StageTimer`; the recorder aggregates per batch and emits a
single summary line at close. Slow-op aggregation runs through a
custom :class:`logging.Handler` attached at batch start so adapter
code stays unaware (it emits to the well-known network logger and
the handler catches anything over the threshold).
"""

from __future__ import annotations

__all__ = [
    "BatchSummary",
    "MetricsRecorder",
    "NetworkEvent",
    "SlowOpAggregator",
    "StageTimer",
]

import datetime as _dt
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

_pipeline_log = logging.getLogger("cmcourier.metrics.pipeline")
_app_log = logging.getLogger("cmcourier")


# ---------------------------------------------------------------------------
# Network event payload (tier 3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NetworkEvent:
    """A single network-tier observation.

    Emitted by AS400 + CMIS adapters via the
    ``cmcourier.metrics.network`` logger as ``extra={...}``.
    """

    kind: str
    duration_ms: float
    sql_prefix: str = ""
    row_count: int | None = None
    size_bytes: int | None = None
    status: int | None = None
    url_prefix: str = ""
    txn_num: str = ""


# ---------------------------------------------------------------------------
# Per-stage timing aggregation (tier 2)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _StageBucket:
    """Thread-safe per-stage timing accumulator (025).

    The 020 single-threaded version had no lock — append-from-one-
    thread, snapshot-from-the-same-thread. 025 adds S5 worker
    concurrency: ``record`` is called from N worker threads while
    ``summary`` is called from the orchestrator + TUI threads.
    Lock keeps the underlying list consistent.
    """

    durations_ms: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, duration_ms: float) -> None:
        with self._lock:
            self.durations_ms.append(duration_ms)

    def summary(self) -> dict[str, float | int]:
        with self._lock:
            snapshot = list(self.durations_ms)
        if not snapshot:
            return {
                "count": 0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "sum_ms": 0.0,
            }
        sorted_ms = sorted(snapshot)
        return {
            "count": len(sorted_ms),
            "p50_ms": _percentile(sorted_ms, 0.50),
            "p95_ms": _percentile(sorted_ms, 0.95),
            "p99_ms": _percentile(sorted_ms, 0.99),
            "sum_ms": sum(sorted_ms),
        }


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile. ``q`` in ``[0, 1]``."""
    if not sorted_values:
        return 0.0
    if q <= 0:
        return sorted_values[0]
    if q >= 1:
        return sorted_values[-1]
    # rank = ceil(q * n), 1-indexed
    rank = max(1, int(q * len(sorted_values) + 0.999999))
    return sorted_values[min(rank, len(sorted_values)) - 1]


# ---------------------------------------------------------------------------
# Slow-ops aggregator (tier 4)
# ---------------------------------------------------------------------------


class SlowOpAggregator:
    """Collect candidate slow operations; emit top-N at batch close.

    Thread-safe (025): ``consider`` is called from S5 worker threads
    via the network logger handler.
    """

    def __init__(self, *, threshold_ms: float, top_n: int) -> None:
        self._threshold_ms = float(threshold_ms)
        self._top_n = int(top_n)
        self._candidates: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def consider(
        self,
        *,
        kind: str,
        duration_ms: float,
        txn_num: str = "",
        stage: str = "",
        size_bytes: int | None = None,
        url_prefix: str = "",
        worker: str = "",
    ) -> None:
        if duration_ms < self._threshold_ms:
            return
        entry: dict[str, Any] = {
            "kind": kind,
            "duration_ms": float(duration_ms),
        }
        if txn_num:
            entry["txn_num"] = txn_num
        if stage:
            entry["stage"] = stage
        if size_bytes is not None:
            entry["size_bytes"] = int(size_bytes)
        if url_prefix:
            entry["url_prefix"] = url_prefix
        if worker:
            entry["worker"] = worker
        with self._lock:
            self._candidates.append(entry)

    def top(self) -> list[dict[str, Any]]:
        with self._lock:
            snapshot = list(self._candidates)
        ranked = sorted(snapshot, key=lambda d: d["duration_ms"], reverse=True)[: self._top_n]
        return [{"rank": i + 1, **entry} for i, entry in enumerate(ranked)]


class _BandwidthSampler:
    """1-Hz rolling sampler for CMIS upload bandwidth (025 phase 3).

    Drives the TUI's bandwidth chart and the WORKERS/NETWORK panels.
    Buckets ``cmis_upload`` sizes by wall-clock second; keeps a 60-bucket
    rolling window so the chart shows the last minute. Thread-safe —
    fed from worker threads via the ``_BandwidthHandler``.
    """

    _WINDOW_SECONDS = 60

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # bucket_ts (int seconds since epoch) → bytes total this second
        self._buckets: dict[int, int] = {}
        # 041: cumulative bytes uploaded since this sampler was created. The
        # rolling buckets above evict after 60 s; this counter never does, so
        # the TUI can show a per-chunk "MB uploaded so far" total. The
        # ``MetricsRecorder`` lifecycle is per-chunk, so this is naturally
        # chunk-scoped.
        self._cumulative_bytes: int = 0

    def record_upload(self, size_bytes: int, completed_at: float) -> None:
        ts = int(completed_at)
        cutoff = ts - self._WINDOW_SECONDS
        with self._lock:
            self._buckets[ts] = self._buckets.get(ts, 0) + int(size_bytes)
            self._cumulative_bytes += int(size_bytes)
            stale = [k for k in self._buckets if k < cutoff]
            for k in stale:
                del self._buckets[k]

    def cumulative_bytes(self) -> int:
        """Total bytes uploaded since this sampler started (never decays)."""
        with self._lock:
            return self._cumulative_bytes

    def current_mbps(self) -> float:
        """MB/s in the most recent completed 1-second bucket."""
        now = int(time.time())
        with self._lock:
            # Look at the previous full bucket — the current one may still
            # be filling.
            return self._buckets.get(now - 1, 0) / 1_000_000.0

    def peak_mbps(self) -> float:
        with self._lock:
            if not self._buckets:
                return 0.0
            return max(self._buckets.values()) / 1_000_000.0

    def series(self, seconds: int = _WINDOW_SECONDS) -> list[tuple[int, float]]:
        """Return ``[(offset_s_negative, mbps)...]`` newest-last."""
        now = int(time.time())
        seconds = max(1, min(seconds, self._WINDOW_SECONDS))
        with self._lock:
            return [
                (
                    -(seconds - i - 1),
                    self._buckets.get(now - (seconds - i - 1), 0) / 1_000_000.0,
                )
                for i in range(seconds)
            ]


class _BandwidthHandler(logging.Handler):
    """Logging handler that feeds the bandwidth sampler from network events."""

    def __init__(self, sampler: _BandwidthSampler) -> None:
        super().__init__(level=logging.INFO)
        self._sampler = sampler

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "kind", "") != "cmis_upload":
            return
        size = getattr(record, "size_bytes", None)
        if size is None:
            return
        self._sampler.record_upload(int(size), record.created)


class _SlowOpHandler(logging.Handler):
    """Logging handler that feeds the per-batch slow-op aggregator.

    Attached to ``cmcourier``, ``cmcourier.metrics.network`` at batch
    start. Any record with a ``duration_ms`` attribute is a
    candidate; the aggregator's threshold filters cheap operations
    out before allocation.

    028: every handler is tagged with the ``batch_id`` of the
    recorder that owns it. Records whose ``record.batch_id`` does
    not match are dropped at the handler level so multiple
    concurrent recorders (one per chunk) don't cross-pollinate.
    A record without a ``batch_id`` extra is also dropped — slow
    ops outside any batch lifetime are not meaningful.
    """

    def __init__(self, aggregator: SlowOpAggregator, *, batch_id: str) -> None:
        super().__init__(level=logging.INFO)
        self._agg = aggregator
        self._batch_id = batch_id

    def emit(self, record: logging.LogRecord) -> None:
        dms = getattr(record, "duration_ms", None)
        if dms is None:
            return
        record_batch_id = getattr(record, "batch_id", None)
        if record_batch_id != self._batch_id:
            return
        self._agg.consider(
            kind=getattr(record, "kind", record.name),
            duration_ms=float(dms),
            txn_num=getattr(record, "txn_num", "") or "",
            stage=getattr(record, "stage", "") or "",
            size_bytes=getattr(record, "size_bytes", None),
            url_prefix=getattr(record, "url_prefix", "") or "",
            worker=getattr(record, "worker", "") or "",
        )


# ---------------------------------------------------------------------------
# Batch summary builder
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BatchSummary:
    pipeline: str
    batch_id: str
    total_docs: int
    elapsed_s: float
    throughput_docs_per_s: float
    stages: dict[str, dict[str, float | int]]

    def to_record(self) -> dict[str, Any]:
        return {
            "ts": _dt.datetime.now(tz=_dt.UTC).isoformat(),
            "kind": "batch_summary",
            "pipeline": self.pipeline,
            "batch_id": self.batch_id,
            "total_docs": self.total_docs,
            "elapsed_s": round(self.elapsed_s, 4),
            "throughput_docs_per_s": round(self.throughput_docs_per_s, 4),
            "stages": self.stages,
        }


# ---------------------------------------------------------------------------
# MetricsRecorder — orchestrator-facing facade
# ---------------------------------------------------------------------------


class MetricsRecorder:
    """Owned by the orchestrator. Per-batch lifecycle.

    The recorder is responsible for:
    * timing aggregation per stage (S0..S5)
    * slow-op collection (via a logging.Handler installed for the batch)
    * batch summary emission to ``cmcourier.metrics.pipeline``
    * slow-ops file emission at batch close
    """

    def __init__(
        self,
        *,
        log_dir: Path,
        slow_op_threshold_ms: float,
        slow_op_top_n: int,
        enabled: bool = True,
        pipeline_metrics_enabled: bool = True,
    ) -> None:
        self._log_dir = log_dir
        self._slow_op_threshold_ms = float(slow_op_threshold_ms)
        self._slow_op_top_n = int(slow_op_top_n)
        self._enabled = enabled
        self._pipeline_metrics_enabled = pipeline_metrics_enabled
        self._stage_buckets: dict[str, _StageBucket] = {}
        self._aggregator: SlowOpAggregator | None = None
        self._slow_op_handler: _SlowOpHandler | None = None
        self._monitored_loggers: list[logging.Logger] = []
        # 025 phase 3: bandwidth sampler is the data source for the TUI's
        # UPLOAD-tab chart. Active for the whole batch lifetime; handler
        # attaches/detaches alongside the slow-op handler.
        self._bandwidth = _BandwidthSampler()
        self._bandwidth_handler: _BandwidthHandler | None = None
        # 041: S5 already-uploaded counter so the CHUNKS tab can show
        # idempotency hits per chunk. Per-chunk recorder ⇒ per-chunk count.
        self._s5_skipped: int = 0
        self._s5_skipped_lock = threading.Lock()

    def start_batch(self, *, pipeline: str, batch_id: str) -> None:
        self._stage_buckets = {}
        if not self._enabled:
            return
        self._aggregator = SlowOpAggregator(
            threshold_ms=self._slow_op_threshold_ms,
            top_n=self._slow_op_top_n,
        )
        self._slow_op_handler = _SlowOpHandler(self._aggregator, batch_id=batch_id)
        self._bandwidth_handler = _BandwidthHandler(self._bandwidth)
        self._monitored_loggers = [
            logging.getLogger("cmcourier"),
            logging.getLogger("cmcourier.metrics.network"),
        ]
        for lg in self._monitored_loggers:
            lg.addHandler(self._slow_op_handler)
        logging.getLogger("cmcourier.metrics.network").addHandler(self._bandwidth_handler)
        _ = pipeline, batch_id  # reserved for future use

    def record_stage(
        self,
        *,
        stage: str,
        duration_ms: float,
    ) -> None:
        bucket = self._stage_buckets.setdefault(stage, _StageBucket())
        bucket.record(duration_ms)

    def current_stage_p95(self, stage: str) -> float:
        """Live p95 latency for a stage (025 — drives auto-tune)."""
        bucket = self._stage_buckets.get(stage)
        if bucket is None:
            return 0.0
        return float(bucket.summary()["p95_ms"])

    def close_batch(
        self,
        *,
        pipeline: str,
        batch_id: str,
        total_docs: int,
        elapsed_s: float,
    ) -> None:
        if not self._enabled:
            return
        try:
            if self._pipeline_metrics_enabled:
                summary = self._build_summary(
                    pipeline=pipeline,
                    batch_id=batch_id,
                    total_docs=total_docs,
                    elapsed_s=elapsed_s,
                )
                _pipeline_log.info(
                    "batch_summary",
                    extra={
                        "pipeline": summary.pipeline,
                        "batch_id": summary.batch_id,
                        "total_docs": summary.total_docs,
                        "elapsed_s": summary.elapsed_s,
                        "throughput_docs_per_s": summary.throughput_docs_per_s,
                        "stages": summary.stages,
                        "kind": "batch_summary",
                    },
                )
            self._flush_slow_ops(batch_id=batch_id)
        finally:
            self._detach_handler()

    # ------------------------------------------------------------------ internals

    def _build_summary(
        self,
        *,
        pipeline: str,
        batch_id: str,
        total_docs: int,
        elapsed_s: float,
    ) -> BatchSummary:
        throughput = (total_docs / elapsed_s) if elapsed_s > 0 else 0.0
        stages: dict[str, dict[str, float | int]] = {}
        for stage_name, bucket in sorted(self._stage_buckets.items()):
            stages[stage_name] = bucket.summary()
        return BatchSummary(
            pipeline=pipeline,
            batch_id=batch_id,
            total_docs=total_docs,
            elapsed_s=elapsed_s,
            throughput_docs_per_s=throughput,
            stages=stages,
        )

    def _flush_slow_ops(self, *, batch_id: str) -> None:
        if self._aggregator is None:
            return
        top = self._aggregator.top()
        if not top:
            return
        self._log_dir.mkdir(parents=True, exist_ok=True)
        path = self._log_dir / f"slow-ops-{batch_id}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            for entry in top:
                fh.write(json.dumps(entry, ensure_ascii=False))
                fh.write("\n")

    def _detach_handler(self) -> None:
        if self._slow_op_handler is None:
            return
        for lg in self._monitored_loggers:
            lg.removeHandler(self._slow_op_handler)
        if self._bandwidth_handler is not None:
            logging.getLogger("cmcourier.metrics.network").removeHandler(self._bandwidth_handler)
        self._slow_op_handler = None
        self._bandwidth_handler = None
        self._monitored_loggers = []
        self._aggregator = None

    # ---------------------------------------------------- TUI provider hooks

    @property
    def bandwidth(self) -> _BandwidthSampler:
        """Read-only handle for the TUI to fetch the bandwidth chart series."""
        return self._bandwidth

    def aggregator_snapshot(self) -> list[dict[str, Any]]:
        """Top-N slow ops snapshot for the TUI; empty when batch not active."""
        if self._aggregator is None:
            return []
        return self._aggregator.top()

    def stages_snapshot(self) -> dict[str, dict[str, float | int]]:
        """Per-stage percentile/count snapshot for the TUI."""
        return {stage: bucket.summary() for stage, bucket in self._stage_buckets.items()}

    def record_upload_skipped(self) -> None:
        """041: tally an S5 outcome of ``"skipped"`` (idempotency / claim-lost)."""
        with self._s5_skipped_lock:
            self._s5_skipped += 1

    def upload_skipped_count(self) -> int:
        with self._s5_skipped_lock:
            return self._s5_skipped


# ---------------------------------------------------------------------------
# StageTimer — context manager
# ---------------------------------------------------------------------------


class StageTimer:
    """Context manager that times one stage call and records to a recorder.

    On ``__exit__`` it:
    * records ``duration_ms`` on the recorder (so percentiles aggregate)
    * emits a ``stage_complete`` event to the ``cmcourier`` logger at
      INFO with the structured fields the JSON formatter promotes.
    """

    __slots__ = (
        "_batch_id",
        "_outcome",
        "_pipeline",
        "_recorder",
        "_stage",
        "_start_monotonic",
        "_txn_num",
    )

    def __init__(
        self,
        recorder: MetricsRecorder,
        *,
        pipeline: str,
        stage: str,
        batch_id: str,
        txn_num: str = "",
    ) -> None:
        self._recorder = recorder
        self._pipeline = pipeline
        self._stage = stage
        self._batch_id = batch_id
        self._txn_num = txn_num
        self._outcome = "OK"
        self._start_monotonic = 0.0

    def mark_failed(self) -> None:
        """Call from inside the ``with`` block when the caller catches
        a known-failure exception and continues. Without this hook,
        a caught exception looks like a success to ``__exit__``.
        """
        self._outcome = "FAIL"

    def __enter__(self) -> StageTimer:
        self._start_monotonic = time.monotonic()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        duration_ms = (time.monotonic() - self._start_monotonic) * 1000.0
        if exc_type is not None:
            self._outcome = "FAIL"
        self._recorder.record_stage(stage=self._stage, duration_ms=duration_ms)
        _app_log.info(
            "stage_complete",
            extra={
                "pipeline": self._pipeline,
                "stage": self._stage,
                "batch_id": self._batch_id,
                "txn_num": self._txn_num,
                "outcome": self._outcome,
                "duration_ms": round(duration_ms, 3),
            },
        )

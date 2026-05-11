"""Tier 5 observability — system resource sampling via ``psutil``.

Background daemon thread that takes a snapshot of host- and
process-level metrics every ``cfg.sample_interval_s`` seconds
and appends one JSON line per sample to
``{output_dir}/system-{date}.jsonl``.

The first sample's delta-based fields (``disk_*_mbps``,
``net_*_mbps``) are 0.0 — there's no baseline yet. Subsequent
samples compute the per-second rate against the previous
sample's counters. Errors from ``psutil`` are caught, logged at
WARNING, and skipped — the thread never dies.

See spec 026, REQ-005..REQ-016.
"""

from __future__ import annotations

__all__ = [
    "SystemMetricsSampler",
    "SystemSample",
    "build_sampler",
]

import datetime as _dt
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psutil

from cmcourier.config.schema import ObservabilityConfig, SystemMetricsConfig
from cmcourier.services.worker_pool_stats import WorkerPoolStats

_log = logging.getLogger("cmcourier.observability.system_metrics")

_BYTES_PER_MB = 1024 * 1024
_BITS_PER_BYTE = 8


@dataclass(frozen=True, slots=True)
class SystemSample:
    ts_iso: str
    cpu_pct: float
    ram_used_mb: int
    ram_total_mb: int
    disk_read_mbps: float
    disk_write_mbps: float
    net_in_mbps: float
    net_out_mbps: float
    process_pid: int
    process_threads: int
    process_cpu_pct: float
    process_rss_mb: int
    active_workers: int | None


class SystemMetricsSampler:
    """Daemon-thread tier-5 sampler.

    Construct it before the pipeline run; call ``start()`` when
    the run begins and ``stop()`` in a ``finally:`` block. Safe
    to call ``start()`` / ``stop()`` multiple times.
    """

    def __init__(
        self,
        *,
        cfg: SystemMetricsConfig,
        output_dir: Path,
        pool_stats: WorkerPoolStats | None = None,
    ) -> None:
        self._cfg = cfg
        self._output_dir = output_dir
        self._pool_stats = pool_stats
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # psutil.cpu_percent() returns 0.0 on its first call — seed it now
        # so the first real sample has a meaningful value.
        psutil.cpu_percent(interval=None)
        self._process = psutil.Process()
        self._process.cpu_percent(interval=None)  # seed per-process CPU too
        self._prev_disk: Any = None  # psutil sdiskio | None — see _take_sample
        self._prev_net: Any = None
        self._prev_ts: float | None = None

    # ----- public API ------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def attach_pool_stats(self, stats: WorkerPoolStats) -> None:
        """Late-bind the worker pool reference (REQ-006)."""
        self._pool_stats = stats

    def start(self) -> None:
        if not self._cfg.enabled or self.is_running:
            return
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="cmcourier-syssampler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._thread = None

    # ----- internals -------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                sample = self._take_sample()
                self._write_sample(sample)
            except (psutil.Error, OSError) as exc:
                _log.warning("system_metrics_sample_failed: %s", exc)
            self._stop.wait(self._cfg.sample_interval_s)

    def _take_sample(self) -> SystemSample:
        now = time.monotonic()
        cpu_pct = float(psutil.cpu_percent(interval=None))
        vm = psutil.virtual_memory()
        # psutil's stubs type these as ``sdiskio | None`` / ``snetio | None``
        # (None when counters wrap on some platforms). We treat None as
        # "no measurement available this tick" — same path as the first
        # call. Cast through Any so the arithmetic below stays readable.
        disk: Any = psutil.disk_io_counters()
        net: Any = psutil.net_io_counters()

        prev_disk = self._prev_disk
        prev_net = self._prev_net
        prev_ts = self._prev_ts
        if prev_disk is None or prev_net is None or prev_ts is None or disk is None or net is None:
            disk_read_mbps = 0.0
            disk_write_mbps = 0.0
            net_in_mbps = 0.0
            net_out_mbps = 0.0
        else:
            elapsed = max(now - prev_ts, 1e-6)
            disk_read_mbps = self._rate_mbps(disk.read_bytes - prev_disk.read_bytes, elapsed)
            disk_write_mbps = self._rate_mbps(disk.write_bytes - prev_disk.write_bytes, elapsed)
            net_in_mbps = self._rate_mbps(net.bytes_recv - prev_net.bytes_recv, elapsed)
            net_out_mbps = self._rate_mbps(net.bytes_sent - prev_net.bytes_sent, elapsed)

        self._prev_disk = disk
        self._prev_net = net
        self._prev_ts = now

        proc_cpu = float(self._process.cpu_percent(interval=None))
        proc_rss_mb = int(self._process.memory_info().rss / _BYTES_PER_MB)
        proc_threads = int(self._process.num_threads())
        proc_pid = int(self._process.pid)

        active = self._pool_stats.snapshot().busy if self._pool_stats is not None else None

        return SystemSample(
            ts_iso=_dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat(),
            cpu_pct=cpu_pct,
            ram_used_mb=int(vm.used / _BYTES_PER_MB),
            ram_total_mb=int(vm.total / _BYTES_PER_MB),
            disk_read_mbps=disk_read_mbps,
            disk_write_mbps=disk_write_mbps,
            net_in_mbps=net_in_mbps,
            net_out_mbps=net_out_mbps,
            process_pid=proc_pid,
            process_threads=proc_threads,
            process_cpu_pct=proc_cpu,
            process_rss_mb=proc_rss_mb,
            active_workers=active,
        )

    @staticmethod
    def _rate_mbps(delta_bytes: int, elapsed_s: float) -> float:
        """Convert a byte delta + elapsed window into megabits-per-second."""
        if delta_bytes <= 0 or elapsed_s <= 0:
            return 0.0
        return (delta_bytes * _BITS_PER_BYTE) / (elapsed_s * _BYTES_PER_MB)

    def _write_sample(self, sample: SystemSample) -> None:
        # Re-resolve filename on every write to support cross-midnight rotation.
        target = self._output_dir / f"system-{_dt.date.today().isoformat()}.jsonl"
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(sample), separators=(",", ":")) + "\n")


def build_sampler(
    observability_cfg: ObservabilityConfig,
    *,
    log_dir: Path,
) -> SystemMetricsSampler | None:
    """Factory — returns ``None`` when tier 5 is disabled."""
    sys_cfg = observability_cfg.system_metrics
    if not sys_cfg.enabled:
        return None
    return SystemMetricsSampler(cfg=sys_cfg, output_dir=log_dir)

"""Observabilidad `tier` 5 — sampling de recursos del sistema vía ``psutil``.

`Daemon thread` en background que toma un snapshot de métricas a nivel host y
proceso cada ``cfg.sample_interval_s`` segundos y appendea una línea JSON
por sample en ``{output_dir}/system-{date}.jsonl``.

Los campos basados en delta del primer sample (``disk_*_mbps``,
``net_*_mbps``) son 0.0 — todavía no hay baseline. Los samples
posteriores calculan la tasa por segundo contra los contadores del sample
anterior. Los errores de ``psutil`` se capturan, se loguean en WARNING y
se saltean — el thread nunca muere.

Ver spec 026, REQ-005..REQ-016.
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
    """Sampler de `tier` 5 en `daemon thread`.

    Construirlo antes de la corrida del pipeline; llamar a ``start()`` al
    arrancar la corrida y a ``stop()`` en un bloque ``finally:``. Es
    seguro llamar a ``start()`` / ``stop()`` varias veces.
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
        # psutil.cpu_percent() devuelve 0.0 en su primera llamada — la
        # seedeamos ahora para que el primer sample real tenga un valor
        # significativo.
        psutil.cpu_percent(interval=None)
        self._process = psutil.Process()
        self._process.cpu_percent(interval=None)  # también seedea CPU por proceso
        self._prev_disk: Any = None  # psutil sdiskio | None — ver _take_sample
        self._prev_net: Any = None
        self._prev_ts: float | None = None

    # ----- API pública ------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def attach_pool_stats(self, stats: WorkerPoolStats) -> None:
        """`Late-bind` de la referencia al worker pool (REQ-006)."""
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

    # ----- internos -------------------------------------------------

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
        # Los stubs de psutil tipan esto como ``sdiskio | None`` /
        # ``snetio | None`` (None cuando los contadores wrappean en algunas
        # plataformas). Tratamos None como "no hay medición disponible en
        # este tick" — mismo path que la primera llamada. Casteamos a
        # través de Any para que la aritmética de abajo quede legible.
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
        """Convierte un delta de bytes + ventana transcurrida en megabits por segundo."""
        if delta_bytes <= 0 or elapsed_s <= 0:
            return 0.0
        return (delta_bytes * _BITS_PER_BYTE) / (elapsed_s * _BYTES_PER_MB)

    def _write_sample(self, sample: SystemSample) -> None:
        # Re-resuelve el filename en cada escritura para soportar la
        # rotación cuando cruza la medianoche.
        target = self._output_dir / f"system-{_dt.date.today().isoformat()}.jsonl"
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(sample), separators=(",", ":")) + "\n")


def build_sampler(
    observability_cfg: ObservabilityConfig,
    *,
    log_dir: Path,
) -> SystemMetricsSampler | None:
    """Factory — devuelve ``None`` cuando el `tier` 5 está deshabilitado."""
    sys_cfg = observability_cfg.system_metrics
    if not sys_cfg.enabled:
        return None
    return SystemMetricsSampler(cfg=sys_cfg, output_dir=log_dir)

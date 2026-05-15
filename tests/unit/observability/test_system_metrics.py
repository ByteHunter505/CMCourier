"""Tests unitarios para el `sampler` de métricas de sistema tier-5 (026, REQ-017)."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from cmcourier.config.schema import ObservabilityConfig, SystemMetricsConfig
from cmcourier.observability.system_metrics import (
    SystemMetricsSampler,
    SystemSample,
    build_sampler,
)
from cmcourier.services.worker_pool_stats import WorkerPoolStats

# ---------------------------------------------------------------------------
# `psutil` falso — contadores determinísticos para aseverar deltas exactos
# ---------------------------------------------------------------------------


class _FakeProcess:
    def __init__(self) -> None:
        self.pid = 4242

    def num_threads(self) -> int:
        return 9

    def cpu_percent(self, interval: float | None = None) -> float:  # noqa: ARG002
        return 11.5

    def memory_info(self) -> SimpleNamespace:
        return SimpleNamespace(rss=250 * 1024 * 1024)


@pytest.fixture
def patched_psutil(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[object]]:
    """`Patch`ea `psutil` con valores determinísticos + una secuencia de contadores para I/O."""
    monkeypatch.setattr(psutil, "cpu_percent", lambda *a, **k: 42.0)
    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: SimpleNamespace(used=4 * 1024 * 1024 * 1024, total=16 * 1024 * 1024 * 1024),
    )
    monkeypatch.setattr(psutil, "Process", lambda *a, **k: _FakeProcess())

    disk_calls: list[object] = [
        SimpleNamespace(read_bytes=0, write_bytes=0),
        SimpleNamespace(read_bytes=10 * 1024 * 1024, write_bytes=20 * 1024 * 1024),
    ]
    net_calls: list[object] = [
        SimpleNamespace(bytes_recv=0, bytes_sent=0),
        SimpleNamespace(bytes_recv=5 * 1024 * 1024, bytes_sent=15 * 1024 * 1024),
    ]

    state = {"disk_idx": 0, "net_idx": 0}

    def _disk(**_: object) -> object:
        idx = min(state["disk_idx"], len(disk_calls) - 1)
        state["disk_idx"] += 1
        return disk_calls[idx]

    def _net(**_: object) -> object:
        idx = min(state["net_idx"], len(net_calls) - 1)
        state["net_idx"] += 1
        return net_calls[idx]

    monkeypatch.setattr(psutil, "disk_io_counters", _disk)
    monkeypatch.setattr(psutil, "net_io_counters", _net)
    return {"disk": disk_calls, "net": net_calls}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSystemMetricsSampler:
    def test_disabled_start_is_noop_no_file(
        self, tmp_path: Path, patched_psutil: dict[str, list[object]]
    ) -> None:
        cfg = SystemMetricsConfig(enabled=False, sample_interval_s=1.0)
        sampler = SystemMetricsSampler(cfg=cfg, output_dir=tmp_path)
        sampler.start()
        # Nada lanzado, ningún archivo dropeado.
        assert sampler.is_running is False
        time.sleep(0.1)
        assert list(tmp_path.glob("system-*.jsonl")) == []

    def test_start_stop_idempotent_thread_terminates(
        self, tmp_path: Path, patched_psutil: dict[str, list[object]]
    ) -> None:
        cfg = SystemMetricsConfig(enabled=True, sample_interval_s=1.0)
        sampler = SystemMetricsSampler(cfg=cfg, output_dir=tmp_path)
        sampler.start()
        sampler.start()  # idempotente — la segunda llamada es no-op
        assert sampler.is_running is True
        sampler.stop()
        sampler.stop()  # idempotente
        assert sampler.is_running is False

    def test_first_sample_has_zero_deltas(
        self, tmp_path: Path, patched_psutil: dict[str, list[object]]
    ) -> None:
        cfg = SystemMetricsConfig(enabled=True, sample_interval_s=1.0)
        sampler = SystemMetricsSampler(cfg=cfg, output_dir=tmp_path)
        sample = sampler._take_sample()  # noqa: SLF001 — acceso directo en test unitario
        assert isinstance(sample, SystemSample)
        assert sample.disk_read_mbps == 0.0
        assert sample.disk_write_mbps == 0.0
        assert sample.net_in_mbps == 0.0
        assert sample.net_out_mbps == 0.0
        assert sample.cpu_pct == 42.0
        assert sample.ram_used_mb == 4 * 1024
        assert sample.ram_total_mb == 16 * 1024
        assert sample.process_pid == 4242
        assert sample.process_threads == 9
        assert sample.process_rss_mb == 250

    def test_second_sample_computes_deltas(
        self,
        tmp_path: Path,
        patched_psutil: dict[str, list[object]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = SystemMetricsConfig(enabled=True, sample_interval_s=1.0)
        sampler = SystemMetricsSampler(cfg=cfg, output_dir=tmp_path)
        # Congela el reloj para que la ventana transcurrida sea
        # exactamente 1s entre muestras.
        times = iter([100.0, 101.0])
        monkeypatch.setattr(
            "cmcourier.observability.system_metrics.time.monotonic",
            lambda: next(times),
        )
        first = sampler._take_sample()  # noqa: SLF001
        second = sampler._take_sample()  # noqa: SLF001
        assert first.disk_read_mbps == 0.0
        # 10 MB leídos en 1 s = 10 MB/s = 80 Mb/s == 80.0
        assert second.disk_read_mbps == pytest.approx(10.0 * 8, rel=1e-3)
        # 20 MB escritos en 1 s = 160 Mb/s
        assert second.disk_write_mbps == pytest.approx(20.0 * 8, rel=1e-3)
        assert second.net_in_mbps == pytest.approx(5.0 * 8, rel=1e-3)
        assert second.net_out_mbps == pytest.approx(15.0 * 8, rel=1e-3)

    def test_active_workers_is_none_without_pool_stats(
        self, tmp_path: Path, patched_psutil: dict[str, list[object]]
    ) -> None:
        cfg = SystemMetricsConfig(enabled=True, sample_interval_s=1.0)
        sampler = SystemMetricsSampler(cfg=cfg, output_dir=tmp_path)
        sample = sampler._take_sample()  # noqa: SLF001
        assert sample.active_workers is None

    def test_active_workers_propagates_from_pool_stats(
        self, tmp_path: Path, patched_psutil: dict[str, list[object]]
    ) -> None:
        cfg = SystemMetricsConfig(enabled=True, sample_interval_s=1.0)
        pool_stats = WorkerPoolStats()
        pool_stats.set_pool_size(4)
        pool_stats.mark_busy("w1")
        pool_stats.mark_busy("w2")
        pool_stats.mark_busy("w3")
        sampler = SystemMetricsSampler(cfg=cfg, output_dir=tmp_path, pool_stats=pool_stats)
        sample = sampler._take_sample()  # noqa: SLF001
        assert sample.active_workers == 3

    def test_attach_pool_stats_late_binding(
        self, tmp_path: Path, patched_psutil: dict[str, list[object]]
    ) -> None:
        cfg = SystemMetricsConfig(enabled=True, sample_interval_s=1.0)
        sampler = SystemMetricsSampler(cfg=cfg, output_dir=tmp_path)
        assert sampler._take_sample().active_workers is None  # noqa: SLF001
        pool_stats = WorkerPoolStats()
        pool_stats.set_pool_size(2)
        pool_stats.mark_busy("w1")
        sampler.attach_pool_stats(pool_stats)
        assert sampler._take_sample().active_workers == 1  # noqa: SLF001

    def test_loop_writes_jsonl_to_today_file(
        self, tmp_path: Path, patched_psutil: dict[str, list[object]]
    ) -> None:
        cfg = SystemMetricsConfig(enabled=True, sample_interval_s=1.0)
        sampler = SystemMetricsSampler(cfg=cfg, output_dir=tmp_path)
        sampler.start()
        time.sleep(0.3)  # una muestra se escribe ni bien arranca el loop
        sampler.stop()
        today_file = tmp_path / f"system-{date.today().isoformat()}.jsonl"
        assert today_file.exists()
        lines = today_file.read_text().strip().splitlines()
        assert len(lines) >= 1
        parsed = json.loads(lines[0])
        for key in (
            "ts_iso",
            "cpu_pct",
            "ram_used_mb",
            "ram_total_mb",
            "disk_read_mbps",
            "disk_write_mbps",
            "net_in_mbps",
            "net_out_mbps",
            "process_pid",
            "process_threads",
            "process_cpu_pct",
            "process_rss_mb",
            "active_workers",
        ):
            assert key in parsed, f"falta la clave {key!r} en la muestra"


class TestBuildSampler:
    def test_returns_none_when_disabled(self, tmp_path: Path) -> None:
        cfg = ObservabilityConfig(system_metrics={"enabled": False}, log_dir=tmp_path)
        assert build_sampler(cfg, log_dir=tmp_path) is None

    def test_returns_instance_when_enabled(self, tmp_path: Path) -> None:
        cfg = ObservabilityConfig(system_metrics={"enabled": True}, log_dir=tmp_path)
        sampler = build_sampler(cfg, log_dir=tmp_path)
        assert isinstance(sampler, SystemMetricsSampler)

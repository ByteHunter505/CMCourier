"""Unit tests for the offline log analyzer (027)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cmcourier.services.analyze import (
    BatchReport,
    BottleneckClassification,
    LogReader,
    NetworkSummary,
    SystemSummary,
    build_batch_report,
    classify_bottleneck,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _batch_summary(batch_id: str, **overrides: object) -> dict:
    base = {
        "kind": "batch_summary",
        "batch_id": batch_id,
        "pipeline": "csv-trigger",
        "total_docs": 10,
        "elapsed_s": 12.34,
        "throughput_docs_per_s": 0.81,
        "stages": {
            "S5": {"count": 10, "p50_ms": 100.0, "p95_ms": 500.0, "p99_ms": 800.0},
            "S4": {"count": 10, "p50_ms": 50.0, "p95_ms": 90.0, "p99_ms": 110.0},
        },
    }
    base.update(overrides)
    return base


def _network_record(batch_id: str, kind: str, duration_ms: float, size: int = 0) -> dict:
    return {
        "kind": kind,
        "batch_id": batch_id,
        "duration_ms": duration_ms,
        "size_bytes": size,
        "worker": "w1",
    }


def _system_sample(batch_id: str, **overrides: object) -> dict:
    base = {
        "batch_id": batch_id,
        "ts_iso": "2026-05-11T12:00:00+00:00",
        "cpu_pct": 30.0,
        "ram_used_mb": 4096,
        "ram_total_mb": 16384,
        "disk_read_mbps": 5.0,
        "disk_write_mbps": 3.0,
        "net_in_mbps": 10.0,
        "net_out_mbps": 50.0,
        "process_pid": 1,
        "process_threads": 8,
        "process_cpu_pct": 25.0,
        "process_rss_mb": 200,
        "active_workers": 2,
    }
    base.update(overrides)
    return base


def _slow_op(batch_id: str, **overrides: object) -> dict:
    base = {
        "batch_id": batch_id,
        "kind": "cmis_upload",
        "duration_ms": 6000.0,
        "txn_num": "TXN_001",
        "worker": "w1",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# LogReader
# ---------------------------------------------------------------------------


class TestLogReader:
    def test_happy_path_reads_all_tiers(self, tmp_path: Path) -> None:
        _write_jsonl(tmp_path / "metrics-2026-05-11.jsonl", [_batch_summary("B1")])
        _write_jsonl(
            tmp_path / "network-2026-05-11.jsonl",
            [
                _network_record("B1", "cmis_upload", 200.0, 1024),
                _network_record("B2", "cmis_upload", 400.0),  # different batch
            ],
        )
        _write_jsonl(tmp_path / "system-2026-05-11.jsonl", [_system_sample("B1")])
        _write_jsonl(tmp_path / "slow-ops-B1.jsonl", [_slow_op("B1")])

        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("B1")

        assert len(records["pipeline"]) == 1
        assert records["pipeline"][0]["batch_id"] == "B1"
        assert len(records["network"]) == 1  # filtered by batch
        assert records["network"][0]["kind"] == "cmis_upload"
        assert len(records["system"]) == 1
        assert len(records["slow_ops"]) == 1

    def test_missing_files_yield_empty(self, tmp_path: Path) -> None:
        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("nope")
        assert records["pipeline"] == []
        assert records["network"] == []
        assert records["system"] == []
        assert records["slow_ops"] == []

    def test_corrupted_line_is_skipped(self, tmp_path: Path, caplog) -> None:
        path = tmp_path / "network-2026-05-11.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(_network_record("B1", "cmis_upload", 1.0)) + "\n")
            fh.write("{not valid json\n")
            fh.write(json.dumps(_network_record("B1", "cmis_upload", 2.0)) + "\n")
        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("B1")
        assert len(records["network"]) == 2  # the broken line skipped

    def test_cross_midnight_merges_files(self, tmp_path: Path) -> None:
        _write_jsonl(
            tmp_path / "network-2026-05-10.jsonl",
            [_network_record("B1", "cmis_upload", 100.0)],
        )
        _write_jsonl(
            tmp_path / "network-2026-05-11.jsonl",
            [_network_record("B1", "cmis_upload", 200.0)],
        )
        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("B1")
        assert len(records["network"]) == 2

    def test_system_samples_absent_returns_empty_list(self, tmp_path: Path) -> None:
        _write_jsonl(tmp_path / "metrics-2026-05-11.jsonl", [_batch_summary("B1")])
        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("B1")
        assert records["system"] == []


# ---------------------------------------------------------------------------
# classify_bottleneck
# ---------------------------------------------------------------------------


def _system_summary(
    *,
    cpu_pct_avg: float = 30.0,
    cpu_pct_max: float = 40.0,
    process_cpu_pct_avg: float = 25.0,
    process_cpu_pct_max: float = 35.0,
    ram_pct_avg: float = 0.4,
    ram_pct_max: float = 0.45,
    disk_total_mbps_avg: float = 10.0,
    disk_total_mbps_max: float = 15.0,
    net_total_mbps_avg: float = 20.0,
    net_total_mbps_max: float = 30.0,
    worker_saturation_pct: float = 0.2,
    sample_count: int = 10,
    cpu_bound_sample_pct: float = 0.0,
    memory_bound_sample_pct: float = 0.0,
    disk_bound_sample_pct: float = 0.0,
    network_bound_sample_pct: float = 0.0,
) -> SystemSummary:
    return SystemSummary(
        cpu_pct_avg=cpu_pct_avg,
        cpu_pct_max=cpu_pct_max,
        process_cpu_pct_avg=process_cpu_pct_avg,
        process_cpu_pct_max=process_cpu_pct_max,
        ram_pct_avg=ram_pct_avg,
        ram_pct_max=ram_pct_max,
        disk_total_mbps_avg=disk_total_mbps_avg,
        disk_total_mbps_max=disk_total_mbps_max,
        net_total_mbps_avg=net_total_mbps_avg,
        net_total_mbps_max=net_total_mbps_max,
        worker_saturation_pct=worker_saturation_pct,
        sample_count=sample_count,
        cpu_bound_sample_pct=cpu_bound_sample_pct,
        memory_bound_sample_pct=memory_bound_sample_pct,
        disk_bound_sample_pct=disk_bound_sample_pct,
        network_bound_sample_pct=network_bound_sample_pct,
    )


def _network_summary(p95_upload_ms: float = 200.0) -> NetworkSummary:
    return NetworkSummary(
        per_kind={
            "cmis_upload": {
                "count": 10,
                "p50_ms": 100.0,
                "p95_ms": p95_upload_ms,
                "p99_ms": 300.0,
                "total_bytes": 1024,
            },
        },
    )


class TestClassifyBottleneck:
    def test_cpu_bound_when_majority_samples_high_cpu(self) -> None:
        sysum = _system_summary(cpu_bound_sample_pct=0.6, process_cpu_pct_avg=85.0)
        cls = classify_bottleneck(
            sysum, _network_summary(), {}, cmis_max_bandwidth_mbps=0, pool_capacity=4
        )
        assert cls.classification == "cpu-bound"
        assert cls.confidence == pytest.approx(0.6)

    def test_memory_bound(self) -> None:
        sysum = _system_summary(memory_bound_sample_pct=0.7, ram_pct_avg=0.9)
        cls = classify_bottleneck(
            sysum, _network_summary(), {}, cmis_max_bandwidth_mbps=0, pool_capacity=4
        )
        assert cls.classification == "memory-bound"

    def test_disk_bound(self) -> None:
        sysum = _system_summary(
            disk_bound_sample_pct=0.55,
            disk_total_mbps_avg=150.0,
            cpu_pct_avg=20.0,
        )
        cls = classify_bottleneck(
            sysum, _network_summary(), {}, cmis_max_bandwidth_mbps=0, pool_capacity=4
        )
        assert cls.classification == "disk-bound"

    def test_network_bound_via_system(self) -> None:
        sysum = _system_summary(
            network_bound_sample_pct=0.6,
            net_total_mbps_avg=200.0,
        )
        cls = classify_bottleneck(
            sysum, _network_summary(), {}, cmis_max_bandwidth_mbps=250, pool_capacity=4
        )
        assert cls.classification == "network-bound"

    def test_worker_saturated_takes_precedence(self) -> None:
        sysum = _system_summary(
            worker_saturation_pct=0.9,
            cpu_bound_sample_pct=0.6,  # would also fire
        )
        cls = classify_bottleneck(
            sysum, _network_summary(), {}, cmis_max_bandwidth_mbps=0, pool_capacity=4
        )
        assert cls.classification == "worker-saturated"

    def test_tie_break_cpu_over_memory(self) -> None:
        sysum = _system_summary(
            cpu_bound_sample_pct=0.6,
            memory_bound_sample_pct=0.6,
        )
        cls = classify_bottleneck(
            sysum, _network_summary(), {}, cmis_max_bandwidth_mbps=0, pool_capacity=4
        )
        assert cls.classification == "cpu-bound"

    def test_under_utilized_when_nothing_fires(self) -> None:
        sysum = _system_summary()
        cls = classify_bottleneck(
            sysum, _network_summary(), {}, cmis_max_bandwidth_mbps=0, pool_capacity=4
        )
        assert cls.classification == "under-utilized"

    def test_no_system_samples_fallback_to_network_heuristic(self) -> None:
        cls = classify_bottleneck(
            None,
            _network_summary(p95_upload_ms=8000.0),  # high p95 → network-bound fallback
            {},
            cmis_max_bandwidth_mbps=0,
            pool_capacity=4,
        )
        assert cls.classification == "network-bound"


# ---------------------------------------------------------------------------
# build_batch_report
# ---------------------------------------------------------------------------


class TestBuildBatchReport:
    def test_aggregates_basic_report(self, tmp_path: Path) -> None:
        _write_jsonl(tmp_path / "metrics-2026-05-11.jsonl", [_batch_summary("B1")])
        _write_jsonl(
            tmp_path / "network-2026-05-11.jsonl",
            [
                _network_record("B1", "cmis_upload", 100.0, 1024),
                _network_record("B1", "cmis_upload", 200.0, 2048),
                _network_record("B1", "cmis_get", 50.0),
            ],
        )
        _write_jsonl(
            tmp_path / "system-2026-05-11.jsonl",
            [_system_sample("B1"), _system_sample("B1", cpu_pct=40.0)],
        )
        _write_jsonl(tmp_path / "slow-ops-B1.jsonl", [_slow_op("B1")])

        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("B1")
        report = build_batch_report(
            batch_id="B1",
            records=records,
            cmis_max_bandwidth_mbps=100,
            pool_capacity=4,
        )

        assert isinstance(report, BatchReport)
        assert report.batch_id == "B1"
        assert report.pipeline == "csv-trigger"
        assert report.total_docs == 10
        assert report.elapsed_s == 12.34
        assert "S5" in report.stage_summary
        assert report.network_summary.per_kind["cmis_upload"]["count"] == 2
        assert report.network_summary.per_kind["cmis_upload"]["total_bytes"] == 3072
        assert report.system_summary is not None
        assert report.system_summary.sample_count == 2
        assert len(report.slow_ops) == 1
        assert isinstance(report.bottleneck, BottleneckClassification)

    def test_report_with_no_system_metrics(self, tmp_path: Path) -> None:
        _write_jsonl(tmp_path / "metrics-2026-05-11.jsonl", [_batch_summary("B1")])
        _write_jsonl(
            tmp_path / "network-2026-05-11.jsonl",
            [_network_record("B1", "cmis_upload", 100.0)],
        )
        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("B1")
        report = build_batch_report(
            batch_id="B1",
            records=records,
            cmis_max_bandwidth_mbps=100,
            pool_capacity=4,
        )
        assert report.system_summary is None
        # No high p95 → under-utilized
        assert report.bottleneck.classification in {"under-utilized", "network-bound"}

    def test_unknown_batch_returns_empty_report(self, tmp_path: Path) -> None:
        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("missing")
        report = build_batch_report(
            batch_id="missing",
            records=records,
            cmis_max_bandwidth_mbps=0,
            pool_capacity=0,
        )
        assert report.batch_id == "missing"
        assert report.pipeline is None
        assert report.total_docs == 0
        assert report.elapsed_s == 0.0
        assert report.system_summary is None
        assert report.slow_ops == []

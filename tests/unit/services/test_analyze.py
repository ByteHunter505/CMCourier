"""Unit tests for the offline log analyzer (027, 053)."""

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

# The standard batch_summary closes at this wall time after a 12.34 s run,
# so the derived window is [2026-05-11T12:00:00, 2026-05-11T12:00:12.34].
_BATCH_TS = "2026-05-11T12:00:12.340000+00:00"
_IN_WINDOW = "2026-05-11T12:00:05+00:00"


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _stage(count: int, p50: float, p95: float, sum_ms: float) -> dict:
    return {"count": count, "p50_ms": p50, "p95_ms": p95, "p99_ms": p95 * 1.5, "sum_ms": sum_ms}


def _batch_summary(batch_id: str, **overrides: object) -> dict:
    base = {
        "kind": "batch_summary",
        "batch_id": batch_id,
        "ts": _BATCH_TS,
        "pipeline": "csv-trigger",
        "total_docs": 10,
        "elapsed_s": 12.34,
        "throughput_docs_per_s": 0.81,
        "stages": {
            "S5": _stage(10, 100.0, 500.0, 1000.0),
            "S4": _stage(10, 50.0, 90.0, 500.0),
        },
    }
    base.update(overrides)
    return base


def _network_record(
    batch_id: str,
    kind: str,
    duration_ms: float,
    size: int = 0,
    *,
    ts: str = _IN_WINDOW,
) -> dict:
    return {
        "kind": kind,
        "batch_id": batch_id,
        "ts": ts,
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
# LogReader — network/system are associated by TIME WINDOW (053), not batch_id
# ---------------------------------------------------------------------------


class TestLogReader:
    def test_happy_path_reads_all_tiers(self, tmp_path: Path) -> None:
        _write_jsonl(tmp_path / "metrics-2026-05-11.jsonl", [_batch_summary("B1")])
        _write_jsonl(
            tmp_path / "network-2026-05-11.jsonl",
            [
                _network_record("B1", "cmis_upload", 200.0, 1024),  # in-window
                # An unrelated record OUTSIDE the batch window is excluded by
                # timestamp — not by batch_id (these records carry none).
                _network_record("B2", "cmis_upload", 400.0, ts="2026-05-11T13:00:00+00:00"),
            ],
        )
        _write_jsonl(tmp_path / "system-2026-05-11.jsonl", [_system_sample("B1")])
        _write_jsonl(tmp_path / "slow-ops-B1.jsonl", [_slow_op("B1")])

        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("B1")

        assert len(records["pipeline"]) == 1
        assert records["pipeline"][0]["batch_id"] == "B1"
        assert len(records["network"]) == 1  # only the in-window record
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

    def test_corrupted_line_is_skipped(self, tmp_path: Path) -> None:
        _write_jsonl(tmp_path / "metrics-2026-05-11.jsonl", [_batch_summary("B1")])
        path = tmp_path / "network-2026-05-11.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(_network_record("B1", "cmis_upload", 1.0)) + "\n")
            fh.write("{not valid json\n")
            fh.write(json.dumps(_network_record("B1", "cmis_upload", 2.0)) + "\n")
        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("B1")
        assert len(records["network"]) == 2  # the broken line skipped

    def test_cross_midnight_merges_files(self, tmp_path: Path) -> None:
        # A batch that started 23:59 and ended 00:01 — its network records
        # land in two date-rotated files; the glob merges them and the
        # window [23:59:00, 00:01:00] keeps both.
        _write_jsonl(
            tmp_path / "metrics-2026-05-11.jsonl",
            [_batch_summary("B1", ts="2026-05-11T00:01:00+00:00", elapsed_s=120.0)],
        )
        _write_jsonl(
            tmp_path / "network-2026-05-10.jsonl",
            [_network_record("B1", "cmis_upload", 100.0, ts="2026-05-10T23:59:30+00:00")],
        )
        _write_jsonl(
            tmp_path / "network-2026-05-11.jsonl",
            [_network_record("B1", "cmis_upload", 200.0, ts="2026-05-11T00:00:30+00:00")],
        )
        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("B1")
        assert len(records["network"]) == 2

    def test_system_samples_absent_returns_empty_list(self, tmp_path: Path) -> None:
        _write_jsonl(tmp_path / "metrics-2026-05-11.jsonl", [_batch_summary("B1")])
        reader = LogReader(log_dir=tmp_path)
        records = reader.read_batch("B1")
        assert records["system"] == []

    def test_network_records_associated_by_time_window(self, tmp_path: Path) -> None:
        # 053 regression: network records carry NO batch_id. Only the
        # record inside the batch's time window must land in the report.
        _write_jsonl(tmp_path / "metrics-2026-05-11.jsonl", [_batch_summary("B1")])
        _write_jsonl(
            tmp_path / "network-2026-05-11.jsonl",
            [
                _network_record("ignored", "cmis_upload", 100.0, ts="2026-05-11T11:59:59+00:00"),
                _network_record("ignored", "cmis_upload", 200.0, ts="2026-05-11T12:00:05+00:00"),
                _network_record("ignored", "cmis_upload", 300.0, ts="2026-05-11T12:00:30+00:00"),
            ],
        )
        records = LogReader(log_dir=tmp_path).read_batch("B1")
        assert len(records["network"]) == 1
        assert records["network"][0]["duration_ms"] == 200.0

    def test_system_records_associated_by_time_window(self, tmp_path: Path) -> None:
        # 053 regression: system samples are filtered by ``ts_iso`` window.
        _write_jsonl(tmp_path / "metrics-2026-05-11.jsonl", [_batch_summary("B1")])
        _write_jsonl(
            tmp_path / "system-2026-05-11.jsonl",
            [
                _system_sample("ignored", ts_iso="2026-05-11T11:59:00+00:00"),
                _system_sample("ignored", ts_iso="2026-05-11T12:00:06+00:00"),
                _system_sample("ignored", ts_iso="2026-05-11T12:01:00+00:00"),
            ],
        )
        records = LogReader(log_dir=tmp_path).read_batch("B1")
        assert len(records["system"]) == 1

    def test_no_batch_summary_yields_empty_network_system(self, tmp_path: Path) -> None:
        # Window underivable (no batch_summary record) → the non-tagged
        # tiers come back empty rather than guessing.
        _write_jsonl(
            tmp_path / "metrics-2026-05-11.jsonl",
            [{"kind": "stage", "batch_id": "B1", "stage": "S5"}],
        )
        _write_jsonl(
            tmp_path / "network-2026-05-11.jsonl",
            [_network_record("B1", "cmis_upload", 1.0)],
        )
        _write_jsonl(tmp_path / "system-2026-05-11.jsonl", [_system_sample("B1")])
        records = LogReader(log_dir=tmp_path).read_batch("B1")
        assert records["network"] == []
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


# Stage breakdowns ----------------------------------------------------------

# The real 95-doc staging run: S5 (upload) dominated total stage time ~26×
# over the next stage. The old classifier ignored this and said
# "under-utilized" — see specs/053.
_STAGES_95_DOC_UPLOAD_BOUND = {
    "S0": _stage(95, 1.0, 2.0, 120.0),
    "S1": _stage(95, 8.0, 15.0, 900.0),
    "S2": _stage(95, 3.0, 6.0, 350.0),
    "S3": _stage(95, 5.0, 11.0, 600.0),
    "S4": _stage(95, 24.0, 40.0, 2280.0),
    "S5": _stage(95, 635.0, 1139.0, 60325.0),
}

_STAGES_ASSEMBLY_BOUND = {
    "S0": _stage(10, 1.0, 2.0, 100.0),
    "S1": _stage(10, 5.0, 9.0, 200.0),
    "S2": _stage(10, 5.0, 9.0, 200.0),
    "S3": _stage(10, 8.0, 14.0, 300.0),
    "S4": _stage(10, 200.0, 380.0, 2000.0),
    "S5": _stage(10, 50.0, 90.0, 500.0),
}

# No stage holds >= 45% of total stage time — a genuinely balanced run.
_STAGES_BALANCED = {
    "S3": _stage(10, 100.0, 180.0, 1000.0),
    "S4": _stage(10, 100.0, 180.0, 1000.0),
    "S5": _stage(10, 100.0, 180.0, 1000.0),
}


class TestClassifyBottleneck:
    # --- stage breakdown is the PRIMARY signal (053) -----------------------

    def test_classify_upload_bound_from_stage_dominance(self) -> None:
        # Named regression for the "under-utilized" bug: S5 dominates the
        # per-doc time → upload-bound, OUTSIDE the program.
        cls = classify_bottleneck(
            None,
            _network_summary(),
            _STAGES_95_DOC_UPLOAD_BOUND,
            cmis_max_bandwidth_mbps=0,
            pool_capacity=4,
        )
        assert cls.classification == "upload-bound"
        assert cls.confidence > 0.9
        assert any("S5" in r and "OUTSIDE" in r for r in cls.reasons)

    def test_classify_assembly_bound(self) -> None:
        cls = classify_bottleneck(
            None,
            _network_summary(),
            _STAGES_ASSEMBLY_BOUND,
            cmis_max_bandwidth_mbps=0,
            pool_capacity=4,
        )
        assert cls.classification == "assembly-bound"
        assert any("S4" in r and "INSIDE" in r for r in cls.reasons)

    def test_classify_under_utilized_when_balanced(self) -> None:
        # No dominant stage AND no system signal → genuinely idle.
        cls = classify_bottleneck(
            None,
            _network_summary(),
            _STAGES_BALANCED,
            cmis_max_bandwidth_mbps=0,
            pool_capacity=4,
        )
        assert cls.classification == "under-utilized"

    def test_upload_bound_surfaces_with_zero_bandwidth_cap(self) -> None:
        # The old regression: with cmis_max_bandwidth_mbps == 0 the
        # classifier could only say "under-utilized". The stage signal
        # carries the verdict now, cap or no cap.
        cls = classify_bottleneck(
            None,
            _network_summary(),
            _STAGES_95_DOC_UPLOAD_BOUND,
            cmis_max_bandwidth_mbps=0,
            pool_capacity=4,
        )
        assert cls.classification == "upload-bound"

    def test_worker_saturation_is_a_reason_not_the_verdict(self) -> None:
        # Worker-pool saturation is a SYMPTOM of a slow downstream. With an
        # S5-dominant breakdown the verdict is upload-bound; saturation is
        # appended as a corroborating reason, never the classification.
        sysum = _system_summary(worker_saturation_pct=0.9)
        cls = classify_bottleneck(
            sysum,
            _network_summary(),
            _STAGES_95_DOC_UPLOAD_BOUND,
            cmis_max_bandwidth_mbps=0,
            pool_capacity=4,
        )
        assert cls.classification == "upload-bound"
        assert any("saturat" in r.lower() for r in cls.reasons)

    def test_stage_verdict_appends_system_corroboration(self) -> None:
        sysum = _system_summary(cpu_bound_sample_pct=0.7, process_cpu_pct_avg=90.0)
        cls = classify_bottleneck(
            sysum,
            _network_summary(),
            _STAGES_ASSEMBLY_BOUND,
            cmis_max_bandwidth_mbps=0,
            pool_capacity=4,
        )
        assert cls.classification == "assembly-bound"  # stage wins
        assert any("process_cpu_pct" in r for r in cls.reasons)  # cpu corroborates

    # --- system metrics are the SECONDARY path (no dominant stage) ---------

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

    def test_worker_saturation_yields_to_a_real_resource_cause(self) -> None:
        # 053: with no dominant stage, a real resource cause (cpu) outranks
        # worker-saturation — saturation is a symptom, not a cause.
        sysum = _system_summary(
            worker_saturation_pct=0.9,
            cpu_bound_sample_pct=0.6,
        )
        cls = classify_bottleneck(
            sysum, _network_summary(), {}, cmis_max_bandwidth_mbps=0, pool_capacity=4
        )
        assert cls.classification == "cpu-bound"
        assert any("saturat" in r.lower() for r in cls.reasons)

    def test_worker_saturation_is_the_verdict_only_when_alone(self) -> None:
        sysum = _system_summary(worker_saturation_pct=0.95)
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

    # --- tertiary fallback: no stage data, no system data ------------------

    def test_no_system_no_stage_falls_back_to_upload_probe(self) -> None:
        cls = classify_bottleneck(
            None,
            _network_summary(p95_upload_ms=8000.0),  # high p95 → upload-bound probe
            {},
            cmis_max_bandwidth_mbps=0,
            pool_capacity=4,
        )
        assert cls.classification == "upload-bound"


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
        # S5 holds 1000/1500 of total stage time → upload-bound via the
        # stage-led path, no system data required.
        assert report.bottleneck.classification == "upload-bound"

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

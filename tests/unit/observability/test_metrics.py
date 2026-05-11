"""Unit tests for the metrics module.

Covers the percentile helper, batch summary builder, slow-op
aggregator, and ``StageTimer`` context manager outcome semantics.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

from cmcourier.observability.metrics import (
    MetricsRecorder,
    SlowOpAggregator,
    StageTimer,
    _percentile,
    _StageBucket,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _percentile
# ---------------------------------------------------------------------------


class TestPercentile:
    def test_empty_returns_zero(self) -> None:
        assert _percentile([], 0.5) == 0.0

    def test_single_value(self) -> None:
        assert _percentile([42.0], 0.50) == 42.0
        assert _percentile([42.0], 0.99) == 42.0

    def test_p50_odd_count(self) -> None:
        # 1, 2, 3, 4, 5 → p50 = 3
        assert _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.50) == 3.0

    def test_p99_picks_top_for_small_lists(self) -> None:
        # 10 values 1..10; p99 = top (nearest-rank ceiling)
        assert _percentile([float(i) for i in range(1, 11)], 0.99) == 10.0

    def test_p0_picks_first(self) -> None:
        assert _percentile([1.0, 2.0, 3.0], 0.0) == 1.0


# ---------------------------------------------------------------------------
# _StageBucket / BatchSummary
# ---------------------------------------------------------------------------


class TestStageBucket:
    def test_empty_bucket_zeros(self) -> None:
        bucket = _StageBucket()
        s = bucket.summary()
        assert s == {
            "count": 0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "sum_ms": 0.0,
        }

    def test_records_aggregated(self) -> None:
        bucket = _StageBucket()
        for v in (10.0, 20.0, 30.0, 40.0, 50.0):
            bucket.record(v)
        s = bucket.summary()
        assert s["count"] == 5
        assert s["sum_ms"] == 150.0
        assert s["p50_ms"] == 30.0


# ---------------------------------------------------------------------------
# SlowOpAggregator
# ---------------------------------------------------------------------------


class TestSlowOpAggregator:
    def test_below_threshold_dropped(self) -> None:
        agg = SlowOpAggregator(threshold_ms=100.0, top_n=10)
        agg.consider(kind="cmis_upload", duration_ms=50.0)
        agg.consider(kind="cmis_upload", duration_ms=99.99)
        assert agg.top() == []

    def test_above_threshold_kept(self) -> None:
        agg = SlowOpAggregator(threshold_ms=100.0, top_n=10)
        agg.consider(kind="cmis_upload", duration_ms=150.0, txn_num="T1")
        agg.consider(kind="as400_query", duration_ms=200.0)
        top = agg.top()
        assert len(top) == 2
        assert top[0]["rank"] == 1
        assert top[0]["kind"] == "as400_query"
        assert top[0]["duration_ms"] == 200.0
        assert top[1]["kind"] == "cmis_upload"

    def test_top_n_caps_results(self) -> None:
        agg = SlowOpAggregator(threshold_ms=0.0, top_n=3)
        for i in range(10):
            agg.consider(kind="x", duration_ms=float(i + 1))
        top = agg.top()
        assert len(top) == 3
        # Largest values, ranked desc.
        assert [e["duration_ms"] for e in top] == [10.0, 9.0, 8.0]
        assert [e["rank"] for e in top] == [1, 2, 3]

    def test_optional_fields_passed_through(self) -> None:
        agg = SlowOpAggregator(threshold_ms=0.0, top_n=1)
        agg.consider(
            kind="cmis_upload",
            duration_ms=100.0,
            txn_num="TXN_042",
            stage="S5_UPLOAD",
            size_bytes=1024,
            url_prefix="http://cmis.example",
        )
        entry = agg.top()[0]
        assert entry["txn_num"] == "TXN_042"
        assert entry["stage"] == "S5_UPLOAD"
        assert entry["size_bytes"] == 1024


# ---------------------------------------------------------------------------
# StageTimer
# ---------------------------------------------------------------------------


def _make_recorder(tmp_path: Path) -> MetricsRecorder:
    return MetricsRecorder(
        log_dir=tmp_path / "logs",
        slow_op_threshold_ms=0.0,
        slow_op_top_n=10,
        enabled=True,
        pipeline_metrics_enabled=True,
    )


class TestStageTimer:
    def test_records_on_exit(self, tmp_path: Path) -> None:
        recorder = _make_recorder(tmp_path)
        recorder.start_batch(pipeline="csv-trigger", batch_id="b1")
        with StageTimer(
            recorder,
            pipeline="csv-trigger",
            stage="S2_MAPPING",
            batch_id="b1",
            txn_num="TXN_001",
        ):
            time.sleep(0.001)
        bucket = recorder._stage_buckets["S2_MAPPING"]  # type: ignore[attr-defined]
        assert bucket.summary()["count"] == 1
        assert bucket.summary()["sum_ms"] > 0

    def test_outcome_fail_on_exception(self, tmp_path: Path, caplog) -> None:
        recorder = _make_recorder(tmp_path)
        recorder.start_batch(pipeline="csv-trigger", batch_id="b1")
        with (
            caplog.at_level(logging.INFO, logger="cmcourier"),
            pytest.raises(RuntimeError),
            StageTimer(
                recorder,
                pipeline="csv-trigger",
                stage="S5_UPLOAD",
                batch_id="b1",
                txn_num="TXN_001",
            ),
        ):
            raise RuntimeError("boom")
        # The stage_complete event was emitted with outcome=FAIL.
        outcomes = [
            getattr(r, "outcome", None) for r in caplog.records if r.message == "stage_complete"
        ]
        assert "FAIL" in outcomes


# ---------------------------------------------------------------------------
# MetricsRecorder.close_batch
# ---------------------------------------------------------------------------


class _RecordCollector(logging.Handler):
    """Test-only handler — direct capture from a specific logger.

    ``caplog`` attaches at root and only sees records that propagate
    up. The ``cmcourier.metrics.*`` loggers intentionally set
    ``propagate=False`` (to avoid duplicating metrics into the app
    log), so a direct handler is the reliable capture path for unit
    tests on those streams.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        # Ensure record.message is populated before downstream assertions.
        # Direct handlers (not chained through a Formatter) don't auto-fill
        # this; only Formatter.format() does. We materialize it here so
        # tests can rely on `record.message`.
        record.message = record.getMessage()
        self.records.append(record)


class TestMetricsRecorderCloseBatch:
    def test_close_batch_emits_summary_with_throughput(self, tmp_path: Path) -> None:
        recorder = _make_recorder(tmp_path)
        recorder.start_batch(pipeline="csv-trigger", batch_id="b1")
        recorder.record_stage(stage="S0", duration_ms=10.0)
        recorder.record_stage(stage="S0", duration_ms=20.0)
        recorder.record_stage(stage="S5", duration_ms=200.0)

        capture = _RecordCollector()
        pipeline_logger = logging.getLogger("cmcourier.metrics.pipeline")
        pipeline_logger.addHandler(capture)
        previous_level = pipeline_logger.level
        previous_disabled = pipeline_logger.disabled
        pipeline_logger.setLevel(logging.INFO)
        pipeline_logger.disabled = False
        try:
            recorder.close_batch(
                pipeline="csv-trigger",
                batch_id="b1",
                total_docs=2,
                elapsed_s=4.0,
            )
        finally:
            pipeline_logger.removeHandler(capture)
            pipeline_logger.setLevel(previous_level)
            pipeline_logger.disabled = previous_disabled

        summaries = [r for r in capture.records if r.message == "batch_summary"]
        assert len(summaries) == 1
        rec = summaries[0]
        assert rec.__dict__["pipeline"] == "csv-trigger"
        assert rec.__dict__["batch_id"] == "b1"
        assert rec.__dict__["total_docs"] == 2
        assert rec.__dict__["throughput_docs_per_s"] == pytest.approx(0.5)
        stages = rec.__dict__["stages"]
        assert stages["S0"]["count"] == 2
        assert stages["S5"]["count"] == 1

    def test_close_batch_disabled_no_emit(self, tmp_path: Path) -> None:
        recorder = MetricsRecorder(
            log_dir=tmp_path / "logs",
            slow_op_threshold_ms=0.0,
            slow_op_top_n=10,
            enabled=False,
            pipeline_metrics_enabled=False,
        )
        recorder.start_batch(pipeline="x", batch_id="b1")

        capture = _RecordCollector()
        pipeline_logger = logging.getLogger("cmcourier.metrics.pipeline")
        pipeline_logger.addHandler(capture)
        pipeline_logger.setLevel(logging.INFO)
        try:
            recorder.close_batch(pipeline="x", batch_id="b1", total_docs=0, elapsed_s=0.0)
        finally:
            pipeline_logger.removeHandler(capture)

        assert [r for r in capture.records if r.message == "batch_summary"] == []

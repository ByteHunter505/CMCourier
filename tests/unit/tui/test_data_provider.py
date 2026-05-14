"""Unit tests for :class:`TUIDataProvider` (025 phase 3)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cmcourier.config.schema import AutoTuneConfig, CmisConfigModel
from cmcourier.observability.metrics import MetricsRecorder
from cmcourier.services.worker_pool_stats import ResizableSemaphore, WorkerPoolStats
from cmcourier.tui.data_provider import PREP_STAGES, UPLOAD_STAGE, TUIDataProvider

pytestmark = pytest.mark.unit


def _make_provider(
    tmp_path: Path,
) -> tuple[
    TUIDataProvider,
    MetricsRecorder,
    WorkerPoolStats,
    ResizableSemaphore,
]:
    recorder = MetricsRecorder(
        log_dir=tmp_path / "logs",
        slow_op_threshold_ms=0.0,
        slow_op_top_n=10,
        enabled=True,
        pipeline_metrics_enabled=True,
    )
    pool_stats = WorkerPoolStats()
    sem = ResizableSemaphore(4)
    cmis = CmisConfigModel(
        base_url="http://cmis.bank.test:9080/cmis",
        repo_id="$x!t",
        workers=4,
        max_bandwidth_mbps=50.0,
        auto_tune=AutoTuneConfig(enabled=True, target_p95_ms=5000.0),
    )
    uploader = MagicMock()
    uploader._timeout_s = 300.0
    provider = TUIDataProvider(
        pipeline_name="csv-trigger",
        metrics_recorder=recorder,
        pool_stats=pool_stats,
        concurrency_limit=sem,
        cmis_config=cmis,
        uploader=uploader,
        auto_tune=None,
    )
    return provider, recorder, pool_stats, sem


class TestTUIDataProvider:
    def test_snapshot_baseline_fields(self, tmp_path: Path) -> None:
        provider, _r, _p, _s = _make_provider(tmp_path)
        snap = provider.snapshot()
        assert snap.pipeline == "csv-trigger"
        assert snap.is_complete is False
        assert snap.pool_capacity == 4
        assert snap.bandwidth_ceiling_mbps == 50.0
        assert PREP_STAGES == ("S0", "S1", "S2", "S3", "S4")
        assert UPLOAD_STAGE == "S5"

    def test_stages_reflect_recorded_data(self, tmp_path: Path) -> None:
        provider, recorder, _p, _s = _make_provider(tmp_path)
        recorder.record_stage(stage="S1", duration_ms=10.0)
        recorder.record_stage(stage="S5", duration_ms=500.0)
        snap = provider.snapshot()
        assert int(snap.stages["S1"]["count"]) == 1
        assert float(snap.stages["S5"]["p95_ms"]) == 500.0

    def test_pool_in_use_reflects_busy_workers(self, tmp_path: Path) -> None:
        provider, _r, pool, sem = _make_provider(tmp_path)
        sem.set_capacity(6)
        pool.set_pool_size(6)
        pool.mark_busy("w1")
        pool.mark_busy("w2")
        snap = provider.snapshot()
        assert snap.pool_capacity == 6
        assert snap.pool_in_use == 2
        assert snap.pool_idle == 4

    def test_auto_tune_disabled_when_no_controller(self, tmp_path: Path) -> None:
        provider, _r, _p, _s = _make_provider(tmp_path)
        snap = provider.snapshot()
        # cmis.auto_tune.enabled=True in the test config, but the controller
        # itself is None — so the "last move" fields are placeholders.
        assert snap.auto_tune_last_action == "—"
        assert snap.auto_tune_seconds_since_last_decision is None

    def test_bandwidth_ceiling_zero_means_auto_scale(self, tmp_path: Path) -> None:
        cmis = CmisConfigModel(
            base_url="x",
            repo_id="y",
            workers=4,
            max_bandwidth_mbps=0.0,
        )
        recorder = MetricsRecorder(
            log_dir=tmp_path / "logs",
            slow_op_threshold_ms=0.0,
            slow_op_top_n=10,
        )
        uploader = MagicMock()
        uploader._timeout_s = 300.0
        provider = TUIDataProvider(
            pipeline_name="x",
            metrics_recorder=recorder,
            pool_stats=WorkerPoolStats(),
            concurrency_limit=ResizableSemaphore(2),
            cmis_config=cmis,
            uploader=uploader,
        )
        snap = provider.snapshot()
        assert snap.bandwidth_ceiling_mbps == 0.0

    def test_mark_batch_lifecycle(self, tmp_path: Path) -> None:
        provider, _r, _p, _s = _make_provider(tmp_path)
        provider.mark_batch_started("batch_xyz")
        snap = provider.snapshot()
        assert snap.batch_id == "batch_xyz"
        assert snap.is_complete is False
        provider.mark_batch_complete()
        assert provider.snapshot().is_complete is True

    def test_elapsed_ticks_while_running(self, tmp_path: Path) -> None:
        provider, _r, _p, _s = _make_provider(tmp_path)
        provider.mark_batch_started("b")
        e1 = provider.snapshot().elapsed_s
        time.sleep(0.05)
        e2 = provider.snapshot().elapsed_s
        assert e2 > e1  # still running → the clock advances

    def test_elapsed_frozen_after_complete(self, tmp_path: Path) -> None:
        # 052: the run timer must FREEZE at completion, not tick forever.
        provider, _r, _p, _s = _make_provider(tmp_path)
        provider.mark_batch_started("b")
        provider.mark_batch_complete()
        e1 = provider.snapshot().elapsed_s
        time.sleep(0.05)
        e2 = provider.snapshot().elapsed_s
        assert e1 == e2

    def test_slow_ops_passes_through_aggregator(self, tmp_path: Path) -> None:
        provider, recorder, _p, _s = _make_provider(tmp_path)
        recorder.start_batch(pipeline="csv-trigger", batch_id="b1")
        # Inject a slow-op record by routing through the network logger.
        # Force INFO level — earlier tests may have set it to CRITICAL+1 via
        # observability.setup.configure.
        import logging as _logging

        net_log = _logging.getLogger("cmcourier.metrics.network")
        prev_level = net_log.level
        net_log.setLevel(_logging.INFO)
        try:
            net_log.info(
                "cmis_upload",
                extra={
                    "batch_id": "b1",
                    "kind": "cmis_upload",
                    "duration_ms": 9999.0,
                    "txn_num": "TXN_S",
                    "worker": "cmcourier-s5_3",
                    "size_bytes": 1024,
                },
            )
            snap = provider.snapshot()
            assert any(op.get("txn_num") == "TXN_S" for op in snap.slow_ops_all)
        finally:
            net_log.setLevel(prev_level)
            recorder.close_batch(pipeline="csv-trigger", batch_id="b1", total_docs=0, elapsed_s=1.0)

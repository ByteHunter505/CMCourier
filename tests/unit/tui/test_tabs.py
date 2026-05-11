"""Unit tests for the PREP/UPLOAD tab renderers (025 phase 3)."""

from __future__ import annotations

import pytest

from cmcourier.services.lane_controller import LaneSnapshot
from cmcourier.services.worker_pool_stats import WorkerPoolStatsSnapshot
from cmcourier.tui.data_provider import TUISnapshot
from cmcourier.tui.prep_tab import render_prep
from cmcourier.tui.upload_tab import render_upload

pytestmark = pytest.mark.unit


def _baseline_snap(**overrides: object) -> TUISnapshot:
    base: dict[str, object] = {
        "pipeline": "csv-trigger",
        "batch_id": "batch_001",
        "elapsed_s": 154.0,
        "throughput_docs_per_s": 1.42,
        "is_complete": False,
        "stages": {
            "S0": {"count": 100, "p50_ms": 4.0, "p95_ms": 8.0, "p99_ms": 12.0, "sum_ms": 600.0},
            "S1": {"count": 93, "p50_ms": 12.0, "p95_ms": 28.0, "p99_ms": 50.0, "sum_ms": 1500.0},
            "S5": {
                "count": 7,
                "p50_ms": 483.0,
                "p95_ms": 812.0,
                "p99_ms": 1240.0,
                "sum_ms": 3000.0,
            },
        },
        "pool_capacity": 8,
        "pool_in_use": 5,
        "pool_idle": 3,
        "queue_depth": 28,
        "auto_tune_enabled": True,
        "auto_tune_target_p95_ms": 5000.0,
        "auto_tune_observed_p95_ms": 812.0,
        "auto_tune_adjust_interval_s": 30,
        "auto_tune_next_in_s": 12.0,
        "auto_tune_timeout_s": 12.4,
        "auto_tune_timeout_min_s": 30,
        "auto_tune_timeout_max_s": 600,
        "auto_tune_last_action": "+1",
        "auto_tune_last_workers_after": 8,
        "auto_tune_seconds_since_last_decision": 16.0,
        "cmis_endpoint": "http://cmis.bank.test:9080/cmis",
        "bandwidth_current_mbps": 4.2,
        "bandwidth_peak_mbps": 7.1,
        "bandwidth_ceiling_mbps": 50.0,
        "bandwidth_series": tuple((-(60 - i), float(i % 7)) for i in range(60)),
        "slow_ops_all": (
            {
                "rank": 1,
                "kind": "s4_assembly",
                "stage": "S4_ASSEMBLY",
                "txn_num": "TXN_PREP",
                "duration_ms": 8920.0,
            },
            {
                "rank": 2,
                "kind": "cmis_upload",
                "stage": "S5_UPLOAD",
                "txn_num": "TXN_UP",
                "worker": "cmcourier-s5_8",
                "duration_ms": 2041.0,
            },
        ),
    }
    base.update(overrides)
    return TUISnapshot(**base)  # type: ignore[arg-type]


class TestRenderPrep:
    def test_includes_all_prep_stages(self) -> None:
        out = render_prep(_baseline_snap())
        for stage in ("S0 TRIGGER", "S1 INDEXING", "S2 MAPPING", "S3 METADATA", "S4 ASSEMBLY"):
            assert stage in out

    def test_shows_prep_slow_op(self) -> None:
        out = render_prep(_baseline_snap())
        assert "TXN_PREP" in out
        assert "S4_ASSEMBLY" in out

    def test_excludes_upload_slow_ops(self) -> None:
        out = render_prep(_baseline_snap())
        assert "TXN_UP" not in out  # belongs to UPLOAD tab


class TestRenderUpload:
    def test_includes_workers_panel(self) -> None:
        out = render_upload(_baseline_snap())
        assert "WORKERS" in out
        assert "Pool capacity:" in out
        assert "in-use 5" in out

    def test_includes_auto_tune_state(self) -> None:
        out = render_upload(_baseline_snap())
        assert "Auto-tune:       ON" in out
        assert "target p95:" in out
        assert "5,000 ms" in out
        assert "812.0 ms" in out
        assert "every 30s" in out

    def test_includes_network_panel(self) -> None:
        out = render_upload(_baseline_snap())
        assert "NETWORK" in out
        assert "cmis.bank.test:9080" in out
        assert "Bandwidth:" in out

    def test_chart_uses_config_ceiling(self) -> None:
        out = render_upload(_baseline_snap())
        assert "y: 0 → 50.0" in out

    def test_chart_auto_scale_when_ceiling_zero(self) -> None:
        out = render_upload(_baseline_snap(bandwidth_ceiling_mbps=0.0))
        # Network panel cites "(auto-scale)", chart caption says "y: 0 → peak".
        assert "(auto-scale)" in out
        assert "y: 0 → peak" in out

    def test_includes_upload_slow_op_with_worker(self) -> None:
        out = render_upload(_baseline_snap())
        assert "TXN_UP" in out
        assert "cmcourier-s5_8" in out

    def test_excludes_prep_slow_op(self) -> None:
        out = render_upload(_baseline_snap())
        assert "TXN_PREP" not in out

    def test_auto_tune_off_label(self) -> None:
        out = render_upload(_baseline_snap(auto_tune_enabled=False))
        assert "Auto-tune:       OFF" in out
        assert "target p95:" not in out

    def test_run_complete_overlay(self) -> None:
        out = render_upload(_baseline_snap(is_complete=True))
        assert "RUN COMPLETE" in out
        assert "[Q]" in out


# ---------------------------------------------------------------------------
# 036: dual heavy/light upload sub-panels
# ---------------------------------------------------------------------------


def _lane_snapshot(
    heavy_pool: int = 2,
    heavy_busy: int = 1,
    heavy_queue: int = 3,
    heavy_done: int = 17,
    heavy_failed: int = 1,
    light_pool: int = 8,
    light_busy: int = 6,
    light_queue: int = 42,
    light_done: int = 134,
    light_failed: int = 0,
    total: int = 10,
) -> LaneSnapshot:
    return LaneSnapshot(
        heavy=WorkerPoolStatsSnapshot(
            pool_size=heavy_pool,
            busy=heavy_busy,
            idle=max(0, heavy_pool - heavy_busy),
            queue_depth=heavy_queue,
            completed=heavy_done,
            failed=heavy_failed,
        ),
        light=WorkerPoolStatsSnapshot(
            pool_size=light_pool,
            busy=light_busy,
            idle=max(0, light_pool - light_busy),
            queue_depth=light_queue,
            completed=light_done,
            failed=light_failed,
        ),
        total_budget=total,
    )


class TestRenderUploadDualLanes:
    def test_single_lane_panel_when_lane_snapshot_none(self) -> None:
        # Default _baseline_snap() has lane_snapshot=None.
        out = render_upload(_baseline_snap())
        # Single-pool path: classic WORKERS panel labels.
        assert "Pool capacity:" in out
        assert "Queue depth:     28" in out
        # Dual-lane labels MUST NOT appear.
        assert "HEAVY" not in out
        assert "LIGHT" not in out

    def test_dual_lane_panels_when_snapshot_present(self) -> None:
        out = render_upload(_baseline_snap(lane_snapshot=_lane_snapshot()))
        # Dual-panel labels present.
        assert "WORKERS (heavy/light" in out
        assert "total budget 10" in out
        assert "HEAVY" in out
        assert "LIGHT" in out
        # Per-lane counters surfaced.
        assert "queue    3" in out  # heavy queue=3
        assert "queue   42" in out  # light queue=42
        assert "done    17" in out  # heavy completed
        assert "done   134" in out  # light completed
        # Single-pool labels SHOULD NOT appear in dual mode.
        assert "Pool capacity:" not in out

    def test_dual_lane_preserves_network_and_chart(self) -> None:
        out = render_upload(_baseline_snap(lane_snapshot=_lane_snapshot()))
        # The dual-panel only replaces the WORKERS block; network +
        # bandwidth chart + slow-ops must still render.
        assert "NETWORK (CMIS)" in out
        assert "UPLOAD SPEED" in out
        assert "SLOW OPS" in out

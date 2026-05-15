"""Unit tests for the BUCKET tab renderer (064)."""

from __future__ import annotations

import pytest

from cmcourier.orchestrators.streaming import StreamingSnapshot
from cmcourier.tui.bucket_tab import render_bucket
from cmcourier.tui.data_provider import TUISnapshot

pytestmark = pytest.mark.unit


def _streaming_snapshot(**kwargs: object) -> TUISnapshot:
    defaults = {
        "pipeline": "csv-trigger",
        "batch_id": "B1",
        "elapsed_s": 1.0,
        "throughput_docs_per_s": 0.0,
        "is_complete": False,
        "mode": "streaming",
        "bucket": StreamingSnapshot(
            bucket_level=4,
            bucket_cap=10,
            bucket_peak=8,
            prep_workers=4,
            prep_in_flight=2,
            upload_workers=8,
            prep_docs_per_s=12.0,
            upload_docs_per_s=10.5,
        ),
        "chunks_state": ({"s5_done": 50, "s5_failed": 1, "prep_skipped": 3},),
        "s1_filtered": 2,
    }
    defaults.update(kwargs)
    return TUISnapshot(**defaults)  # type: ignore[arg-type]


class TestRenderBucket:
    def test_streaming_mode_renders_all_blocks(self) -> None:
        out = render_bucket(_streaming_snapshot())
        # Sections
        assert "BUCKET" in out
        assert "THROUGHPUT" in out
        assert "WORKERS" in out
        assert "OUTCOMES" in out
        # Live data
        assert "4 / 10" in out  # level
        assert "8 / 10" in out  # peak
        assert "12.00 docs/s" in out
        assert "10.50 docs/s" in out
        # In-flight + worker counts
        assert "2 in-flight / 4" in out
        assert "8" in out  # upload workers
        # Outcomes (cumulative)
        assert "S5_DONE" in out
        assert "S5_FAILED" in out
        assert "S1_FILTERED" in out
        assert "S1_SKIPPED" in out

    def test_batched_mode_emits_stub(self) -> None:
        snap = TUISnapshot(
            pipeline="x",
            batch_id="b",
            elapsed_s=0.0,
            throughput_docs_per_s=0.0,
            is_complete=False,
            mode="batched",
            bucket=None,
        )
        out = render_bucket(snap)
        assert "streaming mode only" in out

    def test_missing_bucket_in_streaming_mode_emits_stub(self) -> None:
        # Defensive: streaming mode but no bucket data plumbed.
        snap = TUISnapshot(
            pipeline="x",
            batch_id="b",
            elapsed_s=0.0,
            throughput_docs_per_s=0.0,
            is_complete=False,
            mode="streaming",
            bucket=None,
        )
        out = render_bucket(snap)
        assert "streaming mode only" in out

    def test_cumulative_outcomes_sum_correctly(self) -> None:
        snap = _streaming_snapshot()
        out = render_bucket(snap)
        # s5_done=50, s5_failed=1, s1_filtered=2 (TUISnapshot field),
        # s1_skipped=3 (chunks_state[0].prep_skipped)
        assert "50" in out
        assert "1" in out
        assert "2" in out
        assert "3" in out

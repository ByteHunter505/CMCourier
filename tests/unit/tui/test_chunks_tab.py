"""Unit tests for the CHUNKS tab renderer (030)."""

from __future__ import annotations

from cmcourier.tui.chunks_tab import render_chunks
from cmcourier.tui.data_provider import TUISnapshot


def _snap(chunks: tuple[dict[str, object], ...]) -> TUISnapshot:
    return TUISnapshot(
        pipeline="csv-trigger",
        batch_id="",
        elapsed_s=0.0,
        throughput_docs_per_s=0.0,
        is_complete=False,
        chunks_state=chunks,
    )


class TestRenderChunks:
    def test_empty_chunks_shows_placeholder(self) -> None:
        out = render_chunks(_snap(()))
        assert "no chunks yet" in out
        assert "CHUNKS" in out

    def test_single_chunk_done(self) -> None:
        chunks = (
            {
                "chunk_idx": 0,
                "batch_id": "AAA",
                "status": "DONE",
                "s5_done": 5,
                "s5_failed": 0,
            },
        )
        out = render_chunks(_snap(chunks))
        assert "AAA" in out
        assert "DONE" in out
        assert "done 1" in out
        assert "total 1" in out

    def test_mixed_states(self) -> None:
        chunks = (
            {"chunk_idx": 0, "batch_id": "AAA", "status": "DONE", "s5_done": 5, "s5_failed": 0},
            {"chunk_idx": 1, "batch_id": "BBB", "status": "UPLOAD", "s5_done": 0, "s5_failed": 0},
            {"chunk_idx": 2, "batch_id": "CCC", "status": "PREP", "s5_done": 0, "s5_failed": 0},
            {"chunk_idx": 3, "batch_id": "", "status": "QUEUED", "s5_done": 0, "s5_failed": 0},
        )
        out = render_chunks(_snap(chunks))
        # The counts header sums each status correctly.
        assert "total 4" in out
        assert "done 1" in out
        assert "prep 1" in out
        assert "upload 1" in out
        assert "queued 1" in out
        # Every batch_id appears.
        for bid in ("AAA", "BBB", "CCC"):
            assert bid in out

    def test_failed_chunk_counted(self) -> None:
        chunks = (
            {"chunk_idx": 0, "batch_id": "AAA", "status": "FAILED", "s5_done": 0, "s5_failed": 0},
            {"chunk_idx": 1, "batch_id": "BBB", "status": "DONE", "s5_done": 3, "s5_failed": 0},
        )
        out = render_chunks(_snap(chunks))
        assert "failed 1" in out
        assert "done 1" in out

    def test_long_batch_id_truncated(self) -> None:
        long_id = "a" * 30  # > 14 char cap
        chunks = (
            {
                "chunk_idx": 0,
                "batch_id": long_id,
                "status": "DONE",
                "s5_done": 1,
                "s5_failed": 0,
            },
        )
        out = render_chunks(_snap(chunks))
        # First 14 chars present; full ID is not.
        assert "a" * 14 in out
        assert long_id not in out

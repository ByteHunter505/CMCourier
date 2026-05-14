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


class TestRenderChunksBreakdown041:
    """041: per-stage breakdown columns + aggregate TOTAL row."""

    def test_done_chunk_shows_full_breakdown(self) -> None:
        chunks = (
            {
                "chunk_idx": 0,
                "batch_id": "AAA",
                "status": "DONE",
                "s5_done": 95,
                "s5_failed": 0,
                "doc_count": 95,
                "total_bytes": 42 * 1_048_576,  # 42.0 MB
                "prep_done": 95,
                "prep_skipped": 0,
                "prep_failed": 0,
                "prep_filtered": 3,
                "prep_elapsed_s": 12.4,
                "upload_skipped": 0,
                "upload_elapsed_s": 8.9,
            },
        )
        out = render_chunks(_snap(chunks))
        # 051: PREP cell is done/skip/fail/filtered; UPLOAD stays done/skip/fail.
        assert "95/0/0/3   (12.4s)" in out
        assert "95/0/0   (8.9s)" in out
        assert "42.0" in out  # MB column

    def test_queued_chunk_dashes_in_both_stages(self) -> None:
        chunks = (
            {
                "chunk_idx": 0,
                "batch_id": "",
                "status": "QUEUED",
                "doc_count": 93,
                "total_bytes": 41 * 1_048_576,
            },
        )
        out = render_chunks(_snap(chunks))
        # QUEUED rows have placeholders, not bogus zeros.
        assert "—/—/—" in out
        assert "0/0/0" not in out

    def test_total_row_aggregates_across_chunks(self) -> None:
        chunks = (
            {
                "chunk_idx": 0,
                "batch_id": "AAA",
                "status": "DONE",
                "s5_done": 95,
                "s5_failed": 0,
                "doc_count": 95,
                "total_bytes": 42 * 1_048_576,
                "prep_done": 95,
                "prep_elapsed_s": 12.4,
                "upload_skipped": 0,
                "upload_elapsed_s": 8.9,
            },
            {
                "chunk_idx": 1,
                "batch_id": "BBB",
                "status": "UPLOAD",
                "s5_done": 87,
                "s5_failed": 4,
                "doc_count": 91,
                "total_bytes": 40 * 1_048_576,
                "prep_done": 91,
                "prep_elapsed_s": 12.1,
                "upload_skipped": 0,
                "upload_elapsed_s": 9.4,
            },
        )
        out = render_chunks(_snap(chunks))
        assert "TOTAL (2 chunks)" in out
        assert "186" in out  # docs aggregate
        assert "82.0" in out  # MB aggregate
        # prep done = 95 + 91 = 186
        assert "186/0/0" in out
        # upload done = 95 + 87 = 182 / failed = 0 + 4 = 4
        assert "182/0/4" in out

    def test_upload_in_flight_uses_live_elapsed_value(self) -> None:
        """When status==UPLOAD the data provider freezes prep_elapsed and
        keeps upload_elapsed live; render just trusts the field.
        """
        chunks = (
            {
                "chunk_idx": 0,
                "batch_id": "AAA",
                "status": "UPLOAD",
                "s5_done": 4,
                "s5_failed": 0,
                "doc_count": 10,
                "total_bytes": 5 * 1_048_576,
                "prep_done": 10,
                "prep_elapsed_s": 3.2,
                "upload_skipped": 0,
                "upload_elapsed_s": 1.5,
            },
        )
        out = render_chunks(_snap(chunks))
        assert "(3.2s)" in out
        assert "(1.5s)" in out
        assert "UPLOAD" in out


class TestRenderChunksLiveCounters042:
    """042 — when a chunk is in status UPLOAD, the row must reflect the
    live s5_done/s5_failed/upload_skipped from the upload-active recorder
    instead of waiting for the DONE transition (where the orchestrator
    persists them into ChunkState)."""

    def test_upload_row_shows_live_done_count(self) -> None:
        # The data_provider already substitutes the live values when it
        # has an upload_recorder; here we verify render_chunks renders
        # whatever the dict provides (the snapshot dict carries the
        # post-override values).
        chunks = (
            {
                "chunk_idx": 0,
                "batch_id": "AAA",
                "status": "UPLOAD",
                "s5_done": 17,  # live count from upload_done_count()
                "s5_failed": 0,
                "upload_skipped": 0,
                "doc_count": 50,
                "total_bytes": 5 * 1_048_576,
                "prep_done": 50,
                "prep_elapsed_s": 12.4,
                "upload_elapsed_s": 4.2,
            },
        )
        out = render_chunks(_snap(chunks))
        # Cell renders as done/skip/fail (elapsed)
        assert "17/0/0   (4.2s)" in out
        # NOT showing the stale 0/0/0 the pre-042 code would have shown
        assert "0/0/0   (4.2s)" not in out

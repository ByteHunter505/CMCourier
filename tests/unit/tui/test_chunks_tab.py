"""Tests unitarios para el renderizador de la pestaña CHUNKS (030)."""

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
        # El encabezado de conteos suma cada `status` correctamente.
        assert "total 4" in out
        assert "done 1" in out
        assert "prep 1" in out
        assert "upload 1" in out
        assert "queued 1" in out
        # Cada `batch_id` aparece.
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
        long_id = "a" * 30  # > tope de 14 caracteres
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
        # Los primeros 14 caracteres están presentes; el ID completo no.
        assert "a" * 14 in out
        assert long_id not in out


class TestRenderChunksBreakdown041:
    """041: columnas de desglose por etapa + fila TOTAL agregada."""

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
        # 051: la celda PREP es done/skip/fail/filtered; UPLOAD queda como done/skip/fail.
        assert "95/0/0/3   (12.4s)" in out
        assert "95/0/0   (8.9s)" in out
        assert "42.0" in out  # columna MB

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
        # Las filas QUEUED tienen `placeholder`s, no ceros falsos.
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
        assert "186" in out  # agregado de docs
        assert "82.0" in out  # agregado de MB
        # `prep` done = 95 + 91 = 186
        assert "186/0/0" in out
        # `upload` done = 95 + 87 = 182 / failed = 0 + 4 = 4
        assert "182/0/4" in out

    def test_upload_in_flight_uses_live_elapsed_value(self) -> None:
        """Cuando `status==UPLOAD` el `data_provider` congela
        `prep_elapsed` y mantiene `upload_elapsed` `live`; el render
        simplemente confía en el campo.
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
    """042 — cuando un `chunk` está en `status` UPLOAD, la fila debe
    reflejar los `s5_done/s5_failed/upload_skipped` `live` del
    `recorder` activo de upload en vez de esperar la transición a
    DONE (donde el orquestador los persiste en `ChunkState`)."""

    def test_upload_row_shows_live_done_count(self) -> None:
        # El `data_provider` ya sustituye los valores `live` cuando
        # tiene un `upload_recorder`; acá verificamos que
        # `render_chunks` renderiza lo que el dict provee (el dict del
        # snapshot trae los valores post-override).
        chunks = (
            {
                "chunk_idx": 0,
                "batch_id": "AAA",
                "status": "UPLOAD",
                "s5_done": 17,  # conteo `live` desde `upload_done_count()`
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
        # La celda renderiza como done/skip/fail (elapsed)
        assert "17/0/0   (4.2s)" in out
        # NO muestra el 0/0/0 `stale` que el código pre-042 mostraba
        assert "0/0/0   (4.2s)" not in out


# ---------------------------------------------------------------------------
# 052 — `throughput` UPLOAD por `chunk` (MB/s · docs/s)
# ---------------------------------------------------------------------------


class TestRenderChunksRate052:
    """La pestaña CHUNKS muestra el `throughput` UPLOAD por `chunk`;
    `elapsed` cero renderiza un guion en vez de dividir por cero."""

    def test_chunk_shows_upload_rate(self) -> None:
        chunks = (
            {
                "chunk_idx": 0,
                "batch_id": "AAA",
                "status": "DONE",
                "s5_done": 50,
                "s5_failed": 0,
                "doc_count": 50,
                "total_bytes": 100 * 1_048_576,  # 100 MB
                "prep_done": 50,
                "prep_elapsed_s": 5.0,
                "upload_elapsed_s": 10.0,
            },
        )
        out = render_chunks(_snap(chunks))
        # 100 MB / 10s = 10.0 MB/s; 50 docs / 10s = 5.0 docs/s
        assert "10.0 · 5.0" in out

    def test_zero_upload_elapsed_renders_dash_no_crash(self) -> None:
        chunks = (
            {
                "chunk_idx": 0,
                "batch_id": "AAA",
                "status": "PREP",
                "s5_done": 0,
                "s5_failed": 0,
                "doc_count": 50,
                "total_bytes": 10 * 1_048_576,
                "prep_done": 50,
                "prep_elapsed_s": 5.0,
                "upload_elapsed_s": 0.0,  # no arrancó → sin división por cero
            },
        )
        out = render_chunks(_snap(chunks))  # no debe levantar excepción
        assert "— · —" in out

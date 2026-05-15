"""Tests unitarios para el renderizador de la pestaña DETAIL (052)."""

from __future__ import annotations

import pytest

from cmcourier.domain.models import DocDetail
from cmcourier.tui.detail_tab import render_detail

pytestmark = pytest.mark.unit


def _doc(txn: str, *, status: str = "S5_DONE", reason: str = "", size: int = 2048) -> DocDetail:
    return DocDetail(
        txn_num=txn,
        file_name=f"{txn}.001",
        status=status,
        error_message=reason,
        file_size_bytes=size,
    )


class TestRenderDetail:
    def test_no_chunk_selected_shows_prompt(self) -> None:
        out = render_detail(None, [])
        assert "no chunk selected" in out
        assert "[" in out and "]" in out  # la sugerencia de cursor

    def test_renders_per_doc_table(self) -> None:
        chunk: dict[str, object] = {"chunk_idx": 2, "batch_id": "B-xyz", "status": "DONE"}
        docs = [_doc("TXN_A"), _doc("TXN_B", status="S5_FAILED", reason="cmis 500")]
        out = render_detail(chunk, docs)
        assert "chunk 2" in out
        assert "B-xyz" in out
        assert "TXN_A" in out and "TXN_B" in out
        assert "S5_FAILED" in out
        assert "cmis 500" in out  # se expone la razón de la falla

    def test_empty_docs_shows_placeholder(self) -> None:
        chunk: dict[str, object] = {"chunk_idx": 0, "batch_id": "B0", "status": "PREP"}
        out = render_detail(chunk, [])
        assert "no per-doc rows yet" in out

    def test_renders_all_rows_when_under_max(self) -> None:
        # 058: con el panel scrolleable, el tope previo de 100 filas
        # desapareció (subió a 2000). 1500 docs se renderizan todos —
        # sin pista de truncado.
        chunk: dict[str, object] = {"chunk_idx": 0, "batch_id": "BIG", "status": "DONE"}
        docs = [_doc(f"TXN_{i:04d}") for i in range(1500)]
        out = render_detail(chunk, docs)
        assert "TXN_0000" in out and "TXN_1499" in out
        assert "more" not in out  # sin pista de truncado a 1500

    def test_truncates_when_chunk_exceeds_max_rows(self) -> None:
        # El puntero al CLI sigue ahí para `chunk`s realmente enormes
        # por encima del techo de seguridad de 2000 filas.
        chunk: dict[str, object] = {"chunk_idx": 0, "batch_id": "HUGE", "status": "DONE"}
        docs = [_doc(f"TXN_{i:04d}") for i in range(2100)]
        out = render_detail(chunk, docs)
        assert "more" in out
        assert "cmcourier batch show HUGE" in out

    def test_size_humanized(self) -> None:
        chunk: dict[str, object] = {"chunk_idx": 0, "batch_id": "B", "status": "DONE"}
        out = render_detail(chunk, [_doc("T", size=5 * 1_048_576)])
        assert "5.0 MB" in out

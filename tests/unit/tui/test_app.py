"""`run_test()` pilot tests for ``CMCourierTUI`` — DETAIL pane + chunk
cursor (052)."""

from __future__ import annotations

import asyncio

import pytest
from textual.widgets import Static

from cmcourier.domain.models import DocDetail
from cmcourier.tui.app import CMCourierTUI
from cmcourier.tui.data_provider import TUISnapshot

pytestmark = pytest.mark.unit


class _FakeProvider:
    """Minimal provider for app pilot tests — two chunks, fixed per-doc
    detail keyed by batch_id."""

    def __init__(self) -> None:
        self._docs = {
            "B0": [DocDetail("T0", "T0.001", "S5_DONE", "", 100)],
            "B1": [DocDetail("T1", "T1.001", "S5_FAILED", "boom", 200)],
        }

    def snapshot(self) -> TUISnapshot:
        return TUISnapshot(
            pipeline="rvabrep-trigger",
            batch_id="B0",
            elapsed_s=1.0,
            throughput_docs_per_s=0.0,
            is_complete=False,
            chunks_state=(
                {"chunk_idx": 0, "batch_id": "B0", "status": "DONE"},
                {"chunk_idx": 1, "batch_id": "B1", "status": "UPLOAD"},
            ),
        )

    def docs_for_batch(self, batch_id: str) -> list[DocDetail]:
        return self._docs.get(batch_id, [])


def _detail_text(app: CMCourierTUI) -> str:
    return str(app.query_one("#detail_body", Static).renderable)


class TestDetailPaneSelection:
    def test_cursor_moves_and_detail_renders_selected_chunk(self) -> None:
        async def _run() -> None:
            app = CMCourierTUI(_FakeProvider())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                # Nothing selected yet → the DETAIL pane prompts.
                assert "no chunk selected" in _detail_text(app)

                # ] selects chunk 0.
                await pilot.press("]")
                await pilot.pause()
                assert app._selected_chunk_idx == 0  # noqa: SLF001
                app._refresh_panels()  # noqa: SLF001 — deterministic render
                body = _detail_text(app)
                assert "chunk 0" in body
                assert "T0" in body

                # ] again → chunk 1, with its failed doc + reason.
                await pilot.press("]")
                await pilot.pause()
                assert app._selected_chunk_idx == 1  # noqa: SLF001
                app._refresh_panels()  # noqa: SLF001
                body = _detail_text(app)
                assert "T1" in body
                assert "boom" in body

                # ] at the last chunk clamps — does not run off the end.
                await pilot.press("]")
                await pilot.pause()
                assert app._selected_chunk_idx == 1  # noqa: SLF001

                # [ walks back to chunk 0.
                await pilot.press("[")
                await pilot.pause()
                assert app._selected_chunk_idx == 0  # noqa: SLF001

        asyncio.run(_run())

    def test_d_key_switches_to_detail_tab(self) -> None:
        async def _run() -> None:
            from textual.widgets import TabbedContent

            app = CMCourierTUI(_FakeProvider())  # type: ignore[arg-type]
            async with app.run_test() as pilot:
                await pilot.press("d")
                await pilot.pause()
                assert app.query_one(TabbedContent).active == "detail"

        asyncio.run(_run())


class TestDetailPaneScroll058:
    def test_detail_body_is_inside_a_vertical_scroll(self) -> None:
        # 058: the DETAIL pane is the only one that can produce more
        # content than fits on screen. Its body must live inside a
        # ``VerticalScroll`` so the operator can read past the fold.
        async def _run() -> None:
            from textual.containers import VerticalScroll

            app = CMCourierTUI(_FakeProvider())  # type: ignore[arg-type]
            async with app.run_test():
                detail_body = app.query_one("#detail_body", Static)
                assert isinstance(detail_body.parent, VerticalScroll)

        asyncio.run(_run())

"""Four-tab textual App (025 phase 3 + 052).

The TUI runs on the main thread; the pipeline runs in a worker
thread. Communication is one-way (the TUI polls the provider every
~250 ms). On batch completion the orchestrator calls
``TUIDataProvider.mark_batch_complete`` and the app freezes the
final state on screen until the operator presses ``[Q]``.

052 adds a DETAIL tab: ``[`` / ``]`` move a chunk cursor, ``d`` jumps
to the tab, and the per-doc detail of the selected chunk is read from
the tracking store on demand.
"""

from __future__ import annotations

__all__ = ["CMCourierTUI"]

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from cmcourier.domain.models import DocDetail
from cmcourier.tui.bucket_tab import render_bucket
from cmcourier.tui.chunks_tab import render_chunks
from cmcourier.tui.data_provider import TUIDataProvider, TUISnapshot
from cmcourier.tui.detail_tab import render_detail
from cmcourier.tui.prep_tab import render_prep
from cmcourier.tui.upload_tab import render_upload

_REFRESH_INTERVAL_S: float = 0.25
_FOOTER_TEMPLATE = (
    "throughput {tps:.2f} docs/sec  elapsed {elapsed:02d}:{minutes:02d}:{seconds:02d}"
)


class CMCourierTUI(App[None]):
    """Live four-tab dashboard for an in-flight pipeline run."""

    TITLE = "CMCourier"
    BINDINGS = [
        Binding("p", "show_prep", "PREP"),
        Binding("u", "show_upload", "UPLOAD"),
        Binding("c", "show_chunks", "CHUNKS"),
        Binding("b", "show_bucket", "BUCKET"),
        Binding("d", "show_detail", "DETAIL"),
        Binding("[", "select_prev_chunk", "◀chunk"),
        Binding("]", "select_next_chunk", "chunk▶"),
        Binding("q", "quit", "Quit"),
    ]

    DEFAULT_CSS = """
    #status_bar {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 1;
    }
    Static.tab_body {
        height: 1fr;
        padding: 0 1;
    }
    #detail_body {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, data_provider: TUIDataProvider) -> None:
        super().__init__()
        self._provider = data_provider
        # 052: chunk cursor for the DETAIL tab. ``None`` until the
        # operator moves it with ``[`` / ``]``. ``_last_chunk_count`` is
        # refreshed every tick so the cursor actions clamp correctly.
        self._selected_chunk_idx: int | None = None
        self._last_chunk_count = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        # 064: BUCKET tab is mounted unconditionally; the renderer prints
        # a one-line stub in batched mode pointing to CHUNKS. Keeping the
        # tab list static across modes avoids re-composing on mode-change
        # (which Textual doesn't support after mount anyway).
        with TabbedContent(initial="prep"):
            with TabPane("PREP", id="prep"):
                yield Container(Static(id="prep_body", classes="tab_body"))
            with TabPane("UPLOAD", id="upload"):
                yield Container(Static(id="upload_body", classes="tab_body"))
            with TabPane("CHUNKS", id="chunks"):
                yield Container(Static(id="chunks_body", classes="tab_body"))
            with TabPane("BUCKET", id="bucket"):
                yield Container(Static(id="bucket_body", classes="tab_body"))
            with TabPane("DETAIL", id="detail"):
                # 058: VerticalScroll so chunks bigger than the visible
                # height are scrollable. ``#detail_body`` is sized to
                # ``height: auto`` (see CSS) so the inner Static grows
                # with its content and the parent scrolls through it.
                yield VerticalScroll(Static(id="detail_body"))
        yield Static(id="status_bar")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_panels()
        self.set_interval(_REFRESH_INTERVAL_S, self._refresh_panels)

    def action_show_prep(self) -> None:
        tabbed = self.query_one(TabbedContent)
        tabbed.active = "prep"

    def action_show_upload(self) -> None:
        tabbed = self.query_one(TabbedContent)
        tabbed.active = "upload"

    def action_show_chunks(self) -> None:
        tabbed = self.query_one(TabbedContent)
        tabbed.active = "chunks"

    def action_show_bucket(self) -> None:
        tabbed = self.query_one(TabbedContent)
        tabbed.active = "bucket"

    def action_show_detail(self) -> None:
        tabbed = self.query_one(TabbedContent)
        tabbed.active = "detail"

    def action_select_prev_chunk(self) -> None:
        """052: move the chunk cursor one step toward the first chunk."""
        if self._last_chunk_count == 0:
            return
        if self._selected_chunk_idx is None:
            self._selected_chunk_idx = 0
        else:
            self._selected_chunk_idx = max(0, self._selected_chunk_idx - 1)

    def action_select_next_chunk(self) -> None:
        """052: move the chunk cursor one step toward the last chunk."""
        if self._last_chunk_count == 0:
            return
        if self._selected_chunk_idx is None:
            self._selected_chunk_idx = 0
        else:
            self._selected_chunk_idx = min(self._last_chunk_count - 1, self._selected_chunk_idx + 1)

    def _resolve_detail(
        self, snap: TUISnapshot
    ) -> tuple[dict[str, object] | None, list[DocDetail]]:
        """052: resolve the selected chunk + its per-doc detail for the
        DETAIL pane. Returns ``(None, [])`` when no chunk is selected."""
        if self._selected_chunk_idx is None:
            return None, []
        chunk = next(
            (
                c
                for c in snap.chunks_state
                if isinstance(c.get("chunk_idx"), int)
                and c["chunk_idx"] == self._selected_chunk_idx
            ),
            None,
        )
        if chunk is None:
            return None, []
        return chunk, self._provider.docs_for_batch(str(chunk.get("batch_id", "")))

    def _refresh_panels(self) -> None:
        snap = self._provider.snapshot()
        self._last_chunk_count = len(snap.chunks_state)
        prep_body = self.query_one("#prep_body", Static)
        upload_body = self.query_one("#upload_body", Static)
        chunks_body = self.query_one("#chunks_body", Static)
        bucket_body = self.query_one("#bucket_body", Static)
        detail_body = self.query_one("#detail_body", Static)
        prep_body.update(render_prep(snap))
        upload_body.update(render_upload(snap))
        chunks_body.update(render_chunks(snap))
        bucket_body.update(render_bucket(snap))
        detail_body.update(render_detail(*self._resolve_detail(snap)))

        status = self.query_one("#status_bar", Static)
        total = int(snap.elapsed_s)
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        status.update(
            f"batch {snap.batch_id or '—'}  pipeline {snap.pipeline}  "
            + _FOOTER_TEMPLATE.format(
                tps=snap.throughput_docs_per_s,
                elapsed=hours,
                minutes=minutes,
                seconds=seconds,
            )
        )

        # Update the App.sub_title with the run state so it appears in the
        # header — gives the operator a glance-glance view even if focused
        # on a tab body.
        self.sub_title = (
            "RUN COMPLETE — press Q to exit"
            if snap.is_complete
            else f"{snap.pool_in_use}/{snap.pool_capacity} workers busy"
        )

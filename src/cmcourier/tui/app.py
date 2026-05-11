"""Two-tab textual App (REBIRTH §10.6, 025 phase 3).

The app runs in its own thread; the pipeline runs in the main
thread. Communication is one-way (TUI polls the provider every
~250 ms). On batch completion, the orchestrator calls
``TUIDataProvider.mark_batch_complete`` and the app freezes the
final state on screen until the operator presses ``[Q]``.
"""

from __future__ import annotations

__all__ = ["CMCourierTUI"]

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from cmcourier.tui.chunks_tab import render_chunks
from cmcourier.tui.data_provider import TUIDataProvider
from cmcourier.tui.prep_tab import render_prep
from cmcourier.tui.upload_tab import render_upload

_REFRESH_INTERVAL_S: float = 0.25
_FOOTER_TEMPLATE = (
    "throughput {tps:.2f} docs/sec  elapsed {elapsed:02d}:{minutes:02d}:{seconds:02d}"
)


class CMCourierTUI(App[None]):
    """Live two-tab dashboard for an in-flight pipeline run."""

    TITLE = "CMCourier"
    BINDINGS = [
        Binding("p", "show_prep", "PREP"),
        Binding("u", "show_upload", "UPLOAD"),
        Binding("c", "show_chunks", "CHUNKS"),
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
    """

    def __init__(self, data_provider: TUIDataProvider) -> None:
        super().__init__()
        self._provider = data_provider

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(initial="prep"):
            with TabPane("PREP", id="prep"):
                yield Container(Static(id="prep_body", classes="tab_body"))
            with TabPane("UPLOAD", id="upload"):
                yield Container(Static(id="upload_body", classes="tab_body"))
            with TabPane("CHUNKS", id="chunks"):
                yield Container(Static(id="chunks_body", classes="tab_body"))
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

    def _refresh_panels(self) -> None:
        snap = self._provider.snapshot()
        prep_body = self.query_one("#prep_body", Static)
        upload_body = self.query_one("#upload_body", Static)
        chunks_body = self.query_one("#chunks_body", Static)
        prep_body.update(render_prep(snap))
        upload_body.update(render_upload(snap))
        chunks_body.update(render_chunks(snap))

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

"""Runner that combines an in-flight pipeline with the live TUI (025).

The pipeline is CPU/IO-bound and prefers to run in a worker thread;
the textual ``App`` event loop runs in the main thread (textual
expects the main thread for its asyncio default loop + signal
handling). The two communicate one-way through a :class:`TUIDataProvider`.

Operator semantics:

* The TUI starts before the pipeline. ``mark_batch_started`` fires
  from the worker thread the moment the run begins.
* When the pipeline finishes (success or exception), the worker
  calls ``mark_batch_complete`` and the TUI flips into "run
  complete" mode. The operator presses ``[Q]`` to exit; pressing
  earlier exits the TUI but the worker still joins (so the
  pipeline is never abandoned mid-flight).
* Exceptions raised inside the pipeline thread are re-raised on
  the main thread once the operator quits the TUI.
"""

from __future__ import annotations

__all__ = ["TUIRunOutcome", "run_orchestrator_with_tui"]

import sys
import threading
from dataclasses import dataclass
from typing import Any

from cmcourier.orchestrators.multi_batch import (
    MultiBatchOrchestrator,
    MultiBatchRunReport,
)
from cmcourier.tui import CMCourierTUI, TUIDataProvider


@dataclass(slots=True)
class TUIRunOutcome:
    """Worker-thread outcome handed back to the caller after the TUI exits."""

    report: MultiBatchRunReport | None = None
    exception: BaseException | None = None


def tty_available() -> bool:
    """Whether the current process can render a textual UI.

    textual writes the TUI to ``stderr``; that's the one we check.
    stdin/stdout may be redirected without breaking the render
    (operators sometimes ``cmcourier ... | grep s5_done``).
    """
    return bool(sys.stderr.isatty())


def run_orchestrator_with_tui(
    *,
    orchestrator: MultiBatchOrchestrator,
    data_provider: TUIDataProvider,
    orchestrator_kwargs: dict[str, Any],
) -> TUIRunOutcome:
    """Run the multi-batch orchestrator in a worker thread while the TUI
    owns main. ``orchestrator_kwargs`` is splatted into
    ``orchestrator.run(**kwargs)`` (see :meth:`MultiBatchOrchestrator.run`).
    """
    outcome = TUIRunOutcome()

    def _worker() -> None:
        try:
            data_provider.mark_batch_started(
                batch_id=orchestrator_kwargs.get("resume_batch_id") or ""
            )
            outcome.report = orchestrator.run(**orchestrator_kwargs)
        except BaseException as exc:  # noqa: BLE001 — re-raised on main thread
            outcome.exception = exc
        finally:
            data_provider.mark_batch_complete()

    worker = threading.Thread(target=_worker, name="cmcourier-pipeline", daemon=False)
    worker.start()
    app = CMCourierTUI(data_provider)
    try:
        app.run()
    finally:
        # Always wait for the pipeline to finish before returning — pressing
        # Q during the run exits the TUI viewer but doesn't abandon the run.
        worker.join()
    return outcome

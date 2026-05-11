"""Thread-safe counters for the S5 worker pool (025).

The pool itself is a :class:`concurrent.futures.ThreadPoolExecutor`
in :mod:`cmcourier.orchestrators.staged`; this module just owns
the *visible state* the TUI and the auto-tune controller need to
read.

Snapshots are frozen ``WorkerPoolStatsSnapshot`` values — no
references back into mutable state — so consumers can compare /
log / render them safely from any thread.
"""

from __future__ import annotations

__all__ = ["WorkerPoolStats", "WorkerPoolStatsSnapshot"]

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkerPoolStatsSnapshot:
    """Read-only view of the S5 pool at one instant."""

    pool_size: int
    busy: int
    idle: int
    queue_depth: int
    completed: int
    failed: int


class WorkerPoolStats:
    """Mutable, thread-safe S5 pool counters.

    Hooks called from the orchestrator's worker submission /
    completion path:

    * ``set_pool_size`` — called once at S5 entry, again on every
      auto-tune resize (Phase 2 of 025).
    * ``mark_busy`` / ``mark_idle`` — bracket each upload.
    * ``mark_completed`` / ``mark_failed`` — per-doc outcome.
    * ``set_queue_depth`` — every ``as_completed`` tick.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pool_size = 0
        self._busy = 0
        self._completed = 0
        self._failed = 0
        self._queue_depth = 0

    # ------------------------------------------------------- mutators

    def set_pool_size(self, n: int) -> None:
        with self._lock:
            self._pool_size = max(0, int(n))

    def mark_busy(self, worker_name: str) -> None:
        del worker_name  # reserved for future per-worker stats
        with self._lock:
            self._busy += 1

    def mark_idle(self, worker_name: str) -> None:
        del worker_name
        with self._lock:
            self._busy = max(0, self._busy - 1)

    def mark_completed(self) -> None:
        with self._lock:
            self._completed += 1

    def mark_failed(self) -> None:
        with self._lock:
            self._failed += 1

    def set_queue_depth(self, n: int) -> None:
        with self._lock:
            self._queue_depth = max(0, int(n))

    # ------------------------------------------------------- snapshot

    def snapshot(self) -> WorkerPoolStatsSnapshot:
        with self._lock:
            return WorkerPoolStatsSnapshot(
                pool_size=self._pool_size,
                busy=self._busy,
                idle=max(0, self._pool_size - self._busy),
                queue_depth=self._queue_depth,
                completed=self._completed,
                failed=self._failed,
            )

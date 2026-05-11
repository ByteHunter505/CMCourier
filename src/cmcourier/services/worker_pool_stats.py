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

__all__ = ["ResizableSemaphore", "WorkerPoolStats", "WorkerPoolStatsSnapshot"]

import threading
from dataclasses import dataclass
from types import TracebackType


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


# ---------------------------------------------------------------------------
# ResizableSemaphore (025 phase 2)
# ---------------------------------------------------------------------------


class ResizableSemaphore:
    """Soft-cap concurrency limiter that supports runtime resize.

    Python's :class:`threading.Semaphore` has a fixed initial value and
    no public resize API. Our auto-tune controller wants to dial the
    effective parallelism up and down without tearing down the
    underlying ``ThreadPoolExecutor``. This class wraps a
    :class:`threading.Condition` + counter pair so:

    * :meth:`acquire` blocks while ``in_use >= capacity``.
    * :meth:`release` decrements and wakes one waiter.
    * :meth:`set_capacity` adjusts the cap and wakes any waiters that
      now fit.

    Use as a context manager (``with sem: ...``) to acquire/release
    inside one block.
    """

    def __init__(self, capacity: int) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._capacity = max(1, int(capacity))
        self._in_use = 0

    def acquire(self) -> None:
        with self._cond:
            while self._in_use >= self._capacity:
                self._cond.wait()
            self._in_use += 1

    def release(self) -> None:
        with self._cond:
            self._in_use = max(0, self._in_use - 1)
            self._cond.notify()

    def set_capacity(self, n: int) -> None:
        with self._cond:
            new_cap = max(1, int(n))
            grew = new_cap > self._capacity
            self._capacity = new_cap
            if grew:
                self._cond.notify_all()

    @property
    def capacity(self) -> int:
        with self._lock:
            return self._capacity

    @property
    def in_use(self) -> int:
        with self._lock:
            return self._in_use

    def __enter__(self) -> ResizableSemaphore:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.release()

"""Dual heavy/light lane coordination service (POST-MVP §1, 036).

Owns two :class:`ResizableSemaphore` instances and two
:class:`WorkerPoolStats` counters — one per lane. Couples to AIMD
via :meth:`set_total_budget` (AIMD owns the TOTAL worker count; this
controller owns the distribution). A daemon thread periodically
checks for drained lanes and migrates capacity to whichever lane
still has work.

Floor: each lane retains a minimum capacity of 1 (matches
``ResizableSemaphore``'s ``max(1, n)`` guarantee). A "fully drained
to other lane" event leaves the drained side with 1 reserve worker —
harmless because no items means no acquire calls.

Thread-safety: every public mutator takes the internal lock. Snapshot
methods take the lock briefly to grab counters then release before
returning frozen values.
"""

from __future__ import annotations

__all__ = ["Lane", "LaneController", "LaneSnapshot"]

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from cmcourier.services.lane_splitter import Lane
from cmcourier.services.worker_pool_stats import (
    ResizableSemaphore,
    WorkerPoolStats,
    WorkerPoolStatsSnapshot,
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LaneSnapshot:
    """Read-only view of both lanes at one instant. Consumed by the TUI."""

    heavy: WorkerPoolStatsSnapshot
    light: WorkerPoolStatsSnapshot
    total_budget: int


class LaneController:
    """Two ResizableSemaphores + drain-driven rebalance daemon.

    Lifecycle:

    1. Constructor sets initial heavy/light split from
       ``heavy_initial_ratio``.
    2. :meth:`start` launches the rebalance daemon. Idempotent.
    3. :meth:`acquire` / :meth:`release` for per-doc concurrency.
    4. :meth:`set_total_budget` from the AIMD controller.
    5. :meth:`stop` joins the daemon thread (call at pipeline
       shutdown).
    """

    def __init__(
        self,
        *,
        total_budget: int,
        heavy_initial_ratio: float,
        rebalance_interval_s: float,
        idle_threshold_s: float,
        clock: Callable[[], float] = time.monotonic,
        logger: logging.Logger | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._total = max(2, int(total_budget))
        self._heavy_initial_ratio = float(heavy_initial_ratio)
        heavy_cap, light_cap = self._initial_split(self._total, heavy_initial_ratio)
        self._heavy_sem = ResizableSemaphore(heavy_cap)
        self._light_sem = ResizableSemaphore(light_cap)
        self._heavy_stats = WorkerPoolStats()
        self._light_stats = WorkerPoolStats()
        self._heavy_stats.set_pool_size(heavy_cap)
        self._light_stats.set_pool_size(light_cap)
        self._rebalance_interval_s = float(rebalance_interval_s)
        self._idle_threshold_s = float(idle_threshold_s)
        self._clock = clock
        self._log = logger or _logger
        now = clock()
        self._heavy_last_active = now
        self._light_last_active = now
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ----- initial split -----

    @staticmethod
    def _initial_split(total: int, ratio: float) -> tuple[int, int]:
        """Return ``(heavy, light)`` with both >= 1 and sum == total."""
        if total < 2:
            return (1, 1)  # degenerate: floor applies, won't sum to total
        heavy = max(1, math.ceil(total * ratio))
        heavy = min(heavy, total - 1)  # leave at least 1 for light
        return (heavy, total - heavy)

    # ----- lifecycle -----

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        thread = threading.Thread(
            target=self._rebalance_loop,
            name="cmcourier-lane-rebalance",
            daemon=True,
        )
        thread.start()
        self._thread = thread

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._rebalance_interval_s * 2 + 1.0)

    # ----- per-lane concurrency -----

    def acquire(self, lane: Lane) -> None:
        sem = self._sem_for(lane)
        sem.acquire()
        stats = self._stats_for(lane)
        stats.mark_busy(threading.current_thread().name)

    def release(self, lane: Lane) -> None:
        stats = self._stats_for(lane)
        stats.mark_idle(threading.current_thread().name)
        self._sem_for(lane).release()

    def mark_completed(self, lane: Lane) -> None:
        self._stats_for(lane).mark_completed()

    def mark_failed(self, lane: Lane) -> None:
        self._stats_for(lane).mark_failed()

    def set_queue_depth(self, lane: Lane, depth: int) -> None:
        """Record a queue-depth update for the given lane.

        Side effect: when ``depth > 0``, the lane is marked active for
        drain tracking. The rebalance heuristic uses the time elapsed
        since the last positive depth to decide whether to migrate.
        """
        self._stats_for(lane).set_queue_depth(depth)
        if depth > 0:
            with self._lock:
                if lane == "heavy":
                    self._heavy_last_active = self._clock()
                else:
                    self._light_last_active = self._clock()

    # ----- AIMD coupling -----

    def set_total_budget(self, new_total: int) -> None:
        """AIMD hook: redistribute proportionally, preserving ratio.

        Each lane retains at least one slot when ``new_total >= 2``.
        """
        new_total = max(2, int(new_total))
        with self._lock:
            heavy_cap = self._heavy_sem.capacity
            light_cap = self._light_sem.capacity
            current_total = heavy_cap + light_cap
            ratio = self._heavy_initial_ratio if current_total <= 0 else heavy_cap / current_total
            new_heavy = max(1, round(new_total * ratio))
            new_heavy = min(new_heavy, new_total - 1)
            new_light = new_total - new_heavy
            self._heavy_sem.set_capacity(new_heavy)
            self._light_sem.set_capacity(new_light)
            self._heavy_stats.set_pool_size(new_heavy)
            self._light_stats.set_pool_size(new_light)
            self._total = new_total

    # ----- snapshots -----

    def snapshot(self) -> LaneSnapshot:
        return LaneSnapshot(
            heavy=self._heavy_stats.snapshot(),
            light=self._light_stats.snapshot(),
            total_budget=self._total,
        )

    @property
    def heavy_capacity(self) -> int:
        return self._heavy_sem.capacity

    @property
    def light_capacity(self) -> int:
        return self._light_sem.capacity

    # ----- rebalance loop -----

    def rebalance_tick(self) -> None:
        """One iteration of the drain heuristic. Public for testing."""
        with self._lock:
            now = self._clock()
            heavy_idle_s = now - self._heavy_last_active
            light_idle_s = now - self._light_last_active
            heavy_cap = self._heavy_sem.capacity
            light_cap = self._light_sem.capacity
            total = heavy_cap + light_cap
            new_heavy = heavy_cap
            new_light = light_cap
            migrated_from: Lane | None = None
            if heavy_idle_s >= self._idle_threshold_s and heavy_cap > 1:
                new_heavy = 1
                new_light = total - 1
                migrated_from = "heavy"
            elif light_idle_s >= self._idle_threshold_s and light_cap > 1:
                new_light = 1
                new_heavy = total - 1
                migrated_from = "light"
            if migrated_from is None:
                return
            self._heavy_sem.set_capacity(new_heavy)
            self._light_sem.set_capacity(new_light)
            self._heavy_stats.set_pool_size(new_heavy)
            self._light_stats.set_pool_size(new_light)
            event = {
                "event": "lane_rebalance",
                "from": migrated_from,
                "to": "light" if migrated_from == "heavy" else "heavy",
                "previous_heavy": heavy_cap,
                "previous_light": light_cap,
                "new_heavy": new_heavy,
                "new_light": new_light,
            }
        self._log.info("lane rebalance: %s -> other", migrated_from, extra=event)

    def _rebalance_loop(self) -> None:
        while not self._stop_event.is_set():
            self.rebalance_tick()
            self._stop_event.wait(self._rebalance_interval_s)

    # ----- internal -----

    def _sem_for(self, lane: Lane) -> ResizableSemaphore:
        return self._heavy_sem if lane == "heavy" else self._light_sem

    def _stats_for(self, lane: Lane) -> WorkerPoolStats:
        return self._heavy_stats if lane == "heavy" else self._light_stats

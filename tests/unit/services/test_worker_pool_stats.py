"""Unit tests for :class:`WorkerPoolStats` (025)."""

from __future__ import annotations

import threading

import pytest

from cmcourier.services.worker_pool_stats import (
    WorkerPoolStats,
    WorkerPoolStatsSnapshot,
)

pytestmark = pytest.mark.unit


class TestWorkerPoolStats:
    def test_initial_snapshot_is_zero(self) -> None:
        stats = WorkerPoolStats()
        snap = stats.snapshot()
        assert snap.pool_size == 0
        assert snap.busy == 0
        assert snap.idle == 0
        assert snap.queue_depth == 0
        assert snap.completed == 0
        assert snap.failed == 0

    def test_busy_idle_balance(self) -> None:
        stats = WorkerPoolStats()
        stats.set_pool_size(4)
        stats.mark_busy("w1")
        stats.mark_busy("w2")
        snap = stats.snapshot()
        assert snap.busy == 2
        assert snap.idle == 2  # pool_size - busy

        stats.mark_idle("w1")
        snap = stats.snapshot()
        assert snap.busy == 1
        assert snap.idle == 3

    def test_idle_never_negative(self) -> None:
        """If busy somehow exceeds pool_size (race during shrink), idle clamps to 0."""
        stats = WorkerPoolStats()
        stats.set_pool_size(2)
        stats.mark_busy("w1")
        stats.mark_busy("w2")
        stats.mark_busy("w3")
        snap = stats.snapshot()
        assert snap.busy == 3
        assert snap.idle == 0

    def test_completed_and_failed_counters(self) -> None:
        stats = WorkerPoolStats()
        for _ in range(5):
            stats.mark_completed()
        for _ in range(2):
            stats.mark_failed()
        snap = stats.snapshot()
        assert snap.completed == 5
        assert snap.failed == 2

    def test_set_queue_depth(self) -> None:
        stats = WorkerPoolStats()
        stats.set_queue_depth(42)
        assert stats.snapshot().queue_depth == 42
        stats.set_queue_depth(-5)
        assert stats.snapshot().queue_depth == 0

    def test_thread_safety_under_concurrency(self) -> None:
        """Hammer the counters from 8 threads; final totals must match."""
        stats = WorkerPoolStats()
        stats.set_pool_size(8)
        n_ops = 1000

        def hammer() -> None:
            for _ in range(n_ops):
                stats.mark_busy("w")
                stats.mark_completed()
                stats.mark_idle("w")

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = stats.snapshot()
        assert snap.completed == 8 * n_ops
        assert snap.busy == 0  # every mark_busy paired with mark_idle

    def test_snapshot_is_frozen(self) -> None:
        stats = WorkerPoolStats()
        snap = stats.snapshot()
        assert isinstance(snap, WorkerPoolStatsSnapshot)
        with pytest.raises(AttributeError):
            snap.pool_size = 99  # type: ignore[misc]

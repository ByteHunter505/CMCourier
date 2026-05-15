"""Tests unitarios para :class:`WorkerPoolStats` (025)."""

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
        assert snap.idle == 2  # `pool_size` - `busy`

        stats.mark_idle("w1")
        snap = stats.snapshot()
        assert snap.busy == 1
        assert snap.idle == 3

    def test_idle_never_negative(self) -> None:
        """Si `busy` excede `pool_size` (race durante shrink), `idle` se clampea a 0."""
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
        """Martillea los contadores desde 8 `thread`s; los totales finales deben coincidir."""
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
        assert snap.busy == 0  # cada `mark_busy` apareado con `mark_idle`

    def test_snapshot_is_frozen(self) -> None:
        stats = WorkerPoolStats()
        snap = stats.snapshot()
        assert isinstance(snap, WorkerPoolStatsSnapshot)
        with pytest.raises(AttributeError):
            snap.pool_size = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ResizableSemaphore (025 phase 2)
# ---------------------------------------------------------------------------


class TestResizableSemaphore:
    def test_acquire_release_roundtrip(self) -> None:
        from cmcourier.services.worker_pool_stats import ResizableSemaphore

        sem = ResizableSemaphore(2)
        sem.acquire()
        assert sem.in_use == 1
        sem.acquire()
        assert sem.in_use == 2
        sem.release()
        assert sem.in_use == 1
        sem.release()
        assert sem.in_use == 0

    def test_acquire_blocks_at_capacity(self) -> None:
        import threading as _t
        import time as _time

        from cmcourier.services.worker_pool_stats import ResizableSemaphore

        sem = ResizableSemaphore(1)
        sem.acquire()
        acquired = _t.Event()

        def second() -> None:
            sem.acquire()
            acquired.set()

        t = _t.Thread(target=second, daemon=True)
        t.start()
        # Le da tiempo al `thread` para intentar y bloquearse.
        _time.sleep(0.05)
        assert not acquired.is_set()
        sem.release()
        t.join(timeout=1.0)
        assert acquired.is_set()
        sem.release()

    def test_set_capacity_grow_wakes_waiters(self) -> None:
        import threading as _t
        import time as _time

        from cmcourier.services.worker_pool_stats import ResizableSemaphore

        sem = ResizableSemaphore(1)
        sem.acquire()
        results: list[str] = []

        def waiter(name: str) -> None:
            sem.acquire()
            results.append(name)

        t1 = _t.Thread(target=waiter, args=("a",), daemon=True)
        t2 = _t.Thread(target=waiter, args=("b",), daemon=True)
        t1.start()
        t2.start()
        _time.sleep(0.05)
        assert results == []
        # Crece capacidad a 3 — ambos `waiter`s deberían proceder.
        sem.set_capacity(3)
        t1.join(timeout=1.0)
        t2.join(timeout=1.0)
        assert sorted(results) == ["a", "b"]
        # Limpieza.
        sem.release()
        sem.release()
        sem.release()

    def test_set_capacity_shrink_does_not_revoke(self) -> None:
        """Bajar el `cap` con `worker`s ya `in-flight` no los corta."""
        from cmcourier.services.worker_pool_stats import ResizableSemaphore

        sem = ResizableSemaphore(4)
        for _ in range(3):
            sem.acquire()
        sem.set_capacity(2)
        # 3 `worker`s siguen `in-flight`; `capacity` reporta 2 pero
        # `in_use` es 3.
        assert sem.capacity == 2
        assert sem.in_use == 3
        # Los `release` subsiguientes bajan `in_use` de nuevo.
        sem.release()
        sem.release()
        sem.release()
        assert sem.in_use == 0

    def test_context_manager(self) -> None:
        from cmcourier.services.worker_pool_stats import ResizableSemaphore

        sem = ResizableSemaphore(2)
        with sem:
            assert sem.in_use == 1
        assert sem.in_use == 0

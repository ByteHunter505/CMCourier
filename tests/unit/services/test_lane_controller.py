"""Unit tests for :class:`LaneController` (036 Phase 2).

The controller owns two ``ResizableSemaphore``s plus stats; AIMD
drives total budget, the controller distributes per-lane. A daemon
thread runs the drain heuristic — tests invoke ``rebalance_tick``
directly to keep them deterministic.
"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from cmcourier.services.lane_controller import LaneController, LaneSnapshot

pytestmark = pytest.mark.unit


def _build(
    *,
    total: int = 10,
    ratio: float = 0.2,
    rebalance_interval_s: float = 1.0,
    idle_threshold_s: float = 5.0,
    clock_value: list[float] | None = None,
    logger: logging.Logger | None = None,
) -> tuple[LaneController, list[float]]:
    """Build a controller wired to a tickable clock.

    Returns ``(controller, clock_list)``. Mutate ``clock_list[0]``
    to advance simulated time.
    """
    clock = clock_value if clock_value is not None else [0.0]

    def now() -> float:
        return clock[0]

    ctl = LaneController(
        total_budget=total,
        heavy_initial_ratio=ratio,
        rebalance_interval_s=rebalance_interval_s,
        idle_threshold_s=idle_threshold_s,
        clock=now,
        logger=logger,
    )
    return ctl, clock


class TestInitialAllocation:
    def test_default_ratio_splits_correctly(self) -> None:
        ctl, _ = _build(total=10, ratio=0.2)
        assert ctl.heavy_capacity == 2
        assert ctl.light_capacity == 8
        snap = ctl.snapshot()
        assert snap.total_budget == 10
        assert snap.heavy.pool_size == 2
        assert snap.light.pool_size == 8

    @pytest.mark.parametrize(
        ("total", "ratio", "expected_heavy", "expected_light"),
        [
            (10, 0.5, 5, 5),
            (10, 0.0, 1, 9),  # floor: heavy >= 1
            (10, 1.0, 9, 1),  # floor: light >= 1
            (4, 0.25, 1, 3),
            (2, 0.5, 1, 1),  # min total
            (100, 0.2, 20, 80),
        ],
    )
    def test_initial_split_table(
        self, total: int, ratio: float, expected_heavy: int, expected_light: int
    ) -> None:
        ctl, _ = _build(total=total, ratio=ratio)
        assert ctl.heavy_capacity == expected_heavy
        assert ctl.light_capacity == expected_light

    def test_total_lt_two_clamps_to_two(self) -> None:
        # Edge case: total < 2 is meaningless for a dual-lane split.
        # We clamp to 2 so both lanes get the floor (1 each).
        ctl, _ = _build(total=1, ratio=0.5)
        assert ctl.snapshot().total_budget == 2


class TestAimdCoupling:
    def test_set_total_budget_preserves_ratio(self) -> None:
        ctl, _ = _build(total=10, ratio=0.4)  # heavy=4, light=6
        ctl.set_total_budget(20)
        # ratio 4/10 = 0.4 → new heavy = round(20*0.4) = 8
        assert ctl.heavy_capacity == 8
        assert ctl.light_capacity == 12

    def test_set_total_budget_floors_each_lane_at_one(self) -> None:
        ctl, _ = _build(total=100, ratio=0.99)
        # heavy ~99, light ~1. Shrink to total=2.
        ctl.set_total_budget(2)
        assert ctl.heavy_capacity == 1
        assert ctl.light_capacity == 1

    def test_set_total_budget_updates_stats_pool_size(self) -> None:
        ctl, _ = _build(total=10, ratio=0.2)
        ctl.set_total_budget(40)
        snap = ctl.snapshot()
        assert snap.heavy.pool_size + snap.light.pool_size == 40

    def test_set_total_budget_clamps_to_min_two(self) -> None:
        ctl, _ = _build(total=10, ratio=0.2)
        ctl.set_total_budget(0)
        snap = ctl.snapshot()
        assert snap.total_budget == 2


class TestAcquireReleaseDispatch:
    def test_acquire_then_release_balanced(self) -> None:
        ctl, _ = _build(total=4, ratio=0.5)  # heavy=2, light=2
        ctl.acquire("heavy")
        ctl.acquire("light")
        assert ctl.snapshot().heavy.busy == 1
        assert ctl.snapshot().light.busy == 1
        ctl.release("heavy")
        ctl.release("light")
        assert ctl.snapshot().heavy.busy == 0
        assert ctl.snapshot().light.busy == 0

    def test_acquire_blocks_at_lane_capacity(self) -> None:
        ctl, _ = _build(total=4, ratio=0.5)  # heavy=2, light=2
        ctl.acquire("heavy")
        ctl.acquire("heavy")
        # heavy is now saturated. A third acquire must block.
        blocked = threading.Event()
        released = threading.Event()

        def worker() -> None:
            ctl.acquire("heavy")
            blocked.set()
            ctl.release("heavy")
            released.set()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        # Give the worker time to attempt acquire.
        time.sleep(0.05)
        assert not blocked.is_set()
        # Free a heavy slot.
        ctl.release("heavy")
        assert blocked.wait(1.0)
        assert released.wait(1.0)
        ctl.release("heavy")

    def test_mark_completed_and_failed_routed_per_lane(self) -> None:
        ctl, _ = _build(total=4, ratio=0.5)
        ctl.mark_completed("heavy")
        ctl.mark_completed("heavy")
        ctl.mark_failed("light")
        snap = ctl.snapshot()
        assert snap.heavy.completed == 2
        assert snap.heavy.failed == 0
        assert snap.light.completed == 0
        assert snap.light.failed == 1


class TestQueueDepthTracking:
    def test_set_queue_depth_resets_last_active_when_positive(self) -> None:
        clock = [100.0]
        ctl, _ = _build(total=10, ratio=0.5, idle_threshold_s=5.0, clock_value=clock)
        ctl.set_queue_depth("heavy", 0)
        clock[0] = 110.0  # advance > idle threshold
        # heavy is idle for 10s → drain should fire on the next tick.
        ctl.rebalance_tick()
        # Heavy migrated all but 1 to light.
        assert ctl.heavy_capacity == 1
        assert ctl.light_capacity == 9


class TestDrainRebalance:
    def test_heavy_drain_migrates_to_light(self) -> None:
        clock = [0.0]
        ctl, _ = _build(total=10, ratio=0.5, idle_threshold_s=5.0, clock_value=clock)
        # Initial: heavy=5, light=5.
        # Heavy drains immediately, light stays active.
        ctl.set_queue_depth("light", 100)  # marks light active at t=0
        clock[0] = 6.0  # heavy idle for 6s, light just touched
        ctl.set_queue_depth("light", 99)  # touch again at t=6
        ctl.rebalance_tick()
        assert ctl.heavy_capacity == 1
        assert ctl.light_capacity == 9

    def test_light_drain_migrates_to_heavy(self) -> None:
        clock = [0.0]
        ctl, _ = _build(total=10, ratio=0.5, idle_threshold_s=5.0, clock_value=clock)
        ctl.set_queue_depth("heavy", 100)
        clock[0] = 6.0
        ctl.set_queue_depth("heavy", 99)
        ctl.rebalance_tick()
        assert ctl.light_capacity == 1
        assert ctl.heavy_capacity == 9

    def test_both_active_no_migration(self) -> None:
        clock = [0.0]
        ctl, _ = _build(total=10, ratio=0.5, idle_threshold_s=5.0, clock_value=clock)
        ctl.set_queue_depth("heavy", 5)
        ctl.set_queue_depth("light", 5)
        clock[0] = 4.0  # below threshold for both
        ctl.set_queue_depth("heavy", 5)
        ctl.set_queue_depth("light", 5)
        ctl.rebalance_tick()
        # No migration: both within idle threshold.
        assert ctl.heavy_capacity == 5
        assert ctl.light_capacity == 5

    def test_drain_already_minimal_does_not_migrate(self) -> None:
        clock = [0.0]
        ctl, _ = _build(total=10, ratio=0.5, idle_threshold_s=5.0, clock_value=clock)
        # Migrate heavy down to 1 (manual setup).
        ctl.set_queue_depth("light", 100)
        clock[0] = 6.0
        ctl.set_queue_depth("light", 99)
        ctl.rebalance_tick()
        assert ctl.heavy_capacity == 1
        # Run another tick — nothing should change.
        clock[0] = 12.0
        ctl.set_queue_depth("light", 50)
        ctl.rebalance_tick()
        assert ctl.heavy_capacity == 1
        assert ctl.light_capacity == 9


class TestRebalanceLogging:
    def test_emits_structured_lane_rebalance_event(self, caplog: pytest.LogCaptureFixture) -> None:
        clock = [0.0]
        logger = logging.getLogger("cmcourier.test.lanes")
        ctl, _ = _build(
            total=10,
            ratio=0.5,
            idle_threshold_s=5.0,
            clock_value=clock,
            logger=logger,
        )
        ctl.set_queue_depth("light", 100)
        clock[0] = 6.0
        ctl.set_queue_depth("light", 99)
        with caplog.at_level(logging.INFO, logger=logger.name):
            ctl.rebalance_tick()
        records = [r for r in caplog.records if r.name == logger.name]
        assert any(getattr(r, "event", None) == "lane_rebalance" for r in records)
        evt = next(r for r in records if getattr(r, "event", None) == "lane_rebalance")
        assert getattr(evt, "from") == "heavy"
        assert evt.to == "light"
        assert evt.previous_heavy == 5
        assert evt.previous_light == 5
        assert evt.new_heavy == 1
        assert evt.new_light == 9


class TestDaemonLifecycle:
    def test_start_stop_idempotent_and_clean(self) -> None:
        ctl, _ = _build(total=4, ratio=0.5, rebalance_interval_s=0.05)
        ctl.start()
        ctl.start()  # second call is a no-op
        time.sleep(0.15)  # allow at least 2 ticks
        ctl.stop()
        ctl.stop()  # idempotent
        # No assertion needed beyond "doesn't hang or raise".

    def test_snapshot_is_frozen(self) -> None:
        ctl, _ = _build(total=4, ratio=0.5)
        snap = ctl.snapshot()
        assert isinstance(snap, LaneSnapshot)
        with pytest.raises(AttributeError):
            snap.total_budget = 99  # type: ignore[misc]

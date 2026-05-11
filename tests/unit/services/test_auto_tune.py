"""Unit tests for the AIMD auto-tune controller (025 phase 2)."""

from __future__ import annotations

import pytest

from cmcourier.config.schema import AutoTuneConfig
from cmcourier.services.auto_tune import AutoTuneController, decide

pytestmark = pytest.mark.unit


def _cfg(**overrides: object) -> AutoTuneConfig:
    base = {
        "enabled": True,
        "min_threads": 2,
        "max_threads": 16,
        "target_p95_ms": 1000.0,
        "adjustment_interval_s": 30,
        "warmup_seconds": 60,
        "timeout_auto_adjust": True,
        "min_timeout_s": 30,
        "max_timeout_s": 600,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return AutoTuneConfig(**base)  # type: ignore[arg-type]


class TestDecide:
    def test_warmup_returns_noop(self) -> None:
        cfg = _cfg(warmup_seconds=60)
        d = decide(
            cfg,
            observed_p95_ms=800.0,  # below target, would trigger AI
            elapsed_s=10.0,  # still in warmup
            current_workers=4,
            current_timeout_s=300.0,
        )
        assert d.action == "warmup"
        assert d.workers == 4
        assert d.timeout_s == 300.0

    def test_additive_increase_under_target(self) -> None:
        cfg = _cfg()
        d = decide(
            cfg,
            observed_p95_ms=500.0,  # < 0.8 * 1000 = 800
            elapsed_s=120.0,
            current_workers=4,
            current_timeout_s=300.0,
        )
        assert d.action == "+1"
        assert d.workers == 5
        # Timeout tightens on stable/AI: halve toward min.
        assert d.timeout_s == max(300.0 / 2, cfg.min_timeout_s)

    def test_additive_increase_caps_at_max_threads(self) -> None:
        cfg = _cfg(max_threads=8)
        d = decide(
            cfg,
            observed_p95_ms=200.0,
            elapsed_s=120.0,
            current_workers=8,  # already at cap
            current_timeout_s=300.0,
        )
        assert d.action == "+1"
        assert d.workers == 8  # capped, no change

    def test_multiplicative_decrease_over_target(self) -> None:
        cfg = _cfg()
        d = decide(
            cfg,
            observed_p95_ms=2000.0,  # > 1.2 * 1000 = 1200
            elapsed_s=120.0,
            current_workers=8,
            current_timeout_s=300.0,
        )
        assert d.action == "halve"
        assert d.workers == 4  # 8 // 2
        # Timeout DOUBLES on MD (give each call more headroom).
        assert d.timeout_s == min(300.0 * 2, cfg.max_timeout_s)

    def test_multiplicative_decrease_floors_at_min_threads(self) -> None:
        cfg = _cfg(min_threads=2)
        d = decide(
            cfg,
            observed_p95_ms=5000.0,
            elapsed_s=120.0,
            current_workers=2,  # already at floor
            current_timeout_s=300.0,
        )
        assert d.action == "halve"
        assert d.workers == 2  # floored, no change

    def test_noop_in_target_band(self) -> None:
        cfg = _cfg()
        d = decide(
            cfg,
            observed_p95_ms=1000.0,  # exactly target
            elapsed_s=120.0,
            current_workers=4,
            current_timeout_s=300.0,
        )
        assert d.action == "noop"
        assert d.workers == 4
        # Timeout still tightens toward min on stable.
        assert d.timeout_s == max(300.0 / 2, cfg.min_timeout_s)

    def test_timeout_auto_adjust_disabled(self) -> None:
        cfg = _cfg(timeout_auto_adjust=False)
        d = decide(
            cfg,
            observed_p95_ms=2000.0,  # MD trigger
            elapsed_s=120.0,
            current_workers=8,
            current_timeout_s=300.0,
        )
        assert d.action == "halve"
        # Timeout unchanged when auto-adjust off.
        assert d.timeout_s == 300.0

    def test_timeout_caps_at_max(self) -> None:
        cfg = _cfg(max_timeout_s=400.0)
        d = decide(
            cfg,
            observed_p95_ms=2000.0,
            elapsed_s=120.0,
            current_workers=8,
            current_timeout_s=300.0,
        )
        assert d.action == "halve"
        # 300 * 2 = 600 > max 400 → caps at 400.
        assert d.timeout_s == 400.0


class TestAutoTuneController:
    def test_disabled_controller_does_not_start(self) -> None:
        cfg = AutoTuneConfig(enabled=False)
        resize_calls: list[int] = []
        timeout_calls: list[float] = []
        controller = AutoTuneController(
            config=cfg,
            p95_provider=lambda: 0.0,
            current_workers_provider=lambda: 4,
            current_timeout_provider=lambda: 300.0,
            on_pool_resize=lambda n: resize_calls.append(n),
            on_timeout_change=lambda t: timeout_calls.append(t),
        )
        controller.start()
        controller.stop(timeout=1.0)
        assert resize_calls == []
        assert timeout_calls == []

    def test_enabled_controller_starts_and_stops_cleanly(self) -> None:
        cfg = AutoTuneConfig(
            enabled=True,
            adjustment_interval_s=1,
            warmup_seconds=0,
            min_threads=1,
            max_threads=10,
        )
        controller = AutoTuneController(
            config=cfg,
            p95_provider=lambda: 0.0,
            current_workers_provider=lambda: 4,
            current_timeout_provider=lambda: 300.0,
            on_pool_resize=lambda _n: None,
            on_timeout_change=lambda _t: None,
        )
        controller.start()
        controller.stop(timeout=2.0)
        # No assertion on calls — we just want clean start/stop without
        # hanging the test runner.

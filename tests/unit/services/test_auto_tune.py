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
            sample_count=100,
            elapsed_s=10.0,  # still in warmup
            current_workers=4,
            current_timeout_s=300.0,
        )
        assert d.action == "warmup"
        assert d.workers == 4
        assert d.timeout_s == 300.0

    def test_growth_under_target_uses_multiplicative_floor_plus_one(self) -> None:
        # 068: growth is ``max(current+1, ceil(current * growth_factor))``.
        # current=4 with default 1.25 → max(5, ceil(5.0)) = 5. The +1 floor
        # matches the multiplicative result here.
        cfg = _cfg()
        d = decide(
            cfg,
            observed_p95_ms=500.0,  # < 0.8 * 1000 = 800
            sample_count=100,
            elapsed_s=120.0,
            current_workers=4,
            current_timeout_s=300.0,
        )
        assert d.action == "+N"
        assert d.workers == 5
        # Timeout tightens on stable/grow: halve toward min.
        assert d.timeout_s == max(300.0 / 2, cfg.min_timeout_s)

    def test_growth_uses_multiplicative_factor_when_above_plus_one(self) -> None:
        # 068: current=20, growth_factor=1.25 → ceil(25.0) = 25; max(21, 25) = 25.
        cfg = _cfg(max_threads=50)
        d = decide(
            cfg,
            observed_p95_ms=200.0,
            sample_count=100,
            elapsed_s=120.0,
            current_workers=20,
            current_timeout_s=300.0,
        )
        assert d.action == "+N"
        assert d.workers == 25

    def test_growth_caps_at_max_threads(self) -> None:
        cfg = _cfg(max_threads=8)
        d = decide(
            cfg,
            observed_p95_ms=200.0,
            sample_count=100,
            elapsed_s=120.0,
            current_workers=8,  # already at cap
            current_timeout_s=300.0,
        )
        assert d.action == "+N"
        assert d.workers == 8  # capped, no change

    def test_halve_over_threshold_uses_halve_factor(self) -> None:
        # 068: halve fires when p95 > halve_threshold_ratio * target_p95_ms.
        # Default ratio=1.5 → upper=1500. Halve uses ceil(current*halve_factor).
        # current=8, halve_factor=0.75 → ceil(6.0)=6.
        cfg = _cfg()
        d = decide(
            cfg,
            observed_p95_ms=2000.0,  # > 1.5 * 1000 = 1500
            sample_count=100,
            elapsed_s=120.0,
            current_workers=8,
            current_timeout_s=300.0,
        )
        assert d.action == "halve"
        assert d.workers == 6  # ceil(8 * 0.75)
        # Timeout DOUBLES on halve (give each call more headroom).
        assert d.timeout_s == min(300.0 * 2, cfg.max_timeout_s)

    def test_halve_threshold_ratio_honors_the_knob(self) -> None:
        # 068: ratio=1.2 (pre-068 hardcoded) halves at p95=1300 (above 1200);
        # ratio=1.5 (new default) keeps noop at that p95.
        d_tight = decide(
            _cfg(halve_threshold_ratio=1.2),
            observed_p95_ms=1300.0,
            sample_count=100,
            elapsed_s=120.0,
            current_workers=8,
            current_timeout_s=300.0,
        )
        d_loose = decide(
            _cfg(halve_threshold_ratio=1.5),
            observed_p95_ms=1300.0,
            sample_count=100,
            elapsed_s=120.0,
            current_workers=8,
            current_timeout_s=300.0,
        )
        assert d_tight.action == "halve"
        assert d_loose.action == "noop"

    def test_halve_floors_at_min_threads(self) -> None:
        cfg = _cfg(min_threads=2)
        d = decide(
            cfg,
            observed_p95_ms=5000.0,
            sample_count=100,
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
            sample_count=100,
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
            observed_p95_ms=2000.0,  # > 1.5 × 1000 = halve trigger
            sample_count=100,
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
            sample_count=100,
            elapsed_s=120.0,
            current_workers=8,
            current_timeout_s=300.0,
        )
        assert d.action == "halve"
        # 300 * 2 = 600 > max 400 → caps at 400.
        assert d.timeout_s == 400.0


class TestMinSamplesGuard061:
    """061 — the AIMD halved on the first chunk because nearest-rank p95
    with few samples is dominated by a single cold-connection outlier.
    ``decide`` now short-circuits to ``insufficient_data`` when the
    sample count is below ``config.min_samples``.
    """

    def test_insufficient_data_when_below_min_samples(self) -> None:
        # The named regression: 5 uploads, one of which paid the TCP+TLS
        # handshake (12 s = 12000 ms) → nearest-rank p95 = 12000. With
        # target 6000, that would have halved pre-061. Now it bails.
        cfg = _cfg(target_p95_ms=6000.0, min_samples=20)
        d = decide(
            cfg,
            observed_p95_ms=12000.0,
            sample_count=5,  # below default min_samples=20
            elapsed_s=120.0,  # past warmup
            current_workers=6,
            current_timeout_s=120.0,
        )
        assert d.action == "insufficient_data"
        assert d.workers == 6  # unchanged
        assert d.timeout_s == 120.0  # unchanged

    def test_zero_samples_short_circuits(self) -> None:
        cfg = _cfg(min_samples=20)
        d = decide(
            cfg,
            observed_p95_ms=99999.0,  # would scream halve
            sample_count=0,
            elapsed_s=120.0,
            current_workers=8,
            current_timeout_s=300.0,
        )
        assert d.action == "insufficient_data"
        assert d.workers == 8

    def test_guard_releases_at_floor(self) -> None:
        # The guard is a floor — at exactly min_samples the real decision runs.
        # 068: target=6000, ratio=1.5 → upper=9000. p95=12000 > 9000 → halve.
        # current=6, halve_factor=0.75 → ceil(4.5)=5.
        cfg = _cfg(target_p95_ms=6000.0, min_samples=20)
        d = decide(
            cfg,
            observed_p95_ms=12000.0,
            sample_count=20,
            elapsed_s=120.0,
            current_workers=6,
            current_timeout_s=120.0,
        )
        assert d.action == "halve"
        assert d.workers == 5

    def test_warmup_takes_precedence_over_min_samples(self) -> None:
        # During warmup we never act, regardless of sample count.
        cfg = _cfg(warmup_seconds=60, min_samples=20)
        d = decide(
            cfg,
            observed_p95_ms=12000.0,
            sample_count=100,  # plenty of samples
            elapsed_s=10.0,  # in warmup
            current_workers=4,
            current_timeout_s=300.0,
        )
        assert d.action == "warmup"


class TestAutoTuneController:
    def test_disabled_controller_does_not_start(self) -> None:
        cfg = AutoTuneConfig(enabled=False)
        resize_calls: list[int] = []
        timeout_calls: list[float] = []
        controller = AutoTuneController(
            config=cfg,
            p95_provider=lambda: (0.0, 100),
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
            p95_provider=lambda: (0.0, 100),
            current_workers_provider=lambda: 4,
            current_timeout_provider=lambda: 300.0,
            on_pool_resize=lambda _n: None,
            on_timeout_change=lambda _t: None,
        )
        controller.start()
        controller.stop(timeout=2.0)
        # No assertion on calls — we just want clean start/stop without
        # hanging the test runner.


class TestSetP95Provider043:
    """043 — controller's p95 source can be swapped after construction so
    the multi-batch orchestrator can point it at the upload-active
    recorder instead of the pipeline's own (which receives nothing in
    multi-batch mode)."""

    def test_set_p95_provider_replaces_attribute(self) -> None:
        cfg = AutoTuneConfig(
            enabled=True,
            adjustment_interval_s=10,
            warmup_seconds=0,
            min_threads=1,
            max_threads=16,
        )
        ctl = AutoTuneController(
            config=cfg,
            p95_provider=lambda: (100.0, 100),
            current_workers_provider=lambda: 4,
            current_timeout_provider=lambda: 60.0,
            on_pool_resize=lambda _n: None,
            on_timeout_change=lambda _t: None,
        )
        # Pre-swap: read the original provider's return value.
        assert ctl._p95_provider() == (100.0, 100)  # noqa: SLF001
        ctl.set_p95_provider(lambda: (7000.0, 100))
        # Post-swap: the new provider is in place.
        assert ctl._p95_provider() == (7000.0, 100)  # noqa: SLF001

    def test_swap_takes_effect_on_next_tick(self) -> None:
        """Drive _tick manually with the swapped provider and assert the
        emitted decision reflects the new observed_p95."""
        cfg = AutoTuneConfig(
            enabled=True,
            adjustment_interval_s=15,
            warmup_seconds=0,
            min_threads=2,
            max_threads=16,
            target_p95_ms=3000.0,
            timeout_auto_adjust=False,
        )
        ctl = AutoTuneController(
            config=cfg,
            p95_provider=lambda: (100.0, 100),  # well below target → would say +1
            current_workers_provider=lambda: 4,
            current_timeout_provider=lambda: 60.0,
            on_pool_resize=lambda _n: None,
            on_timeout_change=lambda _t: None,
        )
        # Swap to a provider that reports far ABOVE target → should drive
        # a multiplicative-decrease decision on the next tick.
        ctl.set_p95_provider(lambda: (9000.0, 100))
        # Direct tick (no thread) — simulates one elapsed cycle past warmup.
        ctl._tick(elapsed_s=20.0)  # noqa: SLF001
        # _last_decision now reflects the swapped provider's observation.
        d = ctl.last_decision
        assert d is not None
        # AIMD: above-target observation triggers multiplicative decrease,
        # which the controller emits as ``action="halve"``.
        assert d.action == "halve", f"expected halve, got {d.action!r}"
        assert d.workers < 4, "workers must drop below the 4 starting count"


class TestControllerGatesInsufficientData061:
    def test_tick_with_few_samples_does_not_promote_to_last_decision(self) -> None:
        # 061 regression: when the provider reports too few samples, the
        # controller must NOT update `last_decision` (same treatment as
        # warmup) and must NOT call the resize / timeout callbacks. This
        # is what stops the first-chunk halve.
        cfg = AutoTuneConfig(
            enabled=True,
            adjustment_interval_s=15,
            warmup_seconds=0,
            min_threads=2,
            max_threads=16,
            target_p95_ms=6000.0,
            min_samples=20,
            timeout_auto_adjust=False,
        )
        resize_calls: list[int] = []
        timeout_calls: list[float] = []
        ctl = AutoTuneController(
            config=cfg,
            p95_provider=lambda: (12000.0, 5),  # outlier + few samples
            current_workers_provider=lambda: 6,
            current_timeout_provider=lambda: 120.0,
            on_pool_resize=lambda n: resize_calls.append(n),
            on_timeout_change=lambda t: timeout_calls.append(t),
        )
        ctl._tick(elapsed_s=20.0)  # noqa: SLF001 — past warmup, but few samples
        assert ctl.last_decision is None, "insufficient_data must not promote"
        assert resize_calls == [], "pool must not resize on insufficient_data"
        assert timeout_calls == [], "timeout must not change on insufficient_data"

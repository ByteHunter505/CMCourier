"""Tests unitarios para el controlador `AIMD` de auto-tune (025 fase 2)."""

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
            observed_p95_ms=800.0,  # debajo del target, dispararía AI
            sample_count=100,
            elapsed_s=10.0,  # todavía en warmup
            current_workers=4,
            current_timeout_s=300.0,
        )
        assert d.action == "warmup"
        assert d.workers == 4
        assert d.timeout_s == 300.0

    def test_growth_under_target_uses_multiplicative_floor_plus_one(self) -> None:
        # 068: el crecimiento es ``max(current+1, ceil(current * growth_factor))``.
        # `current=4` con default 1.25 → `max(5, ceil(5.0)) = 5`. El piso
        # `+1` coincide con el resultado multiplicativo aquí.
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
        # El `timeout` se tensa en `stable/grow`: se reduce a la mitad hacia el min.
        assert d.timeout_s == max(300.0 / 2, cfg.min_timeout_s)

    def test_growth_uses_multiplicative_factor_when_above_plus_one(self) -> None:
        # 068: `current=20`, `growth_factor=1.25` → `ceil(25.0) = 25`;
        # `max(21, 25) = 25`.
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
            current_workers=8,  # ya está en el tope
            current_timeout_s=300.0,
        )
        assert d.action == "+N"
        assert d.workers == 8  # topeado, sin cambio

    def test_halve_over_threshold_uses_halve_factor(self) -> None:
        # 068: `halve` dispara cuando `p95 > halve_threshold_ratio * target_p95_ms`.
        # Ratio default=1.5 → upper=1500. `halve` usa
        # `ceil(current*halve_factor)`. `current=8`, `halve_factor=0.75`
        # → `ceil(6.0)=6`.
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
        # El `timeout` DUPLICA en `halve` (le da a cada llamada más headroom).
        assert d.timeout_s == min(300.0 * 2, cfg.max_timeout_s)

    def test_halve_threshold_ratio_honors_the_knob(self) -> None:
        # 068: `ratio=1.2` (hardcodeado pre-068) `halve`a en `p95=1300`
        # (sobre 1200); `ratio=1.5` (nuevo default) mantiene `noop` en
        # ese `p95`.
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
            current_workers=2,  # ya está en el piso
            current_timeout_s=300.0,
        )
        assert d.action == "halve"
        assert d.workers == 2  # `floored`, sin cambio

    def test_noop_in_target_band(self) -> None:
        cfg = _cfg()
        d = decide(
            cfg,
            observed_p95_ms=1000.0,  # exactamente el target
            sample_count=100,
            elapsed_s=120.0,
            current_workers=4,
            current_timeout_s=300.0,
        )
        assert d.action == "noop"
        assert d.workers == 4
        # El `timeout` igual se tensa hacia el min en `stable`.
        assert d.timeout_s == max(300.0 / 2, cfg.min_timeout_s)

    def test_timeout_auto_adjust_disabled(self) -> None:
        cfg = _cfg(timeout_auto_adjust=False)
        d = decide(
            cfg,
            observed_p95_ms=2000.0,  # > 1.5 × 1000 = dispara `halve`
            sample_count=100,
            elapsed_s=120.0,
            current_workers=8,
            current_timeout_s=300.0,
        )
        assert d.action == "halve"
        # `Timeout` sin cambios cuando `auto-adjust` está apagado.
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
        # 300 * 2 = 600 > max 400 → topea en 400.
        assert d.timeout_s == 400.0


class TestMinSamplesGuard061:
    """061 — el `AIMD` `halve`aba en el primer `chunk` porque el `p95`
    `nearest-rank` con pocos `sample`s está dominado por un único
    `outlier` de conexión fría. ``decide`` ahora hace `short-circuit`
    a ``insufficient_data`` cuando el conteo de `sample`s está por
    debajo de ``config.min_samples``.
    """

    def test_insufficient_data_when_below_min_samples(self) -> None:
        # La regresión bautizada: 5 uploads, uno de los cuales pagó el
        # `handshake` `TCP+TLS` (12 s = 12000 ms) → `p95` `nearest-rank`
        # = 12000. Con target 6000, eso hubiera `halve`ado pre-061.
        # Ahora se baja.
        cfg = _cfg(target_p95_ms=6000.0, min_samples=20)
        d = decide(
            cfg,
            observed_p95_ms=12000.0,
            sample_count=5,  # debajo del default `min_samples=20`
            elapsed_s=120.0,  # pasado el warmup
            current_workers=6,
            current_timeout_s=120.0,
        )
        assert d.action == "insufficient_data"
        assert d.workers == 6  # sin cambios
        assert d.timeout_s == 120.0  # sin cambios

    def test_zero_samples_short_circuits(self) -> None:
        cfg = _cfg(min_samples=20)
        d = decide(
            cfg,
            observed_p95_ms=99999.0,  # gritaría `halve`
            sample_count=0,
            elapsed_s=120.0,
            current_workers=8,
            current_timeout_s=300.0,
        )
        assert d.action == "insufficient_data"
        assert d.workers == 8

    def test_guard_releases_at_floor(self) -> None:
        # La guarda es un piso — exactamente en `min_samples` corre la
        # decisión real. 068: `target=6000`, `ratio=1.5` → `upper=9000`.
        # `p95=12000 > 9000` → `halve`. `current=6`, `halve_factor=0.75`
        # → `ceil(4.5)=5`.
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
        # Durante el warmup nunca actuamos, independiente del conteo de samples.
        cfg = _cfg(warmup_seconds=60, min_samples=20)
        d = decide(
            cfg,
            observed_p95_ms=12000.0,
            sample_count=100,  # samples de sobra
            elapsed_s=10.0,  # en warmup
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
        # Sin aserciones sobre llamadas — solo queremos `start/stop`
        # limpio sin colgar el runner de tests.


class TestSetP95Provider043:
    """043 — la fuente de `p95` del controlador puede intercambiarse
    después de la construcción para que el orquestador `multi-batch`
    pueda apuntarla al `recorder` activo de upload en vez del propio
    del `pipeline` (que no recibe nada en modo `multi-batch`)."""

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
        # Pre-`swap`: lee el valor de retorno del proveedor original.
        assert ctl._p95_provider() == (100.0, 100)  # noqa: SLF001
        ctl.set_p95_provider(lambda: (7000.0, 100))
        # Post-`swap`: el nuevo proveedor está en su lugar.
        assert ctl._p95_provider() == (7000.0, 100)  # noqa: SLF001

    def test_swap_takes_effect_on_next_tick(self) -> None:
        """Maneja `_tick` manualmente con el proveedor `swap`eado y
        asevera que la decisión emitida refleje el nuevo `observed_p95`."""
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
            p95_provider=lambda: (100.0, 100),  # bien debajo del target → diría +1
            current_workers_provider=lambda: 4,
            current_timeout_provider=lambda: 60.0,
            on_pool_resize=lambda _n: None,
            on_timeout_change=lambda _t: None,
        )
        # Cambia al proveedor que reporta muy POR ENCIMA del target →
        # debería gatillar una decisión de decrecimiento multiplicativo
        # en el próximo `tick`.
        ctl.set_p95_provider(lambda: (9000.0, 100))
        # `Tick` directo (sin `thread`) — simula un ciclo transcurrido
        # pasado el warmup.
        ctl._tick(elapsed_s=20.0)  # noqa: SLF001
        # `_last_decision` ahora refleja la observación del proveedor
        # `swap`eado.
        d = ctl.last_decision
        assert d is not None
        # `AIMD`: observación por encima del target dispara decrecimiento
        # multiplicativo, que el controlador emite como
        # ``action="halve"``.
        assert d.action == "halve", f"expected halve, got {d.action!r}"
        assert d.workers < 4, "los `worker`s deben caer por debajo del conteo inicial de 4"


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

"""Controlador `AIMD` de auto-tune para el `worker pool` de S5 (025 fase 2).

Algoritmo (recalibrado para cargas de archivos `heavy` en 068):

* **MI** (incremento multiplicativo): cuando la latencia p95 observada
  cae por debajo del 80 % del target, los workers crecen a
  ``max(current + 1, ceil(current * growth_factor))`` y el timeout
  de request se ajusta hacia abajo. El `growth_factor` por defecto
  es 1.25 (+25 % por `tick`, nunca menos de +1). Antes de 068
  siempre era `+1`.
* **Soft halve**: cuando el p95 observado sube por encima de
  ``halve_threshold_ratio × target`` (por defecto 1.5×, antes de 068
  era 1.2×), los workers se reducen a
  ``max(min_threads, ceil(current * halve_factor))`` (por defecto
  0.75, antes de 068 era 0.5). Menos pánico ante un único `tick`
  malo.
* **Noop**: dentro de la banda inferior/superior, mantiene la
  cantidad de workers y solo ajusta el timeout.
* **Warmup**: durante ``warmup_seconds`` posteriores al inicio, no
  ajusta nada.

El controlador corre como `thread` en segundo plano que despierta
con cadencia ``adjustment_interval_s``, lee el estado actual a
través de los `callbacks` provider, computa la próxima
:class:`Decision` y la aplica vía los `callbacks` ``on_pool_resize``
y ``on_timeout_change``. El orchestrator es dueño de esos
`callbacks` (de modo que el controlador no depende directamente del
`pool` ni del uploader).
"""

from __future__ import annotations

__all__ = ["AutoTuneController", "Decision", "decide"]

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from cmcourier.config.schema import AutoTuneConfig

_log = logging.getLogger(__name__)

_AUTO_TUNE_LOG = "auto_tune_decision"


@dataclass(frozen=True, slots=True)
class Decision:
    """Ajuste resuelto en una vuelta del `AIMD`."""

    action: str  # "+N" | "halve" | "noop" | "warmup" | "insufficient_data"
    workers: int
    timeout_s: float


def decide(
    config: AutoTuneConfig,
    *,
    observed_p95_ms: float,
    sample_count: int,
    elapsed_s: float,
    current_workers: int,
    current_timeout_s: float,
) -> Decision:
    """Decisión `AIMD` como función pura (unit-testable de forma aislada).

    061: ``sample_count`` gatea la decisión. Cuando el recorder tiene
    menos de ``config.min_samples`` duraciones de S5, el p95 por
    `nearest-rank` queda dominado por un único sample grande (un
    outlier por conexión fría del primer `chunk`). La acción resultante
    es ``insufficient_data`` y tanto workers como timeout permanecen sin
    cambios.
    """
    if elapsed_s < config.warmup_seconds:
        return Decision(action="warmup", workers=current_workers, timeout_s=current_timeout_s)
    if sample_count < config.min_samples:
        return Decision(
            action="insufficient_data",
            workers=current_workers,
            timeout_s=current_timeout_s,
        )

    lower = 0.8 * config.target_p95_ms
    upper = config.halve_threshold_ratio * config.target_p95_ms

    if observed_p95_ms > upper:
        # 068: soft halve. Antes de 068 era ``current // 2`` (caída del
        # 50 % en un solo `tick`); ahora ``ceil(current * halve_factor)``
        # (por defecto 0.75 → caída del 25 %). La recuperación tras un
        # halve por falso positivo resulta mucho más barata, lo que
        # importa porque la varianza natural del p95 en archivos `heavy`
        # dispara el threshold seguido.
        halved = math.ceil(current_workers * config.halve_factor)
        new_workers = max(halved, config.min_threads)
        new_timeout = (
            min(current_timeout_s * 2, float(config.max_timeout_s))
            if config.timeout_auto_adjust
            else current_timeout_s
        )
        return Decision(action="halve", workers=new_workers, timeout_s=new_timeout)

    new_timeout = (
        max(current_timeout_s / 2, float(config.min_timeout_s))
        if config.timeout_auto_adjust
        else current_timeout_s
    )
    if observed_p95_ms < lower:
        # 068: crecimiento multiplicativo con un `floor` de ``+1``. Antes
        # de 068 siempre era ``+1`` por `tick`: a 15 s por `tick`, ir
        # de 6 a 50 workers llevaba 44 ticks = 11 min. El factor por
        # defecto de 1.25× alcanza 50 en ~10 `ticks` (~2.5 min) partiendo
        # de 6. El `floor` ``+1`` preserva el progreso cuando
        # ``current_workers`` es chico (1.25 × 2 = 2 sin el `floor`).
        grown = math.ceil(current_workers * config.growth_factor)
        new_workers = min(max(current_workers + 1, grown), config.max_threads)
        return Decision(action="+N", workers=new_workers, timeout_s=new_timeout)
    return Decision(action="noop", workers=current_workers, timeout_s=new_timeout)


class AutoTuneController:
    """Controlador `AIMD` en segundo plano para el `worker pool` de S5.

    Lee el estado actual a través de `callbacks` provider y aplica
    decisiones vía los `callbacks` de resize y timeout. El arranque y
    la detención son no bloqueantes; el `thread` se une limpiamente al
    detenerse.

    Cuando ``config.enabled=False``, :meth:`start` es un no-op y no se
    levanta ningún `thread`.
    """

    def __init__(
        self,
        *,
        config: AutoTuneConfig,
        p95_provider: Callable[[], tuple[float, int]],
        current_workers_provider: Callable[[], int],
        current_timeout_provider: Callable[[], float],
        on_pool_resize: Callable[[int], None],
        on_timeout_change: Callable[[float], None],
    ) -> None:
        self._config = config
        self._p95_provider = p95_provider
        self._current_workers_provider = current_workers_provider
        self._current_timeout_provider = current_timeout_provider
        self._on_pool_resize = on_pool_resize
        self._on_timeout_change = on_timeout_change
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_monotonic = 0.0
        # 025 fase 3: la TUI lee ``last_decision`` y
        # ``seconds_to_next_tick`` para renderizar la línea "last move"
        # y el countdown "next: in Ns".
        self._last_decision: Decision | None = None
        self._last_decision_monotonic: float | None = None
        self._last_tick_monotonic: float | None = None
        self._state_lock = threading.Lock()

    def start(self) -> None:
        if not self._config.enabled:
            return
        self._start_monotonic = time.monotonic()
        with self._state_lock:
            self._last_tick_monotonic = self._start_monotonic
        self._thread = threading.Thread(
            target=self._loop,
            name="cmcourier-auto-tune",
            daemon=True,
        )
        self._thread.start()

    def set_p95_provider(self, provider: Callable[[], tuple[float, int]]) -> None:
        """043: reemplaza la fuente de observación del p95 después de
        construido el controlador.

        061: el provider ahora devuelve ``(p95_ms, sample_count)`` para
        que la decisión pueda gatearse según la cantidad mínima de
        samples.

        El controlador lee ``self._p95_provider`` una vez por `tick`,
        de modo que el reemplazo toma efecto en el próximo borde de
        ``adjustment_interval_s`` sin necesidad de reiniciar el
        `thread`. Lo usa el orchestrator multi-`batch` para apuntar el
        controlador al recorder activo de subida (en modo single-`batch`
        se mantiene el valor por defecto fijado en el constructor).
        """
        with self._state_lock:
            self._p95_provider = provider

    # ------------------------------------------------------ accesos para la TUI

    @property
    def last_decision(self) -> Decision | None:
        with self._state_lock:
            return self._last_decision

    @property
    def seconds_since_last_decision(self) -> float | None:
        with self._state_lock:
            if self._last_decision_monotonic is None:
                return None
            return time.monotonic() - self._last_decision_monotonic

    @property
    def seconds_to_next_tick(self) -> float:
        with self._state_lock:
            if self._last_tick_monotonic is None:
                return float(self._config.adjustment_interval_s)
            elapsed = time.monotonic() - self._last_tick_monotonic
            return max(0.0, self._config.adjustment_interval_s - elapsed)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(timeout=self._config.adjustment_interval_s):
            try:
                self._tick(time.monotonic() - self._start_monotonic)
            except Exception:  # noqa: BLE001 — nunca dejar caer al controlador
                _log.exception("auto-tune controller tick failed")

    def _tick(self, elapsed_s: float) -> None:
        current_workers = self._current_workers_provider()
        current_timeout = self._current_timeout_provider()
        observed_p95, sample_count = self._p95_provider()
        now = time.monotonic()
        d = decide(
            self._config,
            observed_p95_ms=observed_p95,
            sample_count=sample_count,
            elapsed_s=elapsed_s,
            current_workers=current_workers,
            current_timeout_s=current_timeout,
        )
        # 061: ``insufficient_data`` se gatea igual que ``warmup``: la
        # observación no es confiable, por lo que no se promueve a
        # ``last_decision`` (que la TUI muestra como "last move").
        gated = d.action in ("warmup", "insufficient_data")
        with self._state_lock:
            self._last_tick_monotonic = now
            if not gated:
                self._last_decision = d
                self._last_decision_monotonic = now
        _log.info(
            _AUTO_TUNE_LOG,
            extra={
                "action": d.action,
                "p95_observed_ms": round(observed_p95, 3),
                "p95_sample_count": sample_count,
                "p95_target_ms": self._config.target_p95_ms,
                "workers_before": current_workers,
                "workers_after": d.workers,
                "timeout_before_s": current_timeout,
                "timeout_after_s": d.timeout_s,
            },
        )
        if d.workers != current_workers:
            self._on_pool_resize(d.workers)
        if d.timeout_s != current_timeout:
            self._on_timeout_change(d.timeout_s)

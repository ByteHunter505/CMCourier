"""AIMD auto-tune controller for the S5 worker pool (025 phase 2).

Algorithm (REBIRTH §12, mirrored from the legacy implementation):

* **AI** (additive increase) — when observed p95 latency falls below
  80 % of the target, add one worker and tighten the request
  timeout (halve toward ``min_timeout_s``). System is healthy;
  give it more concurrency, less per-call slack.
* **MD** (multiplicative decrease) — when observed p95 climbs above
  120 % of the target, halve the worker count (floor at
  ``min_threads``) and double the timeout (cap at
  ``max_timeout_s``). System is under pressure; back off
  concurrency, give each call more headroom.
* **Noop** — within the 80/120 % band, keep the worker count and
  tighten the timeout (same as AI).
* **Warmup** — during ``warmup_seconds`` after start, never adjust.

The controller runs as a background thread that wakes on
``adjustment_interval_s`` cadence, reads the current state through
provider callbacks, computes the next :class:`Decision`, and
applies it via ``on_pool_resize`` and ``on_timeout_change``
callbacks. The orchestrator owns those callbacks (so the
controller has no direct dependency on the pool or the uploader).
"""

from __future__ import annotations

__all__ = ["AutoTuneController", "Decision", "decide"]

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from cmcourier.config.schema import AutoTuneConfig

_log = logging.getLogger(__name__)

_AUTO_TUNE_LOG = "auto_tune_decision"


@dataclass(frozen=True, slots=True)
class Decision:
    """One AIMD round's resolved adjustment."""

    action: str  # "+1" | "halve" | "noop" | "warmup"
    workers: int
    timeout_s: float


def decide(
    config: AutoTuneConfig,
    *,
    observed_p95_ms: float,
    elapsed_s: float,
    current_workers: int,
    current_timeout_s: float,
) -> Decision:
    """Pure-function AIMD decision (unit-testable in isolation)."""
    if elapsed_s < config.warmup_seconds:
        return Decision(action="warmup", workers=current_workers, timeout_s=current_timeout_s)

    lower = 0.8 * config.target_p95_ms
    upper = 1.2 * config.target_p95_ms

    if observed_p95_ms > upper:
        new_workers = max(current_workers // 2, config.min_threads)
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
        new_workers = min(current_workers + 1, config.max_threads)
        return Decision(action="+1", workers=new_workers, timeout_s=new_timeout)
    return Decision(action="noop", workers=current_workers, timeout_s=new_timeout)


class AutoTuneController:
    """Background AIMD controller for the S5 worker pool.

    Reads current state through provider callbacks and applies
    decisions via the resize / timeout callbacks. Non-blocking
    start/stop; cleanly joins on stop.

    When ``config.enabled=False``, :meth:`start` is a no-op and no
    thread is spawned.
    """

    def __init__(
        self,
        *,
        config: AutoTuneConfig,
        p95_provider: Callable[[], float],
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
        # 025 phase 3: TUI reads ``last_decision`` and ``seconds_to_next_tick``
        # to render the "last move" line + the "next: in Ns" countdown.
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

    def set_p95_provider(self, provider: Callable[[], float]) -> None:
        """043 — swap the p95 observation source after construction.

        The controller reads ``self._p95_provider`` once per tick, so a
        replacement takes effect on the next ``adjustment_interval_s``
        boundary without restarting the thread. Used by the multi-batch
        orchestrator to point the controller at the upload-active
        recorder (single-batch mode keeps the constructor-time default).
        """
        with self._state_lock:
            self._p95_provider = provider

    # ------------------------------------------------------ TUI accessors

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
            except Exception:  # noqa: BLE001 — never crash the controller
                _log.exception("auto-tune controller tick failed")

    def _tick(self, elapsed_s: float) -> None:
        current_workers = self._current_workers_provider()
        current_timeout = self._current_timeout_provider()
        observed_p95 = self._p95_provider()
        now = time.monotonic()
        d = decide(
            self._config,
            observed_p95_ms=observed_p95,
            elapsed_s=elapsed_s,
            current_workers=current_workers,
            current_timeout_s=current_timeout,
        )
        with self._state_lock:
            self._last_tick_monotonic = now
            if d.action != "warmup":
                self._last_decision = d
                self._last_decision_monotonic = now
        _log.info(
            _AUTO_TUNE_LOG,
            extra={
                "action": d.action,
                "p95_observed_ms": round(observed_p95, 3),
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

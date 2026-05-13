"""Install loggers, handlers, formatter, and PII filter.

Idempotent: each call removes existing handlers before installing
fresh ones (tests re-invoke between cases without state leak).

Logger hierarchy:

* ``cmcourier`` — app events. stderr + rotating file handler.
* ``cmcourier.metrics.pipeline`` — batch summaries (JSONL).
* ``cmcourier.metrics.network`` — per-request timing (JSONL).
* ``cmcourier.metrics.slow_ops`` — slow-ops per batch (handled by
  :class:`MetricsRecorder`'s per-batch file; this logger exists
  for the symmetry of the namespace).

If ``stderr_only=True`` or ``config.enabled=False``, file handlers
are not installed — only the stderr handler. The doctor's early
fail path uses this when no config has been parsed yet.
"""

from __future__ import annotations

__all__ = ["configure"]

import contextlib
import datetime as _dt
import logging
import sys
from logging.handlers import RotatingFileHandler

from cmcourier.config.schema import ObservabilityConfig
from cmcourier.observability.formatter import JsonFormatter
from cmcourier.observability.pii import PiiMaskingFilter

_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_METRICS_LOGGERS: tuple[str, ...] = (
    "cmcourier.metrics.pipeline",
    "cmcourier.metrics.network",
    "cmcourier.metrics.slow_ops",
)


def configure(
    config: ObservabilityConfig | None = None,
    log_level: str = "INFO",
    *,
    stderr_only: bool = False,
    tui_active: bool = False,
) -> None:
    """Install loggers, handlers, formatter, and PII filter.

    Parameters
    ----------
    config:
        ObservabilityConfig from the parsed pipeline config. If
        ``None`` or ``stderr_only=True``, only the stderr handler
        is installed.
    log_level:
        Level for the stderr handler. File handlers always log at
        INFO+ (DEBUG would explode rotation).
    stderr_only:
        Force the legacy path — no file handlers. Used by doctor
        early-load failure handling.
    tui_active:
        When ``True`` (041), the stderr StreamHandler is NOT attached
        to ``cmcourier`` so Textual's frame is not stomped on by
        ``log.info(...)`` calls during the run. Only the rotating
        FileHandler receives records. Ignored when ``stderr_only=True``
        (the doctor early-fail path still needs stderr no matter what).
    """
    _reset_all_handlers()

    level = getattr(logging, log_level.upper(), logging.INFO)
    pii_filter = PiiMaskingFilter()
    text_formatter = logging.Formatter(_TEXT_FORMAT)
    json_formatter = JsonFormatter()

    # ``cmcourier`` package logger: stderr handler unless the TUI is up;
    # file handler when enabled. Propagation stays at the default (True)
    # so pytest's ``caplog`` (which attaches at the root logger) keeps
    # capturing records.
    root = logging.getLogger("cmcourier")
    root.setLevel(min(level, logging.INFO))

    # 041: skip the stderr handler when a Textual TUI is rendering the
    # terminal — every emitted line would otherwise tear the frame.
    # ``stderr_only=True`` overrides because that path is the doctor's
    # early-fail diagnostic, which needs to print SOMEWHERE regardless.
    if stderr_only or not tui_active:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(text_formatter)
        stderr_handler.setLevel(level)
        stderr_handler.addFilter(pii_filter)
        root.addHandler(stderr_handler)

    if stderr_only or config is None or not config.enabled:
        # Metrics loggers exist but with no handlers attached → emissions
        # are no-ops (Python falls back to lastResort only on the root
        # logger, which we don't touch).
        for name in _METRICS_LOGGERS:
            mlog = logging.getLogger(name)
            mlog.propagate = False
            mlog.setLevel(logging.CRITICAL + 1)  # silent
        return

    log_dir = config.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    date_stamp = _dt.date.today().isoformat()
    app_formatter = json_formatter if config.log_format == "json" else text_formatter
    rotation_bytes = int(config.rotation_mb) * 1024 * 1024

    # App log handler (tier 1).
    app_handler = RotatingFileHandler(
        log_dir / f"app-{date_stamp}.log",
        maxBytes=rotation_bytes,
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setFormatter(app_formatter)
    app_handler.setLevel(logging.INFO)
    app_handler.addFilter(pii_filter)
    root.addHandler(app_handler)

    # Pipeline metrics handler (tier 2).
    pipeline_log = logging.getLogger("cmcourier.metrics.pipeline")
    pipeline_log.propagate = False
    pipeline_log.setLevel(logging.INFO if config.pipeline_metrics else logging.CRITICAL + 1)
    if config.pipeline_metrics:
        pipeline_handler = RotatingFileHandler(
            log_dir / f"metrics-{date_stamp}.jsonl",
            maxBytes=rotation_bytes,
            backupCount=5,
            encoding="utf-8",
        )
        pipeline_handler.setFormatter(json_formatter)
        pipeline_handler.setLevel(logging.INFO)
        pipeline_handler.addFilter(pii_filter)
        pipeline_log.addHandler(pipeline_handler)

    # Network metrics handler (tier 3).
    network_log = logging.getLogger("cmcourier.metrics.network")
    network_log.propagate = False
    network_log.setLevel(logging.INFO if config.network_metrics else logging.CRITICAL + 1)
    if config.network_metrics:
        network_handler = RotatingFileHandler(
            log_dir / f"network-{date_stamp}.jsonl",
            maxBytes=rotation_bytes,
            backupCount=5,
            encoding="utf-8",
        )
        network_handler.setFormatter(json_formatter)
        network_handler.setLevel(logging.INFO)
        network_handler.addFilter(pii_filter)
        network_log.addHandler(network_handler)

    # Slow-ops logger: per-batch file is owned by MetricsRecorder; this
    # logger exists for namespace symmetry only.
    slow_ops_log = logging.getLogger("cmcourier.metrics.slow_ops")
    slow_ops_log.propagate = False
    slow_ops_log.setLevel(logging.CRITICAL + 1)


def _reset_all_handlers() -> None:
    for name in ("cmcourier", *_METRICS_LOGGERS):
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            with contextlib.suppress(Exception):
                handler.close()
        # Reset propagation to default (True). Previous configure() may
        # have switched it off on the metrics loggers; without resetting,
        # later tests / runs inherit that state and caplog stops working.
        logger.propagate = True
        # Reset the level so a previous "silenced" run doesn't suppress
        # records on the next invocation.
        logger.setLevel(logging.NOTSET)

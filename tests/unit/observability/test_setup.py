"""Unit tests for ``cmcourier.observability.setup.configure`` (041)."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from cmcourier.config.schema import ObservabilityConfig
from cmcourier.observability.setup import configure


@pytest.fixture
def obs_config(tmp_path: Path) -> ObservabilityConfig:
    return ObservabilityConfig(
        enabled=True,
        log_dir=tmp_path / "logs",
        log_format="text",
        pipeline_metrics=True,
        network_metrics=True,
        rotation_mb=5,
        slow_op_threshold_ms=1000.0,
        slow_op_top_n=10,
    )


@pytest.fixture(autouse=True)
def _reset_cmcourier_logger() -> None:
    root = logging.getLogger("cmcourier")
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.NOTSET)


def _stderr_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [
        h
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, RotatingFileHandler)
        and getattr(h, "stream", None) is sys.stderr
    ]


def _file_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]


def test_configure_default_attaches_stderr_and_file(obs_config: ObservabilityConfig) -> None:
    configure(obs_config, "INFO")
    root = logging.getLogger("cmcourier")
    assert len(_stderr_handlers(root)) == 1, "default mode must keep the stderr handler"
    assert len(_file_handlers(root)) == 1, "default mode must keep the rotating file handler"


def test_configure_tui_active_omits_stderr(obs_config: ObservabilityConfig) -> None:
    configure(obs_config, "INFO", tui_active=True)
    root = logging.getLogger("cmcourier")
    assert _stderr_handlers(root) == [], (
        "tui_active=True must NOT attach the stderr StreamHandler (would tear the TUI frame)"
    )
    assert len(_file_handlers(root)) == 1, (
        "tui_active=True still needs the rotating file handler so logs persist to disk"
    )


def test_configure_stderr_only_overrides_tui_active(obs_config: ObservabilityConfig) -> None:
    """The doctor early-fail path passes stderr_only=True; it must still print."""
    configure(obs_config, "INFO", stderr_only=True, tui_active=True)
    root = logging.getLogger("cmcourier")
    assert len(_stderr_handlers(root)) == 1, (
        "stderr_only=True is the diagnostic escape hatch — it must always print to stderr"
    )
    assert _file_handlers(root) == [], "stderr_only=True must skip file handlers"


def test_configure_tui_active_with_disabled_observability_still_skips_stderr() -> None:
    """tui_active gating must work even when no ObservabilityConfig is provided."""
    configure(None, "INFO", tui_active=True)
    root = logging.getLogger("cmcourier")
    assert _stderr_handlers(root) == []
    assert _file_handlers(root) == []


def test_configure_idempotent_replaces_handlers(obs_config: ObservabilityConfig) -> None:
    """Re-calling configure with a different mode swaps handler set without leaks."""
    configure(obs_config, "INFO")
    configure(obs_config, "INFO", tui_active=True)
    root = logging.getLogger("cmcourier")
    assert _stderr_handlers(root) == []
    assert len(_file_handlers(root)) == 1, "exactly one file handler after re-configure"

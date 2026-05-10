"""Shared CLI integration fixtures.

The autouse ``_reset_root_logger`` fixture removes every handler on the
root logger before AND after each test so the CLI's
``logging_setup.configure(...)`` call cannot leak handler state across
tests.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from click.testing import CliRunner


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    for handler in list(root.handlers):
        root.removeHandler(handler)
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in saved_handlers:
        root.addHandler(handler)
    root.setLevel(saved_level)


@pytest.fixture
def cli_runner() -> CliRunner:
    # Click 8.2+ separates stdout/stderr by default — no kwargs needed.
    return CliRunner()

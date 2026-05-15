"""`Fixtures` compartidos para los tests de integración del CLI.

El `fixture` con `autouse` ``_reset_root_logger`` saca todos los handlers
del `logger` raíz ANTES y DESPUÉS de cada test, así la llamada a
``logging_setup.configure(...)`` del CLI no puede filtrar estado de
handlers entre tests.
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
    # Click 8.2+ ya separa stdout/stderr por default — no hacen falta `kwargs`.
    return CliRunner()

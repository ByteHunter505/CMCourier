"""Minimal root-logger setup for the CLI.

Single stderr ``StreamHandler``. The tiered logging design from REBIRTH
§17.4 (application / pipeline / network / system / slow-ops) lands in a
dedicated change. For 012, the CLI ships a single handler whose level is
driven by ``--log-level``.

The setup function is idempotent: subsequent calls replace existing
handlers so tests can re-invoke between commands without leaking state.
"""

from __future__ import annotations

__all__ = ["configure"]

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure(level: str = "INFO") -> None:
    """Install a stderr ``StreamHandler`` on the root logger."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

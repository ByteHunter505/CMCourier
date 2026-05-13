"""CMCourier — banking document migration tool (RVI on AS400 -> IBM Content Manager via CMIS)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("cmcourier")
except PackageNotFoundError:
    # Source-tree import without an install (e.g. some test harnesses);
    # keep something readable instead of crashing the CLI.
    __version__ = "0.0.0+unknown"

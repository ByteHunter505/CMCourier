"""Legacy CLI logging shim — delegates to ``cmcourier.observability.setup``.

Pre-020 the CLI shipped a stderr-only text logger here. 020 moved
the real implementation to ``cmcourier.observability.setup``; this
module remains as a thin shim so:

* The ``configure(level)`` signature keeps working for callers that
  do not yet have a parsed config (doctor's early-load failure
  path).
* The legacy stderr-only behavior is preserved.

CLI entry points that have a parsed config call
:func:`cmcourier.observability.setup.configure` directly with the
``config.observability`` block.
"""

from __future__ import annotations

__all__ = ["configure"]

from cmcourier.observability.setup import configure as _configure_observability


def configure(level: str = "INFO") -> None:
    """Install a stderr-only logger. Used before config parsing."""
    _configure_observability(None, level, stderr_only=True)

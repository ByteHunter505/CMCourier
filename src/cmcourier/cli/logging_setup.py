"""Shim legado de logging para el CLI: delega en ``cmcourier.observability.setup``.

Antes de 020 el CLI traia aca un logger de texto solo-stderr. 020 movio
la implementacion real a ``cmcourier.observability.setup``; este modulo
queda como un shim fino para que:

* La firma ``configure(level)`` siga funcionando para los callers que
  todavia no tienen una config parseada (camino de falla temprana de
  carga del doctor).
* Se preserve el comportamiento legado solo-stderr.

Los entry points del CLI que ya tienen una config parseada llaman
:func:`cmcourier.observability.setup.configure` directamente con el
bloque ``config.observability``.
"""

from __future__ import annotations

__all__ = ["configure"]

from cmcourier.observability.setup import configure as _configure_observability


def configure(level: str = "INFO") -> None:
    """Instala un logger solo-stderr. Se usa antes de parsear la config."""
    _configure_observability(None, level, stderr_only=True)

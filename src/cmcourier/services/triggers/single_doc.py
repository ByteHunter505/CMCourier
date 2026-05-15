"""Estrategia de trigger single-doc (`pipeline` de diagnóstico).

Yieldea exactamente un :class:`TriggerRecord` armado a partir de
``shortname``, ``system_id`` y un ``cif`` opcional provistos por el
caller. Los valores del trigger vienen de argumentos del CLI, no
de una fuente de datos.

Caso de uso: el operador empuja los documentos de un cliente
específico sin escanear un `batch` completo.
"""

from __future__ import annotations

__all__ = ["SingleDocTriggerStrategy"]

from collections.abc import Iterator

from cmcourier.domain.models import TriggerRecord
from cmcourier.domain.ports import S0Strategy


class SingleDocTriggerStrategy(S0Strategy):
    """Estrategia de S0 que yieldea un único ``TriggerRecord`` a
    partir de argumentos provistos por el CLI."""

    def __init__(
        self,
        shortname: str,
        system_id: str,
        cif: str | None = None,
    ) -> None:
        self._trigger = TriggerRecord(
            shortname=shortname,
            cif=cif if cif else None,
            system_id=system_id,
        )

    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]:
        del source_descriptor  # parámetro vestigial del port
        yield self._trigger

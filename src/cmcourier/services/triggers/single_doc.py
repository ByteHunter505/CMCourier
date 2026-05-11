"""Single-doc trigger strategy (REBIRTH §10.2 diagnostic pipeline).

Yields exactly one :class:`TriggerRecord` built from caller-provided
``shortname``, ``system_id``, and optional ``cif``. The trigger
values come from CLI args, not from a data source.

Use case: operator pushes one specific client's documents without
scanning a full batch.
"""

from __future__ import annotations

__all__ = ["SingleDocTriggerStrategy"]

from collections.abc import Iterator

from cmcourier.domain.models import TriggerRecord
from cmcourier.domain.ports import S0Strategy


class SingleDocTriggerStrategy(S0Strategy):
    """S0 strategy that yields one TriggerRecord from CLI-provided args."""

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
        del source_descriptor  # vestigial port parameter
        yield self._trigger

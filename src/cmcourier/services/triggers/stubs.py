"""Trigger strategies that depend on infrastructure not yet shipped.

These classes are concrete ``S0Strategy`` subclasses whose constructors
succeed (so an orchestrator can dispatch to them) but whose ``acquire()``
calls raise ``NotImplementedError`` with messages naming their missing
dependencies.

The ``As400TriggerStrategy`` from this module has been promoted to a
real implementation in ``services/triggers/as400.py`` (change 014).
This module retains only the remaining stubs.
"""

from __future__ import annotations

__all__ = ["LocalScanTriggerStrategy"]

from collections.abc import Iterator
from pathlib import Path

from cmcourier.domain.models import TriggerRecord
from cmcourier.domain.ports import IDataSource, S0Strategy


class LocalScanTriggerStrategy(S0Strategy):
    """REBIRTH §5.1 mode ``local_scan``.

    Activates when the folder-scanner module ships in a later change.
    """

    def __init__(
        self,
        scan_path: Path,
        cif_lookup_source: IDataSource | None = None,
    ) -> None:
        self._scan_path = scan_path
        self._cif_lookup_source = cif_lookup_source

    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]:
        del source_descriptor
        raise NotImplementedError(
            "local-scan strategy not yet shipped; depends on a forthcoming folder-scanner module."
        )
        yield  # pragma: no cover - keeps the function a generator

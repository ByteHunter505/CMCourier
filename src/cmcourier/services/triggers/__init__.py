"""Concrete S0Strategy implementations for stage S0 (Trigger Acquisition).

Two real strategies (CSV, direct RVABREP) plus two stubs (AS400, local scan)
that raise ``NotImplementedError`` until their infrastructure ships.
"""

from __future__ import annotations

__all__ = [
    "As400TriggerStrategy",
    "CsvTriggerColumnsConfig",
    "CsvTriggerStrategy",
    "DirectRvabrepTriggerStrategy",
    "LocalScanTriggerStrategy",
    "RvabrepColumnsConfig",
    "RvabrepFilters",
]

from cmcourier.services.triggers.csv import (
    CsvTriggerColumnsConfig,
    CsvTriggerStrategy,
)
from cmcourier.services.triggers.direct_rvabrep import (
    DirectRvabrepTriggerStrategy,
    RvabrepColumnsConfig,
    RvabrepFilters,
)
from cmcourier.services.triggers.stubs import (
    As400TriggerStrategy,
    LocalScanTriggerStrategy,
)

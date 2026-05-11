"""Concrete S0Strategy implementations for stage S0 (Trigger Acquisition).

Four real strategies (CSV, direct RVABREP, AS400, local scan) — the
full set from REBIRTH §5.1. No stubs remain.
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

from cmcourier.services.triggers.as400 import As400TriggerStrategy
from cmcourier.services.triggers.csv import (
    CsvTriggerColumnsConfig,
    CsvTriggerStrategy,
)
from cmcourier.services.triggers.direct_rvabrep import (
    DirectRvabrepTriggerStrategy,
    RvabrepColumnsConfig,
    RvabrepFilters,
)
from cmcourier.services.triggers.local_scan import LocalScanTriggerStrategy

"""Concrete S0Strategy implementations for stage S0 (Trigger Acquisition).

Three real strategies (CSV, direct RVABREP, AS400) plus one stub
(local scan) that raises ``NotImplementedError`` until its infrastructure
ships.
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
from cmcourier.services.triggers.stubs import LocalScanTriggerStrategy

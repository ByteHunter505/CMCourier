"""Concrete S0Strategy implementations for stage S0 (Trigger Acquisition).

Four production strategies (CSV, direct RVABREP, AS400, local scan)
covering REBIRTH §5.1's four trigger source modes, plus one
diagnostic strategy (single-doc, REBIRTH §10.2).
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
    "SingleDocTriggerStrategy",
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
from cmcourier.services.triggers.single_doc import SingleDocTriggerStrategy

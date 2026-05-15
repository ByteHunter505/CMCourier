"""Implementaciones concretas de :class:`S0Strategy` para el stage
S0 (`Trigger Acquisition`).

Cuatro estrategias de producción (CSV, RVABREP directo, AS400 y
local scan) cubren los cuatro modos de fuente de trigger, más una
estrategia de diagnóstico (single-doc).
"""

from __future__ import annotations

__all__ = [
    "CsvTriggerColumnsConfig",
    "CsvTriggerStrategy",
    "DirectRvabrepTriggerStrategy",
    "LocalScanTriggerStrategy",
    "RvabrepColumnsConfig",
    "RvabrepFilters",
    "SingleDocTriggerStrategy",
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
from cmcourier.services.triggers.local_scan import LocalScanTriggerStrategy
from cmcourier.services.triggers.single_doc import SingleDocTriggerStrategy

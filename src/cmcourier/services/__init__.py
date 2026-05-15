"""Capa de servicios: lógica de negocio que depende solo de los ports de dominio.

Contiene los servicios ``mapping``, ``metadata``, las estrategias de
``trigger`` y el futuro servicio ``document``. No realiza I/O directo.
Límite estricto: función <= 50 líneas (Principio III de la Constitución).
"""

from __future__ import annotations

__all__ = [
    "CsvTriggerColumnsConfig",
    "CsvTriggerStrategy",
    "DirectRvabrepTriggerStrategy",
    "FieldSourceConfig",
    "IndexingColumnsConfig",
    "IndexingService",
    "LocalScanTriggerStrategy",
    "MappingColumnsConfig",
    "MappingService",
    "MetadataConfig",
    "MetadataResolution",
    "MetadataService",
    "RvabrepColumnsConfig",
    "RvabrepFilters",
    "SourceConfig",
    "ValidationConfig",
]

from cmcourier.services.indexing import IndexingColumnsConfig, IndexingService
from cmcourier.services.mapping import MappingColumnsConfig, MappingService
from cmcourier.services.metadata import (
    FieldSourceConfig,
    MetadataConfig,
    MetadataResolution,
    MetadataService,
    SourceConfig,
    ValidationConfig,
)
from cmcourier.services.triggers import (
    CsvTriggerColumnsConfig,
    CsvTriggerStrategy,
    DirectRvabrepTriggerStrategy,
    LocalScanTriggerStrategy,
    RvabrepColumnsConfig,
    RvabrepFilters,
)

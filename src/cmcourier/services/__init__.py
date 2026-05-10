"""Services layer - business logic depending only on domain ports.

Houses ``mapping``, ``metadata``, ``trigger`` strategies, and future ``document``
service. No direct I/O. Hard limit: function <= 50 lines (Constitution
Principle III).
"""

from __future__ import annotations

__all__ = [
    "As400TriggerStrategy",
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
    As400TriggerStrategy,
    CsvTriggerColumnsConfig,
    CsvTriggerStrategy,
    DirectRvabrepTriggerStrategy,
    LocalScanTriggerStrategy,
    RvabrepColumnsConfig,
    RvabrepFilters,
)

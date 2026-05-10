"""Services layer - business logic depending only on domain ports.

Houses ``mapping``, ``metadata``, ``trigger``, ``document`` services. No direct
I/O. Hard limit: function <= 50 lines (Constitution Principle III).
"""

from __future__ import annotations

__all__ = [
    "FieldSourceConfig",
    "MappingColumnsConfig",
    "MappingService",
    "MetadataConfig",
    "MetadataResolution",
    "MetadataService",
    "SourceConfig",
    "ValidationConfig",
]

from cmcourier.services.mapping import MappingColumnsConfig, MappingService
from cmcourier.services.metadata import (
    FieldSourceConfig,
    MetadataConfig,
    MetadataResolution,
    MetadataService,
    SourceConfig,
    ValidationConfig,
)

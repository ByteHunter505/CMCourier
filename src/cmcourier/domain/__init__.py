"""Domain layer — pure Python, zero external dependencies (Constitution Principle I).

Holds models (dataclasses), ports (abstract interfaces), and the typed exception
hierarchy. No I/O, no third-party imports — even ``pydantic`` is forbidden here.

Public names from ``models``, ``ports``, and ``exceptions`` are re-exported
here so callers write ``from cmcourier.domain import IDataSource`` without
having to know which submodule a name lives in.
"""

from __future__ import annotations

from cmcourier.domain.exceptions import (
    AssemblyError,
    CMCourierError,
    CMISClientError,
    CMISServerError,
    ConfigurationError,
    DefaultValidationFailedError,
    IDRViNotMappedError,
    IndexingError,
    MappingError,
    MetadataError,
    PDFAssemblyFailedError,
    RetriesExhaustedError,
    RVABREPDeletedError,
    RVABREPDuplicateError,
    RVABREPNotFoundError,
    SourceFailedError,
    SourceFileMissingError,
    TrackingError,
    TriggerError,
    UploadError,
)
from cmcourier.domain.models import (
    CMMapping,
    MigrationRecord,
    ResolvedMetadata,
    RVABREPDocument,
    StagedFile,
    StageStatus,
    TriggerRecord,
    compute_cm_folder,
    compute_cm_object_type,
    is_pdf_filename,
    parse_cymmdd,
)
from cmcourier.domain.ports import (
    IAssembler,
    IDataSource,
    ITrackingStore,
    IUploader,
    S0Strategy,
)

__all__ = [
    "AssemblyError",
    "CMCourierError",
    "CMISClientError",
    "CMISServerError",
    "CMMapping",
    "ConfigurationError",
    "DefaultValidationFailedError",
    "IAssembler",
    "IDRViNotMappedError",
    "IDataSource",
    "ITrackingStore",
    "IUploader",
    "IndexingError",
    "MappingError",
    "MetadataError",
    "MigrationRecord",
    "PDFAssemblyFailedError",
    "RVABREPDeletedError",
    "RVABREPDocument",
    "RVABREPDuplicateError",
    "RVABREPNotFoundError",
    "ResolvedMetadata",
    "RetriesExhaustedError",
    "S0Strategy",
    "SourceFailedError",
    "SourceFileMissingError",
    "StageStatus",
    "StagedFile",
    "TrackingError",
    "TriggerError",
    "TriggerRecord",
    "UploadError",
    "compute_cm_folder",
    "compute_cm_object_type",
    "is_pdf_filename",
    "parse_cymmdd",
]

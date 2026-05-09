"""Verify that every public name is importable directly from ``cmcourier.domain``.

A reader should be able to write ``from cmcourier.domain import IDataSource``
without knowing whether the symbol lives in ``models``, ``ports``, or
``exceptions``. This test guards against re-export drift.
"""

from __future__ import annotations


def test_models_importable() -> None:
    from cmcourier.domain import (
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

    # Just touch them to satisfy linters and prove they resolved.
    assert all(
        x is not None
        for x in (
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
    )


def test_ports_importable() -> None:
    from cmcourier.domain import (
        IAssembler,
        IDataSource,
        ITrackingStore,
        IUploader,
        S0Strategy,
    )

    ports = (IAssembler, IDataSource, ITrackingStore, IUploader, S0Strategy)
    assert all(x is not None for x in ports)


def test_exceptions_importable() -> None:
    from cmcourier.domain import (
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

    assert all(
        x is not None
        for x in (
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
    )


def test_dunder_all_is_complete() -> None:
    """``__all__`` must list every re-exported name and nothing else."""
    import cmcourier.domain as domain

    expected = {
        # Exceptions
        "AssemblyError",
        "CMCourierError",
        "CMISClientError",
        "CMISServerError",
        "ConfigurationError",
        "DefaultValidationFailedError",
        "IDRViNotMappedError",
        "IndexingError",
        "MappingError",
        "MetadataError",
        "PDFAssemblyFailedError",
        "RVABREPDeletedError",
        "RVABREPDuplicateError",
        "RVABREPNotFoundError",
        "RetriesExhaustedError",
        "SourceFailedError",
        "SourceFileMissingError",
        "TrackingError",
        "TriggerError",
        "UploadError",
        # Models + helpers
        "CMMapping",
        "MigrationRecord",
        "ResolvedMetadata",
        "RVABREPDocument",
        "StageStatus",
        "StagedFile",
        "TriggerRecord",
        "compute_cm_folder",
        "compute_cm_object_type",
        "is_pdf_filename",
        "parse_cymmdd",
        # Ports
        "IAssembler",
        "IDataSource",
        "ITrackingStore",
        "IUploader",
        "S0Strategy",
    }
    assert set(domain.__all__) == expected

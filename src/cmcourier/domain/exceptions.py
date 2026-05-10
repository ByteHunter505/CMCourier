"""Typed exception hierarchy for CMCourier.

All project errors descend from :class:`CMCourierError`. Stage-specific errors
(``S0`` … ``S5``) descend from a stage-base class so handlers can filter by
stage without listing every concrete subclass:

.. code-block:: python

    try:
        ...
    except MappingError as exc:
        # catches IDRViNotMappedError too
        log.error("mapping failed", **exc.context)

Every concrete subclass declares its named context parameters explicitly so
type-checkers catch typos at call sites (``IDRViNotMappedError(id_rvi=...)``,
not ``IDRViNotMappedError(idrvi=...)``).

This module is part of the domain layer (Constitution Principle I): pure
Python standard library only. Do not import third-party modules here.
"""

from __future__ import annotations

__all__ = [
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
]


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


class CMCourierError(Exception):
    """Root of the CMCourier exception hierarchy.

    Accepts an optional human message plus arbitrary keyword context. The
    context dict is stored on the instance and reflected in ``str(exc)`` so
    structured loggers can extract the fields without parsing the message.
    """

    def __init__(self, message: str = "", **context: object) -> None:
        self.context: dict[str, object] = dict(context)
        if context:
            ctx_str = ", ".join(f"{k}={v!r}" for k, v in context.items())
            full = f"{message} [{ctx_str}]" if message else ctx_str
        else:
            full = message
        super().__init__(full)


# ---------------------------------------------------------------------------
# Configuration (raised at startup, not tied to a stage)
# ---------------------------------------------------------------------------


class ConfigurationError(CMCourierError):
    """Configuration is invalid or missing required fields."""


# ---------------------------------------------------------------------------
# Stage S0 — Trigger Acquisition
# ---------------------------------------------------------------------------


class TriggerError(CMCourierError):
    """Stage S0 failure: trigger source unreachable, malformed, or empty."""


# ---------------------------------------------------------------------------
# Stage S1 — RVABREP Indexing
# ---------------------------------------------------------------------------


class IndexingError(CMCourierError):
    """Stage S1 base error."""


class RVABREPNotFoundError(IndexingError):
    """No RVABREP rows for the given (shortname, system_id)."""

    def __init__(self, *, shortname: str, system_id: str) -> None:
        super().__init__(
            "RVABREP record not found",
            shortname=shortname,
            system_id=system_id,
        )
        self.shortname = shortname
        self.system_id = system_id


class RVABREPDeletedError(IndexingError):
    """Every RVABREP row matching the trigger is marked deleted (``ABACST`` non-empty).

    Raised by stage S1 when ``(shortname, system_id)`` returns one or more
    rows but all of them carry a non-empty delete code. ``deleted_count`` is
    the number of deleted rows seen.
    """

    def __init__(self, *, shortname: str, system_id: str, deleted_count: int) -> None:
        super().__init__(
            "Every RVABREP record for the trigger is marked deleted",
            shortname=shortname,
            system_id=system_id,
            deleted_count=deleted_count,
        )
        self.shortname = shortname
        self.system_id = system_id
        self.deleted_count = deleted_count


class RVABREPDuplicateError(IndexingError):
    """Multiple RVABREP rows match where exactly one was expected."""

    def __init__(self, *, shortname: str, system_id: str, count: int) -> None:
        super().__init__(
            "Multiple RVABREP records matched",
            shortname=shortname,
            system_id=system_id,
            count=count,
        )
        self.shortname = shortname
        self.system_id = system_id
        self.count = count


# ---------------------------------------------------------------------------
# Stage S2 — Document Class Mapping
# ---------------------------------------------------------------------------


class MappingError(CMCourierError):
    """Stage S2 base error."""


class IDRViNotMappedError(MappingError):
    """The ID RVI has no entry in the Modelo Documental."""

    def __init__(self, *, id_rvi: str, txn_num: str | None = None) -> None:
        super().__init__(
            "ID RVI not mapped in Modelo Documental",
            id_rvi=id_rvi,
            txn_num=txn_num,
        )
        self.id_rvi = id_rvi
        self.txn_num = txn_num


# ---------------------------------------------------------------------------
# Stage S3 — Metadata Resolution
# ---------------------------------------------------------------------------


class MetadataError(CMCourierError):
    """Stage S3 base error."""


class SourceFailedError(MetadataError):
    """A metadata source raised or returned no value, and there is no fallback."""

    def __init__(self, *, field_name: str, source: str) -> None:
        super().__init__(
            "Metadata source failed",
            field_name=field_name,
            source=source,
        )
        self.field_name = field_name
        self.source = source


class DefaultValidationFailedError(MetadataError):
    """All sources failed AND the configured default did not pass validation."""

    def __init__(self, *, field_name: str, default_value: str) -> None:
        super().__init__(
            "Default value did not pass validation",
            field_name=field_name,
            default_value=default_value,
        )
        self.field_name = field_name
        self.default_value = default_value


# ---------------------------------------------------------------------------
# Stage S4 — File Verification & Assembly
# ---------------------------------------------------------------------------


class AssemblyError(CMCourierError):
    """Stage S4 base error."""


class SourceFileMissingError(AssemblyError):
    """Expected source file is not present on the file server."""

    def __init__(self, *, file_path: str) -> None:
        super().__init__(
            "Source file missing on file server",
            file_path=file_path,
        )
        self.file_path = file_path


class PDFAssemblyFailedError(AssemblyError):
    """Underlying PDF assembly tooling raised."""

    def __init__(self, *, txn_num: str, reason: str) -> None:
        super().__init__(
            "PDF assembly failed",
            txn_num=txn_num,
            reason=reason,
        )
        self.txn_num = txn_num
        self.reason = reason


# ---------------------------------------------------------------------------
# Stage S5 — Upload
# ---------------------------------------------------------------------------


class UploadError(CMCourierError):
    """Stage S5 base error."""


class CMISClientError(UploadError):
    """HTTP 4xx from the CMIS server. Do NOT retry — fix the request."""

    def __init__(self, *, status_code: int, response_body: str = "") -> None:
        super().__init__(
            "CMIS rejected the request (4xx)",
            status_code=status_code,
            response_body=response_body,
        )
        self.status_code = status_code
        self.response_body = response_body


class CMISServerError(UploadError):
    """HTTP 5xx from the CMIS server. Retry with backoff."""

    def __init__(self, *, status_code: int, response_body: str = "") -> None:
        super().__init__(
            "CMIS server error (5xx)",
            status_code=status_code,
            response_body=response_body,
        )
        self.status_code = status_code
        self.response_body = response_body


class RetriesExhaustedError(UploadError):
    """Retry budget exhausted for a single document upload."""

    def __init__(self, *, txn_num: str, attempts: int) -> None:
        super().__init__(
            "Upload retries exhausted",
            txn_num=txn_num,
            attempts=attempts,
        )
        self.txn_num = txn_num
        self.attempts = attempts


# ---------------------------------------------------------------------------
# Stage S6 — Tracking (transversal; never blocks the pipeline)
# ---------------------------------------------------------------------------


class TrackingError(CMCourierError):
    """Tracking store write failure. Logged, never raised through callers."""

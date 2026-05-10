"""Unit tests for ``cmcourier.domain.exceptions``.

Validates the typed hierarchy structure (so ``except MappingError`` catches all
mapping-stage failures) and the structured-context contract (so loggers can
extract ``txn_num``, ``id_rvi``, etc. without parsing the message).
"""

from __future__ import annotations

import pytest

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


class TestHierarchy:
    """Every project exception MUST descend from CMCourierError, and stage-
    specific subclasses MUST descend from their stage's base error."""

    @pytest.mark.parametrize(
        ("subclass", "ancestor"),
        [
            # Direct children of root
            (ConfigurationError, CMCourierError),
            (TriggerError, CMCourierError),
            (IndexingError, CMCourierError),
            (MappingError, CMCourierError),
            (MetadataError, CMCourierError),
            (AssemblyError, CMCourierError),
            (UploadError, CMCourierError),
            (TrackingError, CMCourierError),
            # IndexingError children (S1)
            (RVABREPNotFoundError, IndexingError),
            (RVABREPDeletedError, IndexingError),
            (RVABREPDuplicateError, IndexingError),
            (RVABREPNotFoundError, CMCourierError),  # transitively
            # MappingError children (S2)
            (IDRViNotMappedError, MappingError),
            (IDRViNotMappedError, CMCourierError),
            # MetadataError children (S3)
            (SourceFailedError, MetadataError),
            (DefaultValidationFailedError, MetadataError),
            (SourceFailedError, CMCourierError),
            # AssemblyError children (S4)
            (SourceFileMissingError, AssemblyError),
            (PDFAssemblyFailedError, AssemblyError),
            (SourceFileMissingError, CMCourierError),
            # UploadError children (S5)
            (CMISClientError, UploadError),
            (CMISServerError, UploadError),
            (RetriesExhaustedError, UploadError),
            (CMISClientError, CMCourierError),
        ],
    )
    def test_subclass_relationship(
        self, subclass: type[Exception], ancestor: type[Exception]
    ) -> None:
        assert issubclass(subclass, ancestor)

    def test_root_descends_from_exception(self) -> None:
        assert issubclass(CMCourierError, Exception)


class TestStructuredContext:
    """Subclasses with named context parameters MUST expose them as attributes
    AND surface them in ``str(exc)`` for log discoverability."""

    def test_id_rvi_not_mapped(self) -> None:
        exc = IDRViNotMappedError(id_rvi="ZZ99")
        assert exc.id_rvi == "ZZ99"
        assert "ZZ99" in str(exc)

    def test_id_rvi_not_mapped_with_txn_num(self) -> None:
        exc = IDRViNotMappedError(id_rvi="ZZ99", txn_num="123456789")
        assert exc.id_rvi == "ZZ99"
        assert exc.txn_num == "123456789"
        assert "ZZ99" in str(exc)
        assert "123456789" in str(exc)

    def test_rvabrep_not_found(self) -> None:
        exc = RVABREPNotFoundError(shortname="JUANPEREZ01", system_id="1")
        assert exc.shortname == "JUANPEREZ01"
        assert exc.system_id == "1"
        assert "JUANPEREZ01" in str(exc)

    def test_rvabrep_deleted(self) -> None:
        exc = RVABREPDeletedError(shortname="JUANPEREZ01", system_id="1", deleted_count=3)
        assert exc.shortname == "JUANPEREZ01"
        assert exc.system_id == "1"
        assert exc.deleted_count == 3
        assert "JUANPEREZ01" in str(exc)

    def test_source_failed(self) -> None:
        exc = SourceFailedError(field_name="BAC_CIF", source="rvabrep")
        assert exc.field_name == "BAC_CIF"
        assert exc.source == "rvabrep"
        assert "BAC_CIF" in str(exc)

    def test_default_validation_failed(self) -> None:
        exc = DefaultValidationFailedError(field_name="BAC_CIF", default_value="abc")
        assert exc.field_name == "BAC_CIF"
        assert exc.default_value == "abc"

    def test_source_file_missing(self) -> None:
        exc = SourceFileMissingError(file_path="/srv/rvi/0AAAUI0K.001")
        assert exc.file_path == "/srv/rvi/0AAAUI0K.001"
        assert "0AAAUI0K.001" in str(exc)

    def test_pdf_assembly_failed(self) -> None:
        exc = PDFAssemblyFailedError(txn_num="123", reason="img2pdf rejected mixed content")
        assert exc.txn_num == "123"
        assert exc.reason == "img2pdf rejected mixed content"

    def test_cmis_client_error(self) -> None:
        exc = CMISClientError(status_code=400, response_body="malformed metadata")
        assert exc.status_code == 400
        assert exc.response_body == "malformed metadata"
        assert "400" in str(exc)

    def test_cmis_server_error(self) -> None:
        exc = CMISServerError(status_code=503, response_body="upstream down")
        assert exc.status_code == 503

    def test_retries_exhausted(self) -> None:
        exc = RetriesExhaustedError(txn_num="123", attempts=5)
        assert exc.txn_num == "123"
        assert exc.attempts == 5
        assert "5" in str(exc)


class TestRootBaseClass:
    """The root CMCourierError accepts free-form context for handlers that
    don't need a typed subclass (rare, but allowed)."""

    def test_no_context(self) -> None:
        exc = CMCourierError("just a message")
        assert str(exc) == "just a message"
        assert exc.context == {}

    def test_context_only(self) -> None:
        exc = CMCourierError(foo="bar", baz=42)
        assert exc.context == {"foo": "bar", "baz": 42}
        # str includes both keys
        assert "foo" in str(exc)
        assert "bar" in str(exc) or "'bar'" in str(exc)

    def test_message_and_context(self) -> None:
        exc = CMCourierError("boom", reason="explosion")
        s = str(exc)
        assert "boom" in s
        assert "reason" in s

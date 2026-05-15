"""Tests unitarios para ``cmcourier.domain.exceptions``.

Valida la estructura jerárquica tipada (para que ``except
MappingError`` capture todas las fallas de la etapa de mapping) y el
contrato de contexto estructurado (para que los loggers puedan
extraer ``txn_num``, ``id_rvi``, etc. sin parsear el mensaje).
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
    """Cada excepción del proyecto DEBE descender de `CMCourierError`,
    y las subclases específicas de etapa DEBEN descender del error
    base de su etapa."""

    @pytest.mark.parametrize(
        ("subclass", "ancestor"),
        [
            # Hijos directos del root
            (ConfigurationError, CMCourierError),
            (TriggerError, CMCourierError),
            (IndexingError, CMCourierError),
            (MappingError, CMCourierError),
            (MetadataError, CMCourierError),
            (AssemblyError, CMCourierError),
            (UploadError, CMCourierError),
            (TrackingError, CMCourierError),
            # Hijos de `IndexingError` (S1)
            (RVABREPNotFoundError, IndexingError),
            (RVABREPDeletedError, IndexingError),
            (RVABREPDuplicateError, IndexingError),
            (RVABREPNotFoundError, CMCourierError),  # transitivamente
            # Hijos de `MappingError` (S2)
            (IDRViNotMappedError, MappingError),
            (IDRViNotMappedError, CMCourierError),
            # Hijos de `MetadataError` (S3)
            (SourceFailedError, MetadataError),
            (DefaultValidationFailedError, MetadataError),
            (SourceFailedError, CMCourierError),
            # Hijos de `AssemblyError` (S4)
            (SourceFileMissingError, AssemblyError),
            (PDFAssemblyFailedError, AssemblyError),
            (SourceFileMissingError, CMCourierError),
            # Hijos de `UploadError` (S5)
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
    """Las subclases con parámetros de contexto nombrados DEBEN
    exponerlos como atributos Y aflorarlos en ``str(exc)`` para
    descubribilidad en los logs."""

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
    """El root `CMCourierError` acepta contexto libre para `handler`s
    que no necesitan una subclase tipada (raro, pero permitido)."""

    def test_no_context(self) -> None:
        exc = CMCourierError("just a message")
        assert str(exc) == "just a message"
        assert exc.context == {}

    def test_context_only(self) -> None:
        exc = CMCourierError(foo="bar", baz=42)
        assert exc.context == {"foo": "bar", "baz": 42}
        # `str` incluye ambas claves
        assert "foo" in str(exc)
        assert "bar" in str(exc) or "'bar'" in str(exc)

    def test_message_and_context(self) -> None:
        exc = CMCourierError("boom", reason="explosion")
        s = str(exc)
        assert "boom" in s
        assert "reason" in s


class TestAssemblyExceptionsPicklable066:
    """066: `SourceFileMissingError` + `PDFAssemblyFailedError` cruzan
    los límites del `ProcessPoolExecutor` cuando S4 se despacha a un
    proceso `worker`. ``pickle.loads(pickle.dumps(exc))`` debe
    `round-trip` con cada atributo preservado."""

    def test_source_file_missing_round_trips_through_pickle(self) -> None:
        import pickle

        from cmcourier.domain.exceptions import SourceFileMissingError

        original = SourceFileMissingError(file_path="/share/PROD/2025/MISSING.001")
        restored = pickle.loads(pickle.dumps(original))
        assert isinstance(restored, SourceFileMissingError)
        assert restored.file_path == original.file_path
        assert str(restored) == str(original)

    def test_pdf_assembly_failed_round_trips_through_pickle(self) -> None:
        import pickle

        from cmcourier.domain.exceptions import PDFAssemblyFailedError

        original = PDFAssemblyFailedError(
            txn_num="TXN_BANK_42",
            reason="img2pdf: encoding failed",
        )
        restored = pickle.loads(pickle.dumps(original))
        assert isinstance(restored, PDFAssemblyFailedError)
        assert restored.txn_num == original.txn_num
        assert restored.reason == original.reason
        assert str(restored) == str(original)

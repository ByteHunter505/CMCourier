"""Tests unitarios para el `formatter` JSON + filtro de enmascarado PII.

El `formatter` renderiza un objeto JSON por ``LogRecord``; el filtro
redacta nombres de campo PII conocidos antes de que el `formatter`
los vea.
"""

from __future__ import annotations

import json
import logging

import pytest

from cmcourier.observability.formatter import ALLOWED_EXTRA_FIELDS, JsonFormatter
from cmcourier.observability.pii import MASK, PiiMaskingFilter

pytestmark = pytest.mark.unit


def _make_record(
    *,
    name: str = "cmcourier.test",
    level: int = logging.INFO,
    msg: str = "hello",
    extra: dict[str, object] | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


class TestJsonFormatter:
    def test_basic_shape(self) -> None:
        record = _make_record()
        out = JsonFormatter().format(record)
        payload = json.loads(out)
        assert payload["level"] == "INFO"
        assert payload["logger"] == "cmcourier.test"
        assert payload["msg"] == "hello"
        assert "ts" in payload and payload["ts"].endswith("+00:00")

    def test_promotes_allowed_extras(self) -> None:
        record = _make_record(
            msg="stage_complete",
            extra={
                "pipeline": "csv-trigger",
                "stage": "S2_MAPPING",
                "batch_id": "batch_001",
                "txn_num": "TXN_001",
                "outcome": "OK",
                "duration_ms": 12.5,
                "unknown_extra": "dropped",
            },
        )
        payload = json.loads(JsonFormatter().format(record))
        assert payload["pipeline"] == "csv-trigger"
        assert payload["stage"] == "S2_MAPPING"
        assert payload["duration_ms"] == 12.5
        # Los extras desconocidos NO se promueven para mantener el esquema estable.
        assert "unknown_extra" not in payload

    def test_exception_info_serialized(self) -> None:
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys

            exc_info = sys.exc_info()
        record = _make_record()
        record.exc_info = exc_info
        payload = json.loads(JsonFormatter().format(record))
        assert payload["exc_type"] == "RuntimeError"
        assert payload["exc_msg"] == "boom"

    def test_allowed_fields_constant_includes_core_set(self) -> None:
        # Guarda de sanidad: cambios futuros de esquema no deberían
        # tirar estos campos en silencio.
        required = {"pipeline", "stage", "batch_id", "txn_num", "outcome", "duration_ms"}
        assert required <= ALLOWED_EXTRA_FIELDS


class TestPiiMaskingFilter:
    def test_denylist_masks_cif(self) -> None:
        record = _make_record(extra={"cif": "123456", "txn_num": "TXN_001"})
        PiiMaskingFilter().filter(record)
        assert record.__dict__["cif"] == MASK
        # Campo no-PII intacto.
        assert record.__dict__["txn_num"] == "TXN_001"

    def test_pii_prefix_masks(self) -> None:
        record = _make_record(extra={"pii_card_number": "4111-1111-1111-1111"})
        PiiMaskingFilter().filter(record)
        assert record.__dict__["pii_card_number"] == MASK

    def test_case_insensitive_match(self) -> None:
        record = _make_record(extra={"CIF": "999", "Customer_Name": "Doe"})
        PiiMaskingFilter().filter(record)
        assert record.__dict__["CIF"] == MASK
        assert record.__dict__["Customer_Name"] == MASK

    def test_logger_name_not_masked(self) -> None:
        # Regresión: ``name`` es un atributo built-in del `LogRecord`
        # (el nombre del logger). Enmascararlo corrompería la identidad
        # del logger Y dispararía una recursión infinita de
        # `audit-log`. En su lugar, usar `customer_name` / `nombre`
        # para el campo de nombre del cliente.
        record = _make_record(name="cmcourier.adapters.upload.cmis_uploader")
        PiiMaskingFilter().filter(record)
        assert record.name == "cmcourier.adapters.upload.cmis_uploader"

    def test_non_pii_fields_passthrough(self) -> None:
        record = _make_record(
            extra={
                "pipeline": "csv-trigger",
                "stage": "S0_TRIGGER",
                "duration_ms": 1.5,
            }
        )
        PiiMaskingFilter().filter(record)
        assert record.__dict__["pipeline"] == "csv-trigger"
        assert record.__dict__["stage"] == "S0_TRIGGER"
        assert record.__dict__["duration_ms"] == 1.5

    def test_filter_always_returns_true(self) -> None:
        # El filtro no debe descartar registros — solo mutar campos.
        record = _make_record(extra={"cif": "999"})
        assert PiiMaskingFilter().filter(record) is True

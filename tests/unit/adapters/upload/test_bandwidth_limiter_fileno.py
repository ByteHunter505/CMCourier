"""Tests del fileno() del BandwidthLimiter + integración con MultipartEncoder (080).

Bug productivo: pre-080 cuando ``cmis.max_bandwidth_mbps > 0`` el
stream pasaba envuelto en ``BandwidthLimiter`` al ``MultipartEncoder``
del 076. Como ``BandwidthLimiter`` no exponía ``fileno()``,
``requests_toolbelt.total_len()`` devolvía ``None`` y la suma
``len(headers) + total_len(body)`` del encoder explotaba con
``TypeError: unsupported operand +: int + None``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from requests_toolbelt import MultipartEncoder

from cmcourier.adapters.upload.cmis_uploader import BandwidthLimiter, TokenBucket

pytestmark = pytest.mark.unit


class TestBandwidthLimiterFileno:
    def test_fileno_delegates_to_underlying_stream(self, tmp_path: Path) -> None:
        p = tmp_path / "x.bin"
        p.write_bytes(b"hello world")
        with p.open("rb") as fh:
            wrapped = BandwidthLimiter(fh, TokenBucket(mbps=0.0))
            assert wrapped.fileno() == fh.fileno()


class TestMultipartEncoderIntegration:
    """Regression del bug 080: el encoder ahora puede medir el body
    cuando el file part es un BandwidthLimiter."""

    def test_encoder_len_is_positive_with_bandwidth_limited_stream(self, tmp_path: Path) -> None:
        p = tmp_path / "doc.pdf"
        body_size = 4096
        p.write_bytes(b"%PDF-1.4\n" + b"\x00" * (body_size - 9))
        with p.open("rb") as fh:
            wrapped = BandwidthLimiter(fh, TokenBucket(mbps=0.0))
            encoder = MultipartEncoder(
                fields={
                    "cmisaction": "createDocument",
                    "content": ("doc.pdf", wrapped, "application/pdf"),
                }
            )
            # Pre-080 esto tiraba TypeError. Ahora encoder.len es int positivo.
            assert isinstance(encoder.len, int)
            assert encoder.len > body_size  # body + headers de multipart

    def test_encoder_does_not_raise_with_throttled_stream(self, tmp_path: Path) -> None:
        # Caso real: con throttle activo (mbps > 0).
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"%PDF-1.4\n" + b"\x00" * 1024)
        bucket = TokenBucket(mbps=10.0)  # 10 MB/s throttle activo
        with p.open("rb") as fh:
            wrapped = BandwidthLimiter(fh, bucket)
            # No tira TypeError — éste es el bug 080.
            encoder = MultipartEncoder(fields={"content": ("doc.pdf", wrapped, "application/pdf")})
            assert encoder.content_type.startswith("multipart/form-data; boundary=")

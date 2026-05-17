"""Tests unitarios para el body multipart streaming de S5 (076).

Pre-076 ``httpx.Client.post(files={...})`` buffeaba el body multipart
entero en memoria antes de transmitir el primer byte. El legacy
(pre-060) con ``requests-toolbelt.MultipartEncoder`` stream-eaba
directo del disco al socket TCP. Spec 076 trae ese comportamiento
de vuelta usando ``MultipartEncoder`` con ``httpx.Client.post(content=...)``.

Estos tests no validan throughput (eso es integración) — validan que:
1. el body se construye con ``MultipartEncoder``, no con ``files=``;
2. el ``Content-Type`` y ``Content-Length`` correctos viajan en los headers;
3. los campos CMIS esperados están en el body;
4. el contenido del archivo no se buffeea entero antes del POST.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmcourier.adapters.upload.cmis_uploader import (
    CmisConfig,
    CmisUploader,
)
from cmcourier.domain.models import StagedFile

pytestmark = pytest.mark.unit


def _make_uploader(tmp_path: Path, *, base_url: str = "http://cm.test/cmis") -> CmisUploader:
    cfg = CmisConfig(
        base_url=base_url,
        repo_id="repo",
        username="u",
        password="p",
        timeout_seconds=30.0,
        verify_ssl=False,
        max_bandwidth_mbps=0.0,
        retry_max_attempts=1,
        retry_base_delay_s=0.01,
        pool_size=4,
        unmask_pii=False,
    )
    return CmisUploader(cfg)


def _make_staged_file(tmp_path: Path, *, content: bytes = b"x" * 1024) -> StagedFile:
    p = tmp_path / "test-doc.pdf"
    p.write_bytes(content)
    return StagedFile(path=p, size_bytes=len(content), page_count=1)


def _fake_201(object_id: str = "cmis:objid-123") -> Any:
    """Fake httpx Response con shape mínima que el uploader necesita."""
    resp = MagicMock()
    resp.status_code = 201
    resp.json.return_value = {
        "succinctProperties": {"cmis:objectId": object_id},
    }
    resp.text = '{"succinctProperties":{"cmis:objectId":"' + object_id + '"}}'
    return resp


class TestMultipartEncoderUsage:
    """076: el POST debe usar ``content=`` con un iterator del encoder,
    no ``data=``/``files=`` (que buffeaba en RAM)."""

    def test_post_uses_content_not_files_or_data(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {"repositoryId": "repo"}
            return r

        def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            captured["url"] = url
            return _fake_201()

        monkeypatch.setattr("httpx.Client.get", fake_get)
        monkeypatch.setattr("httpx.Client.post", fake_post)

        uploader = _make_uploader(tmp_path)
        staged = _make_staged_file(tmp_path)
        uploader.upload(
            file=staged,
            folder_path="Cuentas/TestFolder",
            object_type_id="cmis:document",
            document_name="test.pdf",
            mime_type="application/pdf",
            properties={"BAC_CIF": "12345"},
            batch_id="b1",
        )

        # 076: el POST usa content=, no data=/files=
        assert "content" in captured, "Expected content= in post kwargs"
        assert "files" not in captured, "files= would defeat streaming"
        assert "data" not in captured, "data= would defeat streaming"

    def test_content_type_header_is_multipart_from_encoder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {"repositoryId": "repo"}
            return r

        def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _fake_201()

        monkeypatch.setattr("httpx.Client.get", fake_get)
        monkeypatch.setattr("httpx.Client.post", fake_post)

        uploader = _make_uploader(tmp_path)
        staged = _make_staged_file(tmp_path)
        uploader.upload(
            file=staged,
            folder_path="F",
            object_type_id="cmis:document",
            document_name="x.pdf",
            mime_type="application/pdf",
            properties={},
            batch_id="b1",
        )

        headers = captured.get("headers", {})
        ct = headers.get("Content-Type", "")
        assert ct.startswith("multipart/form-data; boundary="), (
            f"Expected multipart/form-data with boundary, got: {ct!r}"
        )
        # Content-Length debe estar presente y ser > size_bytes del archivo
        # (incluye headers + boundaries del multipart).
        cl = headers.get("Content-Length", "")
        assert cl.isdigit() and int(cl) > staged.size_bytes

    def test_content_is_iterable_for_streaming(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # El content que pasamos a httpx debe ser un iterable lazy
        # — no bytes ni str. Si fuera bytes/str, httpx lo lee entero
        # en memoria (lo que estamos tratando de evitar).
        # Drenamos el iterable adentro del mock (mientras el file
        # handle aún está abierto).
        snapshot: dict[str, Any] = {}

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {"repositoryId": "repo"}
            return r

        def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
            content = kwargs.get("content")
            snapshot["content_type"] = type(content)
            snapshot["is_bytes"] = isinstance(content, (bytes, bytearray, str))
            # Drenar para confirmar que produce bytes chunks (con el
            # file aún abierto del with del adapter).
            first = next(iter(content), None) if content is not None else None
            snapshot["first_chunk_type"] = type(first) if first is not None else None
            return _fake_201()

        monkeypatch.setattr("httpx.Client.get", fake_get)
        monkeypatch.setattr("httpx.Client.post", fake_post)

        uploader = _make_uploader(tmp_path)
        staged = _make_staged_file(tmp_path)
        uploader.upload(
            file=staged,
            folder_path="F",
            object_type_id="cmis:document",
            document_name="x.pdf",
            mime_type="application/pdf",
            properties={},
            batch_id="b1",
        )

        assert not snapshot["is_bytes"], (
            "content should be a lazy iterable, not pre-buffered bytes/str "
            f"(got {snapshot['content_type']})"
        )
        assert snapshot["first_chunk_type"] is bytes, (
            f"Expected first chunk to be bytes, got {snapshot['first_chunk_type']}"
        )


class TestMultipartBodyContents:
    """076: validar que el body multipart contiene los campos CMIS
    esperados, en el orden esperado."""

    def test_encoder_includes_cmisaction_and_properties(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Drenamos el iterable adentro del fake_post — con el file
        # handle aún abierto del ``with`` del adapter.
        captured_body: dict[str, bytes] = {}

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {"repositoryId": "repo"}
            return r

        def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
            content = kwargs.get("content")
            captured_body["body"] = b"".join(content) if content is not None else b""
            return _fake_201()

        monkeypatch.setattr("httpx.Client.get", fake_get)
        monkeypatch.setattr("httpx.Client.post", fake_post)

        uploader = _make_uploader(tmp_path)
        staged = _make_staged_file(tmp_path, content=b"PDF_BYTES_HERE")
        uploader.upload(
            file=staged,
            folder_path="F",
            object_type_id="$t!-2_BAC_DocumentoIdentidad-v1",
            document_name="RV12345.pdf",
            mime_type="application/pdf",
            properties={"BAC_CIF": "12345", "BAC_Nombre": "JUAN"},
            batch_id="b1",
        )

        body = captured_body["body"]
        body_str = body.decode("utf-8", errors="replace")

        assert "cmisaction" in body_str
        assert "createDocument" in body_str
        assert "cmis:objectTypeId" in body_str
        assert "$t!-2_BAC_DocumentoIdentidad-v1" in body_str
        assert "cmis:name" in body_str
        assert "RV12345.pdf" in body_str
        assert "BAC_CIF" in body_str
        assert "12345" in body_str
        assert "BAC_Nombre" in body_str
        assert "JUAN" in body_str
        # El contenido del archivo está embebido en el multipart.
        assert b"PDF_BYTES_HERE" in body


class TestRetryRebuildsEncoder:
    """076: en cada retry, el encoder se reconstruye después de ``stream.seek(0)``.
    Un encoder consumido no es reutilizable — el rebuild es necesario.
    """

    def test_retry_after_500_rebuilds_encoder_and_resends_full_body(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bodies_sent: list[bytes] = []
        call_count = {"n": 0}

        def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {"repositoryId": "repo"}
            return r

        def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
            call_count["n"] += 1
            # Drenar el iterable y capturar bytes.
            content = kwargs.get("content")
            body = b"".join(content) if content is not None else b""
            bodies_sent.append(body)
            # Primer intento: 500. Segundo: 201.
            if call_count["n"] == 1:
                r = MagicMock()
                r.status_code = 500
                r.text = "internal server error"
                return r
            return _fake_201()

        monkeypatch.setattr("httpx.Client.get", fake_get)
        monkeypatch.setattr("httpx.Client.post", fake_post)

        cfg = CmisConfig(
            base_url="http://cm.test/cmis",
            repo_id="repo",
            username="u",
            password="p",
            timeout_seconds=30.0,
            verify_ssl=False,
            max_bandwidth_mbps=0.0,
            retry_max_attempts=3,  # permite al menos un retry
            retry_base_delay_s=0.001,  # rápido para test
            pool_size=4,
            unmask_pii=False,
        )
        uploader = CmisUploader(cfg)
        staged = _make_staged_file(tmp_path, content=b"FULL_BODY_BYTES")
        uploader.upload(
            file=staged,
            folder_path="F",
            object_type_id="cmis:document",
            document_name="x.pdf",
            mime_type="application/pdf",
            properties={},
            batch_id="b1",
        )

        assert call_count["n"] == 2, "expected one retry after 500"
        assert len(bodies_sent) == 2
        # Ambos bodies deben contener el archivo completo — el encoder
        # se reconstruyó después del seek(0), no quedó consumido.
        assert b"FULL_BODY_BYTES" in bodies_sent[0]
        assert b"FULL_BODY_BYTES" in bodies_sent[1]
        # Y deben ser equivalentes en tamaño (los boundaries multipart
        # difieren porque cada encoder genera su propio boundary, así
        # que comparamos tamaño).
        assert abs(len(bodies_sent[0]) - len(bodies_sent[1])) < 200

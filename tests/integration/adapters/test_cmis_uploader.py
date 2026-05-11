"""Integration tests for :class:`CmisUploader`.

Exercises the adapter end-to-end against the real ``requests`` library,
with the network stubbed by the ``responses`` library (Constitution
Principle VI: no mocking of ``requests`` internals — only the network).

The retry-policy tests monkey-patch ``time.sleep`` inside the cmis_uploader
module's namespace so retries do not actually wait. The bandwidth limiter
test uses the real ``time.sleep`` because it asserts on elapsed time.
"""

from __future__ import annotations

import dataclasses
import io
import logging
import time
from pathlib import Path
from typing import Any

import pytest
import requests
import responses

from cmcourier.adapters.upload.cmis_uploader import (
    BandwidthLimiter,
    CmisConfig,
    CmisUploader,
)
from cmcourier.domain.exceptions import (
    CMISClientError,
    CMISServerError,
    RetriesExhaustedError,
)
from cmcourier.domain.models import StagedFile

pytestmark = pytest.mark.integration

_BASE_URL = "http://cmis.example.test:9080/opencmcmis/browser"
_REPO_ID = "$x!testrepo"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> CmisConfig:
    defaults: dict[str, Any] = {
        "base_url": _BASE_URL,
        "repo_id": _REPO_ID,
        "username": "tester",
        "password": "secret-not-real",
        "timeout_seconds": 5.0,
        "verify_ssl": False,
        "max_bandwidth_mbps": 0.0,
        "retry_max_attempts": 3,
        "retry_base_delay_s": 0.0,
    }
    defaults.update(overrides)
    return CmisConfig(**defaults)


def _make_staged(tmp_path: Path, *, size_bytes: int = 1024) -> StagedFile:
    """Write a synthetic PDF and return a :class:`StagedFile`."""
    path = tmp_path / "TXN0000001.pdf"
    body = b"%PDF-1.4\n" + (b"x" * max(0, size_bytes - 9))
    path.write_bytes(body)
    return StagedFile(path=path, size_bytes=path.stat().st_size, page_count=1)


def _repo_info_url() -> str:
    return f"{_BASE_URL}/{_REPO_ID}"


def _root_url(folder_path: str = "") -> str:
    suffix = f"/{folder_path}" if folder_path else ""
    return f"{_BASE_URL}/{_REPO_ID}/root{suffix}"


def _stub_warmup() -> None:
    """Register a successful repositoryInfo response."""
    responses.add(
        responses.GET,
        _repo_info_url(),
        json={
            "repositoryId": _REPO_ID,
            "productName": "IBM Content Manager",
            "productVersion": "8.7",
            "vendorName": "IBM",
        },
        status=200,
        match=[responses.matchers.query_param_matcher({"cmisselector": "repositoryInfo"})],
    )


def _skip_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cmcourier.adapters.upload.cmis_uploader.time.sleep",
        lambda _seconds: None,
    )


# ---------------------------------------------------------------------------
# Group 1 — CmisConfig
# ---------------------------------------------------------------------------


class TestCmisConfig:
    def test_default_field_values(self) -> None:
        cfg = CmisConfig(
            base_url=_BASE_URL,
            repo_id=_REPO_ID,
            username="u",
            password="p",
        )
        assert cfg.timeout_seconds == 300.0
        assert cfg.verify_ssl is False
        assert cfg.max_bandwidth_mbps == 0.0
        assert cfg.retry_max_attempts == 3
        assert cfg.retry_base_delay_s == 2.0

    def test_config_is_frozen(self) -> None:
        cfg = _make_config()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.username = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Group 2 — Warmup
# ---------------------------------------------------------------------------


class TestWarmup:
    def test_construction_makes_no_http_call(self) -> None:
        with responses.RequestsMock() as rsps:
            CmisUploader(_make_config())
            assert len(rsps.calls) == 0

    @responses.activate
    def test_warmup_runs_on_first_state_change(self, tmp_path: Path) -> None:
        _stub_warmup()
        uploader = CmisUploader(_make_config())
        uploader.test_connection()
        assert len(responses.calls) == 1
        assert "cmisselector=repositoryInfo" in responses.calls[0].request.url

    @responses.activate
    def test_warmup_5xx_raises_server_error(self) -> None:
        responses.add(
            responses.GET,
            _repo_info_url(),
            json={"error": "boom"},
            status=503,
            match=[responses.matchers.query_param_matcher({"cmisselector": "repositoryInfo"})],
        )
        uploader = CmisUploader(_make_config())
        with pytest.raises(CMISServerError) as ei:
            uploader.test_connection()
        assert ei.value.status_code == 503


# ---------------------------------------------------------------------------
# Group 3 — test_connection
# ---------------------------------------------------------------------------


class TestTestConnection:
    @responses.activate
    def test_parses_repository_info(self) -> None:
        _stub_warmup()
        uploader = CmisUploader(_make_config())
        info = uploader.test_connection()
        assert info["repository_id"] == _REPO_ID
        assert info["product_name"] == "IBM Content Manager"
        assert info["product_version"] == "8.7"
        assert info["vendor_name"] == "IBM"

    @responses.activate
    def test_missing_keys_become_empty_string(self) -> None:
        responses.add(
            responses.GET,
            _repo_info_url(),
            json={},  # all keys missing
            status=200,
            match=[responses.matchers.query_param_matcher({"cmisselector": "repositoryInfo"})],
        )
        uploader = CmisUploader(_make_config())
        info = uploader.test_connection()
        assert info["repository_id"] == ""
        assert info["product_name"] == ""

    @responses.activate
    def test_4xx_raises_client_error(self) -> None:
        responses.add(
            responses.GET,
            _repo_info_url(),
            json={"error": "unauthorized"},
            status=401,
            match=[responses.matchers.query_param_matcher({"cmisselector": "repositoryInfo"})],
        )
        uploader = CmisUploader(_make_config())
        with pytest.raises(CMISClientError) as ei:
            uploader.test_connection()
        assert ei.value.status_code == 401


# ---------------------------------------------------------------------------
# Group 4 — ensure_folder
# ---------------------------------------------------------------------------


class TestEnsureFolder:
    @responses.activate
    def test_skips_system_folders(self) -> None:
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        responses.add(
            responses.POST, _root_url("BAC_01_02_04_01_01"), json={"ok": True}, status=201
        )
        uploader = CmisUploader(_make_config())
        uploader.ensure_folder("/$type/BAC_01_02_04_01_01")
        # 1 warmup GET + 1 createFolder POST (for BAC_..., not for $type)
        post_calls = [c for c in responses.calls if c.request.method == "POST"]
        assert len(post_calls) == 1

    @responses.activate
    def test_recursive_creation_three_segments(self) -> None:
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        responses.add(responses.POST, _root_url("A"), json={"ok": True}, status=201)
        responses.add(responses.POST, _root_url("A/B"), json={"ok": True}, status=201)
        uploader = CmisUploader(_make_config())
        uploader.ensure_folder("/A/B/C")
        post_calls = [c for c in responses.calls if c.request.method == "POST"]
        assert len(post_calls) == 3

    @responses.activate
    def test_cache_prevents_repost(self) -> None:
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        responses.add(responses.POST, _root_url("A"), json={"ok": True}, status=201)
        responses.add(responses.POST, _root_url("A/B"), json={"ok": True}, status=201)
        uploader = CmisUploader(_make_config())
        uploader.ensure_folder("/A/B/C")
        first_pass = sum(1 for c in responses.calls if c.request.method == "POST")
        uploader.ensure_folder("/A/B/C")
        second_pass_extra = (
            sum(1 for c in responses.calls if c.request.method == "POST") - first_pass
        )
        assert first_pass == 3
        assert second_pass_extra == 0

    @responses.activate
    def test_409_treated_as_success(self) -> None:
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"err": "conflict"}, status=409)
        uploader = CmisUploader(_make_config())
        uploader.ensure_folder("/EXISTS")  # must not raise

    @responses.activate
    def test_path_cached_after_409(self) -> None:
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"err": "conflict"}, status=409)
        uploader = CmisUploader(_make_config())
        uploader.ensure_folder("/EXISTS")
        before = sum(1 for c in responses.calls if c.request.method == "POST")
        uploader.ensure_folder("/EXISTS")
        after = sum(1 for c in responses.calls if c.request.method == "POST")
        assert after == before  # second call short-circuits via cache


# ---------------------------------------------------------------------------
# Group 5 — Upload happy path
# ---------------------------------------------------------------------------


class TestUploadHappyPath:
    @responses.activate
    def test_succinct_properties_object_id(self, tmp_path: Path) -> None:
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        responses.add(
            responses.POST,
            _root_url("BAC_X"),
            json={"succinctProperties": {"cmis:objectId": "abc-123"}},
            status=201,
        )
        uploader = CmisUploader(_make_config())
        result = uploader.upload(
            file=_make_staged(tmp_path),
            folder_path="/BAC_X",
            object_type_id="$t!-2_BAC_Xv-1",
            document_name="TXN0000001.pdf",
            mime_type="application/pdf",
            properties={"clbNonGroup.BAC_CIF": "000000"},
        )
        assert result == "abc-123"

    @responses.activate
    def test_standard_properties_object_id_fallback(self, tmp_path: Path) -> None:
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        responses.add(
            responses.POST,
            _root_url("BAC_Y"),
            json={"properties": {"cmis:objectId": {"value": "def-456"}}},
            status=201,
        )
        uploader = CmisUploader(_make_config())
        result = uploader.upload(
            file=_make_staged(tmp_path),
            folder_path="/BAC_Y",
            object_type_id="t",
            document_name="TXN0000002.pdf",
            mime_type="application/pdf",
            properties={},
        )
        assert result == "def-456"

    @responses.activate
    def test_id_field_object_id_fallback(self, tmp_path: Path) -> None:
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        responses.add(
            responses.POST,
            _root_url("BAC_Z"),
            json={"id": "ghi-789"},
            status=201,
        )
        uploader = CmisUploader(_make_config())
        result = uploader.upload(
            file=_make_staged(tmp_path),
            folder_path="/BAC_Z",
            object_type_id="t",
            document_name="TXN0000003.pdf",
            mime_type="application/pdf",
            properties={},
        )
        assert result == "ghi-789"

    @responses.activate
    def test_content_type_is_multipart(self, tmp_path: Path) -> None:
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        responses.add(
            responses.POST,
            _root_url("BAC_X"),
            json={"succinctProperties": {"cmis:objectId": "id"}},
            status=201,
        )
        uploader = CmisUploader(_make_config())
        uploader.upload(
            file=_make_staged(tmp_path),
            folder_path="/BAC_X",
            object_type_id="t",
            document_name="TXN0000004.pdf",
            mime_type="application/pdf",
            properties={},
        )
        upload_call = responses.calls[-1]
        assert upload_call.request.headers["Content-Type"].startswith(
            "multipart/form-data; boundary="
        )


# ---------------------------------------------------------------------------
# Group 6 — Retry policy
# ---------------------------------------------------------------------------


class TestUploadRetry:
    @responses.activate
    def test_5xx_then_201(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _skip_sleep(monkeypatch)
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        responses.add(responses.POST, _root_url("BAC_R"), json={}, status=503)
        responses.add(responses.POST, _root_url("BAC_R"), json={}, status=503)
        responses.add(
            responses.POST,
            _root_url("BAC_R"),
            json={"succinctProperties": {"cmis:objectId": "ok"}},
            status=201,
        )
        uploader = CmisUploader(_make_config(retry_max_attempts=3))
        result = uploader.upload(
            file=_make_staged(tmp_path),
            folder_path="/BAC_R",
            object_type_id="t",
            document_name="TXN0000010.pdf",
            mime_type="application/pdf",
            properties={},
        )
        assert result == "ok"
        upload_attempts = [c for c in responses.calls if c.request.url.endswith("/BAC_R")]
        assert len(upload_attempts) == 3

    @responses.activate
    def test_4xx_fail_fast(self, tmp_path: Path) -> None:
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        responses.add(responses.POST, _root_url("BAC_F"), json={"err": "bad"}, status=400)
        uploader = CmisUploader(_make_config())
        with pytest.raises(CMISClientError) as ei:
            uploader.upload(
                file=_make_staged(tmp_path),
                folder_path="/BAC_F",
                object_type_id="t",
                document_name="TXN0000011.pdf",
                mime_type="application/pdf",
                properties={},
            )
        assert ei.value.status_code == 400
        upload_attempts = [c for c in responses.calls if c.request.url.endswith("/BAC_F")]
        assert len(upload_attempts) == 1

    @responses.activate
    def test_401_rewarms_and_retries_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _skip_sleep(monkeypatch)
        _stub_warmup()  # initial warmup
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        responses.add(responses.POST, _root_url("BAC_A"), json={}, status=401)
        _stub_warmup()  # re-warmup
        responses.add(
            responses.POST,
            _root_url("BAC_A"),
            json={"succinctProperties": {"cmis:objectId": "ok"}},
            status=201,
        )
        uploader = CmisUploader(_make_config(retry_max_attempts=3))
        result = uploader.upload(
            file=_make_staged(tmp_path),
            folder_path="/BAC_A",
            object_type_id="t",
            document_name="TXN0000012.pdf",
            mime_type="application/pdf",
            properties={},
        )
        assert result == "ok"
        warmup_calls = [c for c in responses.calls if c.request.method == "GET"]
        assert len(warmup_calls) == 2

    @responses.activate
    def test_retries_exhausted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _skip_sleep(monkeypatch)
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        for _ in range(5):
            responses.add(responses.POST, _root_url("BAC_E"), json={}, status=503)
        uploader = CmisUploader(_make_config(retry_max_attempts=3))
        with pytest.raises(RetriesExhaustedError) as ei:
            uploader.upload(
                file=_make_staged(tmp_path),
                folder_path="/BAC_E",
                object_type_id="t",
                document_name="TXN0000013.pdf",
                mime_type="application/pdf",
                properties={},
            )
        assert ei.value.attempts == 3
        assert isinstance(ei.value.__cause__, CMISServerError)


# ---------------------------------------------------------------------------
# Group 7 — Windows 10053
# ---------------------------------------------------------------------------


class TestUploadWindows10053:
    def test_10053_doubles_delay_and_logs_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        captured_delays: list[float] = []
        monkeypatch.setattr(
            "cmcourier.adapters.upload.cmis_uploader.time.sleep",
            lambda s: captured_delays.append(s),
        )

        @responses.activate
        def _run() -> str:
            _stub_warmup()
            responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
            responses.add(
                responses.POST,
                _root_url("BAC_W"),
                body=requests.exceptions.ConnectionError("WSA error 10053"),
            )
            responses.add(
                responses.POST,
                _root_url("BAC_W"),
                json={"succinctProperties": {"cmis:objectId": "ok"}},
                status=201,
            )
            uploader = CmisUploader(_make_config(retry_base_delay_s=1.0))
            with caplog.at_level(logging.ERROR, logger="cmcourier.adapters.upload.cmis_uploader"):
                return uploader.upload(
                    file=_make_staged(tmp_path),
                    folder_path="/BAC_W",
                    object_type_id="t",
                    document_name="TXN0000020.pdf",
                    mime_type="application/pdf",
                    properties={},
                )

        result = _run()
        assert result == "ok"
        # 10053 sleep is doubled: base 1.0 * 2^0 * 2 = 2.0
        assert any(s >= 2.0 for s in captured_delays), captured_delays
        assert any("10053" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Group 8 — BandwidthLimiter
# ---------------------------------------------------------------------------


class TestBandwidthLimiter:
    def test_throttles_to_configured_rate(self, tmp_path: Path) -> None:
        size = 1_000_000  # 1 MB
        path = tmp_path / "blob.bin"
        path.write_bytes(b"x" * size)
        # 0.5 MB/s on 1 MB ≈ 2.0 s nominal.
        with path.open("rb") as fh:
            limiter = BandwidthLimiter(fh, mbps=0.5)
            start = time.monotonic()
            consumed = 0
            while True:
                chunk = limiter.read(100_000)
                if not chunk:
                    break
                consumed += len(chunk)
            elapsed = time.monotonic() - start
        assert consumed == size
        assert 1.5 < elapsed < 3.0, elapsed

    def test_mbps_zero_passes_through(self) -> None:
        stream = io.BytesIO(b"abcdef")
        limiter = BandwidthLimiter(stream, mbps=0.0)
        start = time.monotonic()
        data = limiter.read(6)
        elapsed = time.monotonic() - start
        assert data == b"abcdef"
        assert elapsed < 0.1  # no throttling

    def test_passthrough_methods(self) -> None:
        stream = io.BytesIO(b"abcdef")
        limiter = BandwidthLimiter(stream, mbps=10.0)
        assert limiter.tell() == 0
        limiter.read(3)
        assert limiter.tell() == 3
        limiter.seek(0)
        assert limiter.tell() == 0
        limiter.close()
        assert stream.closed


# ---------------------------------------------------------------------------
# Group 9 — Logging discipline (Constitution VIII)
# ---------------------------------------------------------------------------


class TestLoggingDiscipline:
    @responses.activate
    def test_retry_log_carries_keys_not_values(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _skip_sleep(monkeypatch)
        _stub_warmup()
        responses.add(responses.POST, _root_url(""), json={"ok": True}, status=201)
        responses.add(responses.POST, _root_url("BAC_L"), json={}, status=503)
        responses.add(
            responses.POST,
            _root_url("BAC_L"),
            json={"succinctProperties": {"cmis:objectId": "ok"}},
            status=201,
        )
        uploader = CmisUploader(_make_config(retry_max_attempts=3))
        sensitive = "BAC_VALUE_THAT_MUST_NOT_LEAK_999999"
        with caplog.at_level(logging.INFO, logger="cmcourier.adapters.upload.cmis_uploader"):
            uploader.upload(
                file=_make_staged(tmp_path),
                folder_path="/BAC_L",
                object_type_id="t",
                document_name="TXN0000030.pdf",
                mime_type="application/pdf",
                properties={"clbNonGroup.BAC_CIF": sensitive},
            )
        for record in caplog.records:
            assert sensitive not in record.getMessage()
            assert sensitive not in str(record.__dict__.get("extra", ""))


# ---------------------------------------------------------------------------
# Group 10 — get_type_definition (REBIRTH §10.5 pre-flight)
# ---------------------------------------------------------------------------


class TestGetTypeDefinition:
    @responses.activate
    def test_200_returns_parsed_dict(self) -> None:
        _stub_warmup()
        responses.add(
            responses.GET,
            _repo_info_url(),
            json={"id": "$t!-2_BAC_01_02_04_01_01v-1", "displayName": "Auth SMS"},
            status=200,
            match=[
                responses.matchers.query_param_matcher(
                    {
                        "cmisselector": "typeDefinition",
                        "typeId": "$t!-2_BAC_01_02_04_01_01v-1",
                    }
                )
            ],
        )
        uploader = CmisUploader(_make_config())
        result = uploader.get_type_definition("$t!-2_BAC_01_02_04_01_01v-1")
        assert result["id"] == "$t!-2_BAC_01_02_04_01_01v-1"
        assert result["displayName"] == "Auth SMS"

    @responses.activate
    def test_404_raises_client_error(self) -> None:
        _stub_warmup()
        responses.add(
            responses.GET,
            _repo_info_url(),
            json={"error": "type not found"},
            status=404,
            match=[
                responses.matchers.query_param_matcher(
                    {"cmisselector": "typeDefinition", "typeId": "MISSING"}
                )
            ],
        )
        uploader = CmisUploader(_make_config())
        with pytest.raises(CMISClientError) as ei:
            uploader.get_type_definition("MISSING")
        assert ei.value.status_code == 404

    @responses.activate
    def test_500_raises_server_error(self) -> None:
        _stub_warmup()
        responses.add(
            responses.GET,
            _repo_info_url(),
            json={"error": "boom"},
            status=500,
            match=[
                responses.matchers.query_param_matcher(
                    {"cmisselector": "typeDefinition", "typeId": "X"}
                )
            ],
        )
        uploader = CmisUploader(_make_config())
        with pytest.raises(CMISServerError) as ei:
            uploader.get_type_definition("X")
        assert ei.value.status_code == 500


# ---------------------------------------------------------------------------
# Port conformance (019, Constitution I)
# ---------------------------------------------------------------------------


class TestPortConformance:
    def test_cmis_uploader_is_iuploader(self) -> None:
        from cmcourier.domain.ports import IUploader

        uploader = CmisUploader(_make_config())
        assert isinstance(uploader, IUploader)

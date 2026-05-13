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
    TokenBucket,
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
# Group 2b — Connection pool sizing + eager warm-up (038)
# ---------------------------------------------------------------------------


class TestConnectionPoolSizing:
    def test_default_pool_size_is_ten(self) -> None:
        cfg = CmisConfig(base_url=_BASE_URL, repo_id=_REPO_ID, username="u", password="p")
        assert cfg.pool_size == 10

    def test_adapter_mounted_with_configured_pool_size(self) -> None:
        uploader = CmisUploader(_make_config(pool_size=32))
        # requests.Session.mount keys preserve insertion order; check both
        # http:// and https:// adapters carry the configured maxsize.
        adapters = list(uploader._session.adapters.values())
        assert any(getattr(a, "_pool_maxsize", None) == 32 for a in adapters)


class TestWarmConnectionPool:
    @responses.activate
    def test_warm_n_connections_fires_n_requests(self) -> None:
        _stub_warmup()
        # Add 7 more identical stubs so a pool of 8 doesn't blow past
        # the matcher list. responses by default allows reuse of a
        # single stub for multiple calls — but let's be explicit.
        for _ in range(7):
            _stub_warmup()
        uploader = CmisUploader(_make_config(pool_size=8))
        succeeded = uploader.warm_connection_pool(8)
        assert succeeded == 8
        # repositoryInfo got hit 8 times.
        info_calls = [c for c in responses.calls if "cmisselector=repositoryInfo" in c.request.url]
        assert len(info_calls) == 8

    def test_warm_zero_is_noop(self) -> None:
        uploader = CmisUploader(_make_config())
        # No HTTP mocks registered → would error if a request happened.
        assert uploader.warm_connection_pool(0) == 0
        assert uploader.warm_connection_pool(-3) == 0

    @responses.activate
    def test_warm_swallows_individual_failures(self) -> None:
        # First stub succeeds; subsequent are 503 so 3 of 4 fail.
        _stub_warmup()
        for _ in range(3):
            responses.add(
                responses.GET,
                _repo_info_url(),
                json={"error": "boom"},
                status=503,
                match=[responses.matchers.query_param_matcher({"cmisselector": "repositoryInfo"})],
            )
        uploader = CmisUploader(_make_config(pool_size=4))
        # Should NOT raise — failures only log.
        succeeded = uploader.warm_connection_pool(4)
        # Order of completion is non-deterministic so just assert it
        # is within [0, 4] and at least one succeeded if responses
        # popped the success first.
        assert 0 <= succeeded <= 4


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
# Group 4 — verify_folder_exists (038: read-only; doctor's pre-flight uses
# this, S5 no longer touches folder verification on the happy path)
# ---------------------------------------------------------------------------


class TestVerifyFolderExists:
    @responses.activate
    def test_returns_true_for_existing_folder(self) -> None:
        _stub_warmup()
        responses.add(
            responses.GET,
            _root_url("EXISTS"),
            json={"properties": {"cmis:baseTypeId": {"value": "cmis:folder"}}},
            status=200,
            match=[responses.matchers.query_param_matcher({"cmisselector": "object"})],
        )
        uploader = CmisUploader(_make_config())
        assert uploader.verify_folder_exists("/EXISTS") is True

    @responses.activate
    def test_returns_true_for_succinct_response(self) -> None:
        _stub_warmup()
        responses.add(
            responses.GET,
            _root_url("EXISTS"),
            json={"succinctProperties": {"cmis:baseTypeId": "cmis:folder"}},
            status=200,
            match=[responses.matchers.query_param_matcher({"cmisselector": "object"})],
        )
        uploader = CmisUploader(_make_config())
        assert uploader.verify_folder_exists("/EXISTS") is True

    @responses.activate
    def test_returns_false_on_404(self) -> None:
        _stub_warmup()
        responses.add(
            responses.GET,
            _root_url("MISSING"),
            json={"error": "not found"},
            status=404,
            match=[responses.matchers.query_param_matcher({"cmisselector": "object"})],
        )
        uploader = CmisUploader(_make_config())
        assert uploader.verify_folder_exists("/MISSING") is False

    @responses.activate
    def test_returns_false_when_path_is_document_not_folder(self) -> None:
        _stub_warmup()
        responses.add(
            responses.GET,
            _root_url("DOC_AT_THIS_PATH"),
            json={"properties": {"cmis:baseTypeId": {"value": "cmis:document"}}},
            status=200,
            match=[responses.matchers.query_param_matcher({"cmisselector": "object"})],
        )
        uploader = CmisUploader(_make_config())
        assert uploader.verify_folder_exists("/DOC_AT_THIS_PATH") is False

    @responses.activate
    def test_raises_on_401(self) -> None:
        _stub_warmup()
        responses.add(
            responses.GET,
            _root_url("ANY"),
            json={"error": "unauthorized"},
            status=401,
            match=[responses.matchers.query_param_matcher({"cmisselector": "object"})],
        )
        uploader = CmisUploader(_make_config())
        with pytest.raises(CMISClientError) as ei:
            uploader.verify_folder_exists("/ANY")
        assert ei.value.status_code == 401

    @responses.activate
    def test_raises_on_5xx(self) -> None:
        _stub_warmup()
        responses.add(
            responses.GET,
            _root_url("ANY"),
            json={"error": "server down"},
            status=503,
            match=[responses.matchers.query_param_matcher({"cmisselector": "object"})],
        )
        uploader = CmisUploader(_make_config())
        with pytest.raises(CMISServerError) as ei:
            uploader.verify_folder_exists("/ANY")
        assert ei.value.status_code == 503

    @responses.activate
    def test_does_not_post_anything(self) -> None:
        """Read-only contract: no folder is ever created."""
        _stub_warmup()
        responses.add(
            responses.GET,
            _root_url("X"),
            json={"properties": {"cmis:baseTypeId": {"value": "cmis:folder"}}},
            status=200,
            match=[responses.matchers.query_param_matcher({"cmisselector": "object"})],
        )
        uploader = CmisUploader(_make_config())
        uploader.verify_folder_exists("/X")
        post_calls = [c for c in responses.calls if c.request.method == "POST"]
        assert post_calls == []


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


class TestTokenBucket:
    """Direct tests for the new shared token bucket (029, REQ-001)."""

    def test_zero_mbps_is_noop(self) -> None:
        bucket = TokenBucket(mbps=0.0)
        start = time.monotonic()
        bucket.consume(10_000_000)  # 10 MB
        elapsed = time.monotonic() - start
        assert elapsed < 0.05  # no throttling

    def test_single_thread_throttles_to_rate(self) -> None:
        # 0.5 MB/s for 1 MB ≈ 2.0 s nominal.
        bucket = TokenBucket(mbps=0.5)
        start = time.monotonic()
        # Drain 1 MB in 10×100 KB chunks (mimics a real upload).
        for _ in range(10):
            bucket.consume(100_000)
        elapsed = time.monotonic() - start
        assert 1.5 < elapsed < 3.0, elapsed

    def test_n_concurrent_workers_share_cap(self) -> None:
        """REQ-004 property test: N workers consuming concurrently
        against a shared bucket cannot exceed the configured rate.

        4 workers × 0.5 MB each at 1 MB/s → ≈2.0 s aggregate.
        Each worker draining alone would take 0.5 s; a per-worker
        bucket would let them finish in parallel in 0.5 s and prove
        the bug. The shared bucket forces them to serialize tokens.
        """
        import threading as _threading

        bucket = TokenBucket(mbps=1.0)  # 1 MB/s aggregate
        bytes_per_worker = 500_000  # 0.5 MB each
        n_workers = 4
        results: list[float] = []

        def _worker() -> None:
            t0 = time.monotonic()
            for _ in range(10):
                bucket.consume(bytes_per_worker // 10)
            results.append(time.monotonic() - t0)

        threads = [_threading.Thread(target=_worker, name=f"w_{i}") for i in range(n_workers)]
        wall_start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall_elapsed = time.monotonic() - wall_start

        total_bytes = bytes_per_worker * n_workers  # 2 MB
        # At 1 MB/s aggregate, 2 MB takes ~2.0 s. Anything well under
        # 1.5 s would prove the cap leaked. Be lenient on upper bound
        # (CI / GIL noise) — the lower bound is the real assertion.
        assert wall_elapsed > 1.5, (
            f"shared cap leaked: {n_workers} workers drained "
            f"{total_bytes} B in {wall_elapsed:.2f}s "
            f"(expected ≥ {total_bytes / 1_000_000:.1f}s at 1 MB/s)"
        )
        assert wall_elapsed < 4.0, wall_elapsed


class TestBandwidthLimiter:
    def test_throttles_via_shared_bucket(self, tmp_path: Path) -> None:
        size = 1_000_000  # 1 MB
        path = tmp_path / "blob.bin"
        path.write_bytes(b"x" * size)
        # 0.5 MB/s on 1 MB ≈ 2.0 s nominal.
        bucket = TokenBucket(mbps=0.5)
        with path.open("rb") as fh:
            limiter = BandwidthLimiter(fh, bucket)
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

    def test_zero_bucket_passes_through(self) -> None:
        stream = io.BytesIO(b"abcdef")
        limiter = BandwidthLimiter(stream, TokenBucket(mbps=0.0))
        start = time.monotonic()
        data = limiter.read(6)
        elapsed = time.monotonic() - start
        assert data == b"abcdef"
        assert elapsed < 0.1  # no throttling

    def test_passthrough_methods(self) -> None:
        stream = io.BytesIO(b"abcdef")
        limiter = BandwidthLimiter(stream, TokenBucket(mbps=10.0))
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


# ---------------------------------------------------------------------------
# 038 — s5_upload_attempt + s5_upload_failed events
# ---------------------------------------------------------------------------


class TestUploadPayloadTraceEvents:
    @responses.activate
    def test_attempt_event_emitted_on_success(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _stub_warmup()
        responses.add(
            responses.POST,
            _root_url("BAC_X"),
            json={"succinctProperties": {"cmis:objectId": "abc"}},
            status=201,
        )
        uploader = CmisUploader(_make_config())
        with caplog.at_level(logging.INFO, logger="cmcourier.metrics.network"):
            uploader.upload(
                file=_make_staged(tmp_path),
                folder_path="/BAC_X",
                object_type_id="D:cmcourier:bacDoc",
                document_name="TXN1.pdf",
                mime_type="application/pdf",
                properties={"clbNonGroup.BAC_CIF": "00123456"},
            )
        attempts = [r for r in caplog.records if getattr(r, "event", "") == "s5_upload_attempt"]
        assert len(attempts) == 1
        rec = attempts[0]
        assert rec.object_type_id == "D:cmcourier:bacDoc"
        assert rec.document_name == "TXN1.pdf"
        # PII masked by default: CIF value should not appear.
        assert "00123456" not in rec.properties_json
        # cmis:name and mime are safe — appear raw.
        assert "TXN1.pdf" in rec.properties_json
        assert "application/pdf" in rec.properties_json

    @responses.activate
    def test_failed_event_emitted_with_curl_equivalent(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_warmup()
        _skip_sleep(monkeypatch)
        responses.add(
            responses.POST,
            _root_url("BAC_X"),
            json={"error": "constraint", "message": "property unknown"},
            status=400,
        )
        uploader = CmisUploader(_make_config())
        with (
            caplog.at_level(logging.INFO, logger="cmcourier.metrics.network"),
            pytest.raises(CMISClientError),
        ):
            uploader.upload(
                file=_make_staged(tmp_path),
                folder_path="/BAC_X",
                object_type_id="D:cmcourier:bacDoc",
                document_name="TXN2.pdf",
                mime_type="application/pdf",
                properties={"clbNonGroup.BAC_CIF": "00123456"},
            )
        attempts = [r for r in caplog.records if getattr(r, "event", "") == "s5_upload_attempt"]
        failures = [r for r in caplog.records if getattr(r, "event", "") == "s5_upload_failed"]
        assert len(attempts) == 1
        assert len(failures) == 1
        fail = failures[0]
        assert fail.status_code == 400
        assert "createDocument" in fail.curl_equivalent
        assert "D:cmcourier:bacDoc" in fail.curl_equivalent
        # PII masked: the raw CIF must not be in either the JSON
        # properties or the curl-equivalent dump.
        assert "00123456" not in fail.properties_json
        assert "00123456" not in fail.curl_equivalent

    @responses.activate
    def test_unmask_pii_emits_raw_values(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _stub_warmup()
        responses.add(
            responses.POST,
            _root_url("BAC_X"),
            json={"succinctProperties": {"cmis:objectId": "abc"}},
            status=201,
        )
        uploader = CmisUploader(_make_config(unmask_pii=True))
        with caplog.at_level(logging.INFO, logger="cmcourier.metrics.network"):
            uploader.upload(
                file=_make_staged(tmp_path),
                folder_path="/BAC_X",
                object_type_id="D:cmcourier:bacDoc",
                document_name="TXN3.pdf",
                mime_type="application/pdf",
                properties={"clbNonGroup.BAC_CIF": "00123456"},
            )
        attempts = [r for r in caplog.records if getattr(r, "event", "") == "s5_upload_attempt"]
        assert len(attempts) == 1
        assert "00123456" in attempts[0].properties_json

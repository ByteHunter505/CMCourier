"""Stage S5 — :class:`CmisUploader` (REBIRTH §8).

Concrete :class:`IUploader` for IBM Content Manager via the CMIS Browser
Binding REST/JSON protocol. Single-threaded MVP: the adapter holds one
:class:`requests.Session` shared across all calls. A follow-up change
adds thread-local sessions when the orchestrator's worker pool lands.

Implements the full REBIRTH §8 contract:

* JSESSIONID warmup (§8.2) — lazy, runs once per session lifetime.
* Recursive folder creation with the in-memory cache and idempotent 409
  semantics (§8.3); ``$``-prefixed system folders are skipped.
* Streaming multipart upload (§8.5) via
  :class:`requests_toolbelt.MultipartEncoder`; the file is read from disk
  on demand, never buffered.
* Optional :class:`BandwidthLimiter` wrapping the file stream (§8.6) for
  throttled corporate networks.
* Retry policy (§8.7): 401 → re-warmup + retry once; 5xx → exponential
  backoff capped at 60 s; Windows-10053 connection abort → doubled
  sleep; 4xx → fail-fast :class:`CMISClientError`; retry budget
  exhausted → :class:`RetriesExhaustedError`.
* The 3-path ``cmis:objectId`` parser (§8.8).

Constitution Principle I: this module imports ``requests``,
``requests_toolbelt`` (both already declared in ``pyproject.toml``), and
the standard library. Domain models are imported as types only.
Principle VIII: logs identify operational keys (txn_num, folder_path,
HTTP status, attempt) but never property values or response bodies
beyond a truncation cap.
"""

from __future__ import annotations

__all__ = ["BandwidthLimiter", "CmisConfig", "CmisUploader"]

import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import IO, Any

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests_toolbelt import MultipartEncoder

from cmcourier.domain.exceptions import (
    CMISClientError,
    CMISServerError,
    RetriesExhaustedError,
)
from cmcourier.domain.models import StagedFile
from cmcourier.domain.ports import IUploader

_network_log = logging.getLogger("cmcourier.metrics.network")

_log = logging.getLogger(__name__)

_SYSTEM_FOLDER_PREFIX = "$"
_WINDOWS_ABORT_MARKER = "10053"
_MAX_BACKOFF_S = 60.0
_RESPONSE_BODY_TRUNCATION = 1024


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CmisConfig:
    """Connection + retry + bandwidth knobs for :class:`CmisUploader`."""

    base_url: str
    repo_id: str
    username: str
    password: str
    timeout_seconds: float = 300.0
    verify_ssl: bool = False
    max_bandwidth_mbps: float = 0.0
    retry_max_attempts: int = 3
    retry_base_delay_s: float = 2.0


# ---------------------------------------------------------------------------
# BandwidthLimiter
# ---------------------------------------------------------------------------


class BandwidthLimiter:
    """Token-bucket read throttle for a file-like stream (REBIRTH §8.6)."""

    def __init__(self, stream: IO[bytes], mbps: float) -> None:
        self._stream = stream
        self._enabled = mbps > 0
        self._rate = mbps * 1_000_000.0
        self._tokens = 0.0
        self._last_refill = time.monotonic()

    def read(self, size: int = -1) -> bytes:
        if not self._enabled:
            return self._stream.read(size)
        chunk_size = size if size >= 0 else 1 << 20
        self._wait_for_tokens(chunk_size)
        self._tokens -= chunk_size
        return self._stream.read(chunk_size)

    def _wait_for_tokens(self, needed: int) -> None:
        while self._tokens < needed:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens += elapsed * self._rate
            self._last_refill = now
            if self._tokens < needed:
                deficit = (needed - self._tokens) / self._rate
                time.sleep(deficit)

    def seek(self, *args: Any, **kwargs: Any) -> int:
        return self._stream.seek(*args, **kwargs)

    def tell(self) -> int:
        return self._stream.tell()

    def close(self) -> None:
        self._stream.close()

    @property
    def name(self) -> str:
        return str(getattr(self._stream, "name", "<bandwidth-limited>"))

    def __enter__(self) -> BandwidthLimiter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# CmisUploader
# ---------------------------------------------------------------------------


class CmisUploader(IUploader):
    """Concrete :class:`IUploader` over CMIS Browser Binding."""

    def __init__(self, config: CmisConfig) -> None:
        self._cfg = config
        self._session = requests.Session()
        self._session.auth = (config.username, config.password)
        self._session.verify = config.verify_ssl
        self._folder_cache: set[str] = set()
        self._warm = False
        # 025: S5 worker pool calls upload/ensure_folder concurrently.
        # The per-instance state above is shared across worker threads.
        self._folder_lock = threading.Lock()
        self._warm_lock = threading.Lock()
        # 025 phase 2: the AIMD auto-tune controller may adjust the
        # request timeout mid-batch. CmisConfig itself is frozen, so we
        # keep the live value here. Request paths consult this property
        # via ``self._timeout_s``; defaults to the configured value.
        self._timeout_s: float = float(config.timeout_seconds)

    # ----------------------------------------------------------- public API

    def test_connection(self) -> Mapping[str, str]:
        """GET repositoryInfo, return a small diagnostics dict."""
        data = self._warmup_session()
        return {
            "repository_id": str(data.get("repositoryId", "")),
            "product_name": str(data.get("productName", "")),
            "product_version": str(data.get("productVersion", "")),
            "vendor_name": str(data.get("vendorName", "")),
        }

    def get_type_definition(self, object_type_id: str) -> Mapping[str, Any]:
        """GET cmisselector=typeDefinition&typeId=<id>. Bypasses the retry loop."""
        with self._warm_lock:
            need_warmup = not self._warm
        if need_warmup:
            self._warmup_session()
        url = f"{self._cfg.base_url}/{self._cfg.repo_id}"
        t0 = time.monotonic()
        resp = self._session.get(
            url,
            params={"cmisselector": "typeDefinition", "typeId": object_type_id},
            timeout=self._timeout_s,
        )
        _network_log.info(
            "cmis_get",
            extra={
                "kind": "cmis_get",
                "duration_ms": round((time.monotonic() - t0) * 1000.0, 3),
                "status": resp.status_code,
                "url_prefix": url[:80],
                "worker": threading.current_thread().name,
            },
        )
        body = _truncate(resp.text)
        if resp.status_code >= 500:
            raise CMISServerError(status_code=resp.status_code, response_body=body)
        if resp.status_code >= 400:
            raise CMISClientError(status_code=resp.status_code, response_body=body)
        try:
            data = resp.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def ensure_folder(self, folder_path: str) -> None:
        """Create ``folder_path`` recursively. Idempotent + cached.

        Thread-safe (025): two workers racing on the same folder hit
        the cache check inside the lock; only one issues the POST.
        Repeat POSTs across workers for different paths are fine —
        the CMIS endpoint returns 409 which we treat as success.
        """
        segments = [
            s for s in folder_path.split("/") if s and not s.startswith(_SYSTEM_FOLDER_PREFIX)
        ]
        parent = ""
        for seg in segments:
            abs_path = f"{parent}/{seg}".lstrip("/") if parent else seg
            with self._folder_lock:
                if abs_path in self._folder_cache:
                    parent = abs_path
                    continue
            self._create_folder_segment(parent, seg)
            with self._folder_lock:
                self._folder_cache.add(abs_path)
            parent = abs_path

    def upload(
        self,
        file: StagedFile,
        folder_path: str,
        object_type_id: str,
        document_name: str,
        mime_type: str,
        properties: Mapping[str, str],
    ) -> str:
        """Stream the staged file and return the resulting cmis:objectId."""
        normalized = folder_path.strip("/")
        self.ensure_folder(folder_path)
        url = f"{self._cfg.base_url}/{self._cfg.repo_id}/root/{normalized}"
        with file.path.open("rb") as fh:
            stream: IO[bytes] = (
                BandwidthLimiter(fh, self._cfg.max_bandwidth_mbps)  # type: ignore[assignment]
                if self._cfg.max_bandwidth_mbps > 0
                else fh
            )
            encoder = self._build_multipart_for_upload(
                stream, document_name, mime_type, object_type_id, properties
            )
            resp = self._post_with_retries(
                url,
                encoder,
                {"Content-Type": encoder.content_type},
                txn_num=document_name,
                kind="cmis_upload",
            )
        return self._parse_object_id(resp)

    # ----------------------------------------------------------- internals

    def _warmup_session(self) -> dict[str, Any]:
        url = f"{self._cfg.base_url}/{self._cfg.repo_id}"
        t0 = time.monotonic()
        resp = self._session.get(
            url,
            params={"cmisselector": "repositoryInfo"},
            timeout=self._timeout_s,
        )
        _network_log.info(
            "cmis_get",
            extra={
                "kind": "cmis_get",
                "duration_ms": round((time.monotonic() - t0) * 1000.0, 3),
                "status": resp.status_code,
                "url_prefix": url[:80],
                "worker": threading.current_thread().name,
            },
        )
        body = _truncate(resp.text)
        if resp.status_code >= 500:
            raise CMISServerError(status_code=resp.status_code, response_body=body)
        if resp.status_code >= 400:
            raise CMISClientError(status_code=resp.status_code, response_body=body)
        with self._warm_lock:
            self._warm = True
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def _create_folder_segment(self, parent_path: str, segment: str) -> None:
        url = f"{self._cfg.base_url}/{self._cfg.repo_id}/root/{parent_path}".rstrip("/")
        encoder = MultipartEncoder(
            fields={
                "cmisaction": "createFolder",
                "propertyId[0]": "cmis:objectTypeId",
                "propertyValue[0]": "cmis:folder",
                "propertyId[1]": "cmis:name",
                "propertyValue[1]": segment,
            }
        )
        try:
            self._post_with_retries(
                url,
                encoder,
                {"Content-Type": encoder.content_type},
                txn_num=f"folder:{segment}",
            )
        except CMISClientError as exc:
            if exc.status_code == 409:
                return
            raise

    def _post_with_retries(
        self,
        url: str,
        data: MultipartEncoder,
        headers: dict[str, str],
        txn_num: str,
        kind: str = "cmis_post",
    ) -> requests.Response:
        auth_retried = False
        last_exc: Exception | None = None
        real_attempts = 0
        size_bytes = int(getattr(data, "len", 0)) or None
        t0 = time.monotonic()
        while real_attempts < self._cfg.retry_max_attempts:
            with self._warm_lock:
                need_warmup = not self._warm
            if need_warmup:
                self._warmup_session()
            try:
                resp = self._session.post(url, data=data, headers=headers, timeout=self._timeout_s)
            except RequestsConnectionError as exc:
                real_attempts += 1
                last_exc = exc
                doubled = _WINDOWS_ABORT_MARKER in str(exc)
                if doubled:
                    _log.error(
                        "cmis: windows abort 10053",
                        extra={"txn_num": txn_num, "attempt": real_attempts},
                    )
                if real_attempts < self._cfg.retry_max_attempts or doubled:
                    self._backoff_sleep(real_attempts, doubled)
                continue
            if resp.status_code == 401 and not auth_retried:
                auth_retried = True
                with self._warm_lock:
                    self._warm = False
                continue
            if 200 <= resp.status_code < 400:
                self._emit_network(kind, t0, resp.status_code, size_bytes, url)
                return resp
            if 400 <= resp.status_code < 500:
                self._emit_network(kind, t0, resp.status_code, size_bytes, url)
                raise CMISClientError(
                    status_code=resp.status_code, response_body=_truncate(resp.text)
                )
            real_attempts += 1
            last_exc = CMISServerError(
                status_code=resp.status_code, response_body=_truncate(resp.text)
            )
            _log.info(
                "cmis: server error, retrying",
                extra={
                    "txn_num": txn_num,
                    "attempt": real_attempts,
                    "status": resp.status_code,
                },
            )
            if real_attempts < self._cfg.retry_max_attempts:
                self._backoff_sleep(real_attempts, doubled=False)
        assert last_exc is not None
        last_status = getattr(last_exc, "status_code", None)
        self._emit_network(kind, t0, last_status, size_bytes, url)
        raise RetriesExhaustedError(
            txn_num=txn_num, attempts=self._cfg.retry_max_attempts
        ) from last_exc

    @staticmethod
    def _emit_network(
        kind: str,
        t0: float,
        status: int | None,
        size_bytes: int | None,
        url: str,
    ) -> None:
        extra: dict[str, object] = {
            "kind": kind,
            "duration_ms": round((time.monotonic() - t0) * 1000.0, 3),
            "url_prefix": url[:80],
            "worker": threading.current_thread().name,
        }
        if status is not None:
            extra["status"] = status
        if size_bytes is not None:
            extra["size_bytes"] = size_bytes
        _network_log.info(kind, extra=extra)

    def _backoff_sleep(self, attempt: int, doubled: bool) -> None:
        delay = self._cfg.retry_base_delay_s * (2 ** (attempt - 1))
        if doubled:
            delay *= 2
        time.sleep(min(delay, _MAX_BACKOFF_S))

    @staticmethod
    def _build_multipart_for_upload(
        stream: IO[bytes],
        document_name: str,
        mime_type: str,
        object_type_id: str,
        properties: Mapping[str, str],
    ) -> MultipartEncoder:
        fields: dict[str, Any] = {
            "cmisaction": "createDocument",
            "propertyId[0]": "cmis:objectTypeId",
            "propertyValue[0]": object_type_id,
            "propertyId[1]": "cmis:name",
            "propertyValue[1]": document_name,
            "propertyId[2]": "cmis:contentStreamMimeType",
            "propertyValue[2]": mime_type,
        }
        for i, (key, value) in enumerate(properties.items()):
            fields[f"propertyId[{i + 3}]"] = key
            fields[f"propertyValue[{i + 3}]"] = value
        fields["content"] = (document_name, stream, mime_type)
        return MultipartEncoder(fields=fields)

    @staticmethod
    def _parse_object_id(response: requests.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return "unknown"
        if isinstance(data, dict):
            succinct = data.get("succinctProperties")
            if isinstance(succinct, dict) and "cmis:objectId" in succinct:
                return str(succinct["cmis:objectId"])
            properties = data.get("properties")
            if isinstance(properties, dict):
                obj = properties.get("cmis:objectId")
                if isinstance(obj, dict) and "value" in obj:
                    return str(obj["value"])
            return str(data.get("id", "unknown"))
        return "unknown"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _truncate(text: str) -> str:
    if len(text) <= _RESPONSE_BODY_TRUNCATION:
        return text
    return text[:_RESPONSE_BODY_TRUNCATION] + "...(truncated)"

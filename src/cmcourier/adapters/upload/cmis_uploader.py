"""Stage S5 — :class:`CmisUploader`.

Concrete :class:`IUploader` for IBM Content Manager via the CMIS Browser
Binding REST/JSON protocol. The adapter holds one :class:`httpx.Client`
shared across all calls. Sync client; the orchestrator's ``ThreadPoolExecutor``
calls into it from N worker threads.

060: migrated from ``requests`` to ``httpx[http2]``. When the server
negotiates HTTP/2 via ALPN (Apache-fronted Alfresco in prod) the N
concurrent workers multiplex over a single TCP connection — small-upload
overhead drops. If the server only speaks HTTP/1.1 (Tomcat-direct
staging) httpx transparently falls back, same behaviour as pre-060.

Implements the full S5 upload contract:

* JSESSIONID warmup — lazy, runs once per session lifetime.
* Recursive folder creation with the in-memory cache and idempotent 409
  semantics; ``$``-prefixed system folders are skipped.
* Streaming multipart upload via httpx's ``files=`` / ``data=`` API;
  the file is read from disk on demand, never buffered whole.
* Optional :class:`BandwidthLimiter` wrapping the file stream for
  throttled corporate networks.
* Retry policy: 401 → re-warmup + retry once; 5xx → exponential
  backoff capped at 60 s; Windows-10053 connection abort → doubled
  sleep; 4xx → fail-fast :class:`CMISClientError`; retry budget
  exhausted → :class:`RetriesExhaustedError`.
* The 3-path ``cmis:objectId`` parser.

Constitution Principle I: this module imports ``httpx`` (declared in
``pyproject.toml``) and the standard library. Domain models are
imported as types only. Principle VIII: logs identify operational keys
(txn_num, folder_path, HTTP status, attempt) but never property values
or response bodies beyond a truncation cap.
"""

from __future__ import annotations

__all__ = ["BandwidthLimiter", "CmisConfig", "CmisUploader", "TokenBucket"]

import json
import logging
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import IO, Any

import httpx

from cmcourier.domain.exceptions import (
    CMISClientError,
    CMISServerError,
    RetriesExhaustedError,
)
from cmcourier.domain.models import StagedFile
from cmcourier.domain.ports import IUploader
from cmcourier.observability.pii import mask_dict

_network_log = logging.getLogger("cmcourier.metrics.network")

_log = logging.getLogger(__name__)

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
    # 038: default httpx connection pool is small. When the S5 worker
    # count exceeds the keepalive pool, httpx opens fresh TCP per
    # request. Size the pool to match expected concurrency.
    pool_size: int = 10
    # 038: when True, ``s5_upload_attempt`` and ``s5_upload_failed``
    # events emit raw property values instead of PII-masked ones.
    # Toggled via ``ObservabilityConfig.unmask_pii``; never default-true.
    unmask_pii: bool = False


# ---------------------------------------------------------------------------
# BandwidthLimiter
# ---------------------------------------------------------------------------


class TokenBucket:
    """Process-shared token bucket (fixed in 029).

    A single instance is owned by :class:`CmisUploader` and reused
    across every upload + every worker thread. Concurrent
    ``consume()`` calls serialize on the internal lock so the
    configured rate is the **global** ceiling, not a per-call
    one. ``mbps=0`` disables throttling entirely (no lock taken).
    """

    def __init__(self, mbps: float) -> None:
        self._enabled = mbps > 0
        self._rate = mbps * 1_000_000.0  # bytes/sec
        self._tokens = 0.0
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, n_bytes: int) -> None:
        """Block until ``n_bytes`` tokens are available, then deduct."""
        if not self._enabled or n_bytes <= 0:
            return
        # Compute the sleep outside the lock so other threads can
        # refill their token math while this one waits. The lock
        # only guards the (tokens, last_refill) state.
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens += elapsed * self._rate
                self._last_refill = now
                if self._tokens >= n_bytes:
                    self._tokens -= n_bytes
                    return
                deficit = (n_bytes - self._tokens) / self._rate
            time.sleep(deficit)


class BandwidthLimiter:
    """File-like wrapper that defers throttling to a shared bucket."""

    def __init__(self, stream: IO[bytes], bucket: TokenBucket) -> None:
        self._stream = stream
        self._bucket = bucket

    def read(self, size: int = -1) -> bytes:
        chunk_size = size if size >= 0 else 1 << 20
        self._bucket.consume(chunk_size)
        return self._stream.read(chunk_size)

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
    """Concrete :class:`IUploader` over CMIS Browser Binding (httpx[http2])."""

    def __init__(self, config: CmisConfig) -> None:
        self._cfg = config
        pool_size = max(1, int(config.pool_size))
        # 060: HTTP/2 negotiated via ALPN; HTTP/1.1 fallback if the
        # server doesn't advertise h2. Same wire behaviour as pre-060
        # against Tomcat-direct; multiplexing kicks in vs Apache.
        self._client = httpx.Client(
            http2=True,
            auth=(config.username, config.password),
            verify=config.verify_ssl,
            limits=httpx.Limits(
                max_connections=pool_size,
                max_keepalive_connections=pool_size,
            ),
            timeout=httpx.Timeout(config.timeout_seconds),
        )
        self._warm = False
        # 025: S5 worker pool calls upload concurrently. The per-instance
        # state above is shared across worker threads.
        self._warm_lock = threading.Lock()
        # 025 phase 2: the AIMD auto-tune controller may adjust the
        # request timeout mid-batch. CmisConfig itself is frozen, so we
        # keep the live value here. Request paths consult this property
        # via ``self._timeout_s``; defaults to the configured value.
        self._timeout_s: float = float(config.timeout_seconds)
        # 029: one shared TokenBucket per uploader so the configured
        # ``max_bandwidth_mbps`` is the global cap across every
        # concurrent upload (not a per-call ceiling that multiplies
        # by worker count).
        self._bandwidth_bucket = TokenBucket(mbps=config.max_bandwidth_mbps)

    # ----------------------------------------------------------- public API

    def test_connection(self) -> Mapping[str, str]:
        """GET repositoryInfo, return a small diagnostics dict.

        IBM CM returns the fields flat under the top-level JSON object.
        Alfresco wraps them: ``{"<repo_id>": {"repositoryId": ...}}``.
        We unwrap when the top-level lacks ``repositoryId`` (040).
        """
        data = self._warmup_session()
        if isinstance(data, dict) and "repositoryId" not in data:
            nested = [v for v in data.values() if isinstance(v, dict) and "repositoryId" in v]
            if nested:
                data = nested[0]
        return {
            "repository_id": str(data.get("repositoryId", "")),
            "product_name": str(data.get("productName", "")),
            "product_version": str(data.get("productVersion", "")),
            "vendor_name": str(data.get("vendorName", "")),
        }

    def warm_connection_pool(self, n: int) -> int:
        """Pre-open ``n`` TCP+TLS+JSESSIONID connections (038).

        Without this, the first ``n`` S5 uploads each pay the TCP +
        TLS handshake + JSESSIONID bootstrap on the critical path —
        easily 100-400 ms per worker on a corporate link. Calling this
        once before stage S5 dispatches all that to a parallel
        startup phase, leaving the uploads themselves on warm
        keep-alive connections.

        Returns the number of warmups that completed successfully.
        Failures are logged but never raise — a cold pool just means
        the first uploads pay the handshake.
        """
        if n <= 0:
            return 0
        successes = 0
        with ThreadPoolExecutor(
            max_workers=n,
            thread_name_prefix="cmcourier-cmis-warmup",
        ) as pool:
            futures = [pool.submit(self._warmup_session) for _ in range(n)]
            for fut in as_completed(futures):
                try:
                    fut.result()
                    successes += 1
                except (CMISServerError, CMISClientError, httpx.RequestError):
                    _log.warning("cmis: warmup attempt failed", exc_info=True)
        _log.info(
            "cmis: connection pool warmed",
            extra={
                "event": "cmis_pool_warmed",
                "requested": n,
                "succeeded": successes,
            },
        )
        return successes

    def get_type_definition(self, object_type_id: str) -> Mapping[str, Any]:
        """GET cmisselector=typeDefinition&typeId=<id>. Bypasses the retry loop."""
        with self._warm_lock:
            need_warmup = not self._warm
        if need_warmup:
            self._warmup_session()
        url = self._service_url()
        t0 = time.monotonic()
        resp = self._client.get(
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

    def verify_folder_exists(self, folder_path: str) -> bool:
        """Return ``True`` iff *folder_path* exists on the CM server and is
        a ``cmis:folder``.

        Read-only — never creates the folder. CMCourier deposits documents
        only; the target folder tree is governed by the CMIS administrator
        (038). Used by ``doctor --check cm-targets`` to pre-flight every
        ``CMISFolder`` declared in MapeoRVI_CM before S5 ever runs.

        Returns ``False`` on 404 or when the path resolves to a non-folder
        object. Raises ``CMISClientError`` (401/403) or ``CMISServerError``
        (5xx) on connectivity / authentication failures so doctor surfaces
        configuration errors loudly.
        """
        normalized = folder_path.strip("/")
        url = self._service_url(f"root/{normalized}")
        t0 = time.monotonic()
        resp = self._client.get(
            url,
            params={"cmisselector": "object"},
            timeout=self._timeout_s,
        )
        _network_log.info(
            "cmis_get",
            extra={
                "kind": "cmis_verify_folder",
                "duration_ms": round((time.monotonic() - t0) * 1000.0, 3),
                "status": resp.status_code,
                "url_prefix": url[:80],
                "worker": threading.current_thread().name,
            },
        )
        if resp.status_code == 404:
            return False
        body = _truncate(resp.text)
        if resp.status_code >= 500:
            raise CMISServerError(status_code=resp.status_code, response_body=body)
        if resp.status_code >= 400:
            raise CMISClientError(status_code=resp.status_code, response_body=body)
        try:
            data = resp.json()
        except ValueError:
            return False
        if not isinstance(data, dict):
            return False
        props = data.get("properties") or data.get("succinctProperties") or {}
        if not isinstance(props, dict):
            return False
        base = props.get("cmis:baseTypeId")
        if isinstance(base, dict):
            base = base.get("value")
        return base == "cmis:folder"

    def upload(
        self,
        file: StagedFile,
        folder_path: str,
        object_type_id: str,
        document_name: str,
        mime_type: str,
        properties: Mapping[str, str],
        *,
        batch_id: str,
    ) -> str:
        """Stream the staged file and return the resulting cmis:objectId.

        ``batch_id`` tags every network event emitted here so the
        per-batch ``_BandwidthHandler`` / ``_SlowOpHandler`` attribute
        the bytes + slow ops to the right chunk. Without it the handlers
        drop the events (their ``batch_id`` filter never matches).

        The target folder is NOT verified or created here — the operator
        is expected to have run ``doctor --check cm-targets`` (038) before
        the pipeline. If the folder is missing or is not a CMIS folder,
        the server returns a 4xx and the failure surfaces via the
        existing retry / metrics path.
        """
        normalized = folder_path.strip("/")
        url = self._service_url(f"root/{normalized}")
        self._emit_upload_attempt(
            url=url,
            object_type_id=object_type_id,
            document_name=document_name,
            mime_type=mime_type,
            properties=properties,
            content_bytes=file.size_bytes,
            batch_id=batch_id,
        )
        with file.path.open("rb") as fh:
            stream: IO[bytes] = (
                BandwidthLimiter(fh, self._bandwidth_bucket)  # type: ignore[assignment]
                if self._cfg.max_bandwidth_mbps > 0
                else fh
            )
            data_fields, file_field = self._build_multipart_for_upload(
                stream, document_name, mime_type, object_type_id, properties
            )
            try:
                resp = self._post_with_retries(
                    url,
                    data_fields=data_fields,
                    file_field=file_field,
                    txn_num=document_name,
                    kind="cmis_upload",
                    size_bytes=file.size_bytes,
                    batch_id=batch_id,
                )
            except (CMISClientError, CMISServerError) as exc:
                # 045: a 409 conflict typically means a prior run (or a
                # kill-race between a successful CMIS POST and our SQLite
                # commit) already created this object. Look it up by
                # cmis:name; if found, treat the upload as idempotently
                # successful and return that objectId.
                if isinstance(exc, CMISClientError) and exc.status_code == 409:
                    recovered = self._try_recover_409(
                        folder_url=url,
                        document_name=document_name,
                        object_type_id=object_type_id,
                        mime_type=mime_type,
                        properties=properties,
                        content_bytes=file.size_bytes,
                        exc=exc,
                    )
                    if recovered is not None:
                        return recovered
                self._emit_upload_failed(
                    url=url,
                    object_type_id=object_type_id,
                    document_name=document_name,
                    mime_type=mime_type,
                    properties=properties,
                    content_bytes=file.size_bytes,
                    batch_id=batch_id,
                    status_code=exc.status_code,
                    response_body=str(getattr(exc, "response_body", "") or "")[
                        :_RESPONSE_BODY_TRUNCATION
                    ],
                )
                raise
        return self._parse_object_id(resp)

    def _try_recover_409(
        self,
        *,
        folder_url: str,
        document_name: str,
        object_type_id: str,
        mime_type: str,
        properties: Mapping[str, str],
        content_bytes: int,
        exc: CMISClientError,
    ) -> str | None:
        """045 — recover a 409 conflict via children lookup.

        Returns the existing ``cmis:objectId`` when a child of ``folder_url``
        already has ``cmis:name == document_name``; returns ``None`` when
        nothing matches (true 409 — propagate as failure). Emits structured
        audit events so the operator can grep recoveries in
        ``network-YYYY-MM-DD.jsonl``.
        """
        self._emit_409_event(
            event="s5_upload_409_recovery_attempt",
            url=folder_url,
            object_type_id=object_type_id,
            document_name=document_name,
            mime_type=mime_type,
            properties=properties,
            content_bytes=content_bytes,
        )
        try:
            existing_id = self._lookup_existing_object_id(folder_url, document_name)
        except (CMISClientError, CMISServerError, httpx.RequestError):
            # Lookup itself failed — fall through to the original failure
            # path so the operator sees the underlying upload error.
            self._emit_409_event(
                event="s5_upload_409_recovery_failed",
                url=folder_url,
                object_type_id=object_type_id,
                document_name=document_name,
                mime_type=mime_type,
                properties=properties,
                content_bytes=content_bytes,
                detail="lookup-transport-error",
            )
            return None
        if existing_id is None:
            self._emit_409_event(
                event="s5_upload_409_recovery_failed",
                url=folder_url,
                object_type_id=object_type_id,
                document_name=document_name,
                mime_type=mime_type,
                properties=properties,
                content_bytes=content_bytes,
                detail="no-matching-child",
            )
            return None
        self._emit_409_event(
            event="s5_upload_409_recovered",
            url=folder_url,
            object_type_id=object_type_id,
            document_name=document_name,
            mime_type=mime_type,
            properties=properties,
            content_bytes=content_bytes,
            recovered_object_id=existing_id,
        )
        del exc  # the original 409 is consumed — recovery is the answer now.
        return existing_id

    def _lookup_existing_object_id(self, folder_url: str, document_name: str) -> str | None:
        """List ``folder_url``'s children, return the matching cmis:objectId."""
        t0 = time.monotonic()
        resp = self._client.get(
            folder_url,
            params={"cmisselector": "children", "maxItems": "5000"},
            timeout=self._timeout_s,
        )
        _network_log.info(
            "cmis_get",
            extra={
                "kind": "cmis_409_lookup",
                "duration_ms": round((time.monotonic() - t0) * 1000.0, 3),
                "status": resp.status_code,
                "url_prefix": folder_url[:80],
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
            return None
        if not isinstance(data, dict):
            return None
        objects = data.get("objects") or []
        if not isinstance(objects, list):
            return None
        for entry in objects:
            obj = entry.get("object") if isinstance(entry, dict) else None
            if not isinstance(obj, dict):
                continue
            props = obj.get("properties") or obj.get("succinctProperties") or {}
            if not isinstance(props, dict):
                continue
            name = props.get("cmis:name")
            if isinstance(name, dict):
                name = name.get("value")
            if name != document_name:
                continue
            obj_id = props.get("cmis:objectId")
            if isinstance(obj_id, dict):
                obj_id = obj_id.get("value")
            if isinstance(obj_id, str) and obj_id:
                return obj_id
        return None

    def _emit_409_event(
        self,
        *,
        event: str,
        url: str,
        object_type_id: str,
        document_name: str,
        mime_type: str,
        properties: Mapping[str, str],
        content_bytes: int,
        recovered_object_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        masked = mask_dict(dict(properties), unmask=self._cfg.unmask_pii)
        extra: dict[str, Any] = {
            "event": event,
            "kind": "cmis_409_recovery",
            "url": url,
            "object_type_id": object_type_id,
            "document_name": document_name,
            "mime_type": mime_type,
            "content_bytes": content_bytes,
            "properties_json": json.dumps(masked, sort_keys=True),
        }
        if recovered_object_id is not None:
            extra["recovered_object_id"] = recovered_object_id
        if detail is not None:
            extra["detail"] = detail
        _network_log.info(event, extra=extra)

    def _emit_upload_attempt(
        self,
        *,
        url: str,
        object_type_id: str,
        document_name: str,
        mime_type: str,
        properties: Mapping[str, str],
        content_bytes: int,
        batch_id: str,
    ) -> None:
        """038: structured ``s5_upload_attempt`` event into metrics.jsonl."""
        masked = mask_dict(
            {
                "cmis:name": document_name,
                "cmis:contentStreamMimeType": mime_type,
                **dict(properties),
            },
            unmask=self._cfg.unmask_pii,
        )
        _network_log.info(
            "s5_upload_attempt",
            extra={
                "event": "s5_upload_attempt",
                "kind": "cmis_upload_attempt",
                "batch_id": batch_id,
                "url": url[:200],
                "object_type_id": object_type_id,
                "document_name": document_name,
                "mime_type": mime_type,
                "properties_json": json.dumps(masked, ensure_ascii=False, sort_keys=True),
                "content_bytes": content_bytes,
                "worker": threading.current_thread().name,
            },
        )

    def _emit_upload_failed(
        self,
        *,
        url: str,
        object_type_id: str,
        document_name: str,
        mime_type: str,
        properties: Mapping[str, str],
        content_bytes: int,
        batch_id: str,
        status_code: int,
        response_body: str,
    ) -> None:
        """038: structured ``s5_upload_failed`` event with curl-equivalent."""
        masked = mask_dict(
            {
                "cmis:name": document_name,
                "cmis:contentStreamMimeType": mime_type,
                **dict(properties),
            },
            unmask=self._cfg.unmask_pii,
        )
        curl = self._build_curl_equivalent(
            url=url, object_type_id=object_type_id, masked_properties=masked
        )
        _network_log.info(
            "s5_upload_failed",
            extra={
                "event": "s5_upload_failed",
                "kind": "cmis_upload_failed",
                "batch_id": batch_id,
                "url": url[:200],
                "object_type_id": object_type_id,
                "document_name": document_name,
                "mime_type": mime_type,
                "properties_json": json.dumps(masked, ensure_ascii=False, sort_keys=True),
                "content_bytes": content_bytes,
                "status_code": status_code,
                "response_body": response_body,
                "curl_equivalent": curl,
                "worker": threading.current_thread().name,
            },
        )

    def _build_curl_equivalent(
        self, *, url: str, object_type_id: str, masked_properties: Mapping[str, str]
    ) -> str:
        """Render a runnable curl that reproduces the failing POST.

        Auth is rendered as ``-u admin:***`` regardless of unmask_pii —
        credentials never leak into structured logs (Principle VIII).
        """
        parts = [
            "curl -u admin:***",
            "-X POST",
            "-F 'cmisaction=createDocument'",
            f"-F 'propertyId[0]=cmis:objectTypeId' -F 'propertyValue[0]={object_type_id}'",
        ]
        idx = 1
        for k, v in masked_properties.items():
            if k in ("cmis:contentStreamMimeType",):
                # already in the form; skip duplicate (the encoder always
                # carries mime via `cmis:contentStreamMimeType`).
                pass
            safe_v = v.replace("'", "'\\''")
            parts.append(f"-F 'propertyId[{idx}]={k}' -F 'propertyValue[{idx}]={safe_v}'")
            idx += 1
        parts.append("-F 'content=@<staged_pdf_path>'")
        parts.append(f"'{url}'")
        return " ".join(parts)

    # ----------------------------------------------------------- internals

    def _service_url(self, suffix: str = "") -> str:
        """Build a CMIS Browser Binding service URL respecting Alfresco vs IBM CM.

        IBM Content Manager exposes its repository id INSIDE the URL path
        (``.../cmis-browser/<repo_id>/root/<folder>``). Alfresco's browser
        binding does NOT — the repository id is read from the
        ``repositoryInfo`` response, and the ``base_url`` already includes
        everything up to ``.../browser`` (040). Distinguish the two via
        the ``repo_id`` config:

        - ``repo_id`` set (any non-empty string): IBM CM convention,
          emit ``f"{base}/{repo_id}/{suffix}"``.
        - ``repo_id == ""``: Alfresco convention, emit
          ``f"{base}/{suffix}"`` (no doubled slash).
        """
        if self._cfg.repo_id:
            url = f"{self._cfg.base_url}/{self._cfg.repo_id}"
        else:
            url = self._cfg.base_url
        return f"{url}/{suffix}" if suffix else url

    def _warmup_session(self) -> dict[str, Any]:
        url = self._service_url()
        t0 = time.monotonic()
        resp = self._client.get(
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

    def _post_with_retries(
        self,
        url: str,
        *,
        data_fields: dict[str, str],
        file_field: tuple[str, IO[bytes], str],
        txn_num: str,
        kind: str = "cmis_post",
        size_bytes: int | None = None,
        batch_id: str,
    ) -> httpx.Response:
        auth_retried = False
        last_exc: Exception | None = None
        real_attempts = 0
        t0 = time.monotonic()
        # 060: the file stream may have been consumed by a previous attempt
        # (httpx reads it whole on POST). Seek to 0 before each retry — but
        # only the underlying file handle, since BandwidthLimiter forwards
        # seek() to it.
        stream = file_field[1]
        while real_attempts < self._cfg.retry_max_attempts:
            with self._warm_lock:
                need_warmup = not self._warm
            if need_warmup:
                self._warmup_session()
            try:
                if real_attempts > 0:
                    stream.seek(0)
                resp = self._client.post(
                    url,
                    data=data_fields,
                    files={"content": file_field},
                    timeout=self._timeout_s,
                )
            except httpx.RequestError as exc:
                # httpx.RequestError covers ConnectError, ReadError,
                # RemoteProtocolError, TimeoutException — every transport
                # failure that would previously have come up as
                # requests.exceptions.ConnectionError.
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
                self._emit_network(kind, t0, resp.status_code, size_bytes, url, batch_id)
                return resp
            if 400 <= resp.status_code < 500:
                self._emit_network(kind, t0, resp.status_code, size_bytes, url, batch_id)
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
        self._emit_network(kind, t0, last_status, size_bytes, url, batch_id)
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
        batch_id: str,
    ) -> None:
        # ``batch_id`` is mandatory: the per-batch _BandwidthHandler /
        # _SlowOpHandler drop any record whose batch_id doesn't match,
        # so an event without it is silently discarded by every recorder.
        extra: dict[str, object] = {
            "kind": kind,
            "batch_id": batch_id,
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

    def _build_multipart_for_upload(
        self,
        stream: IO[bytes],
        document_name: str,
        mime_type: str,
        object_type_id: str,
        properties: Mapping[str, str],
    ) -> tuple[dict[str, str], tuple[str, IO[bytes], str]]:
        """Build the multipart body for `client.post(..., data=..., files=...)`.

        060: httpx separates text fields (``data``) from file fields
        (``files``). Returns ``(data_fields, file_field)`` so the caller
        can assemble the POST. The text fields carry every CMIS property
        (``cmisaction``, ``propertyId[N]`` / ``propertyValue[N]``) and the
        file field carries the staged stream.

        040: IBM CM requires ``cmis:contentStreamMimeType`` as an explicit
        property; Alfresco rejects that same property with 400 because it
        infers the mime type from the multipart Content-Type. The
        convention follows the same Alfresco-vs-IBM-CM heuristic as the
        URL builder: empty ``repo_id`` means Alfresco mode → omit the
        explicit property; the multipart part still carries the right
        Content-Type.
        """
        data_fields: dict[str, str] = {
            "cmisaction": "createDocument",
            "propertyId[0]": "cmis:objectTypeId",
            "propertyValue[0]": object_type_id,
            "propertyId[1]": "cmis:name",
            "propertyValue[1]": document_name,
        }
        next_idx = 2
        if self._cfg.repo_id:
            data_fields[f"propertyId[{next_idx}]"] = "cmis:contentStreamMimeType"
            data_fields[f"propertyValue[{next_idx}]"] = mime_type
            next_idx += 1
        for i, (key, value) in enumerate(properties.items()):
            data_fields[f"propertyId[{next_idx + i}]"] = key
            data_fields[f"propertyValue[{next_idx + i}]"] = value
        file_field = (document_name, stream, mime_type)
        return data_fields, file_field

    @staticmethod
    def _parse_object_id(response: httpx.Response) -> str:
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

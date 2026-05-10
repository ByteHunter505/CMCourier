# Plan — 010-cmis-upload-adapter

**Status**: Draft
**Spec**: `specs/010-cmis-upload-adapter/spec.md`

---

## 1. Architecture in one paragraph

One module `adapters/upload/cmis_uploader.py` housing three public
classes: `CmisConfig` (frozen dataclass), `BandwidthLimiter` (token-bucket
file wrapper), and `CmisUploader` (the `IUploader` implementation
holding ONE `requests.Session`). The session is warmed up lazily on first
use; subsequent state-changing calls (`ensure_folder`, `upload`) flow
through a private `_post_with_retries` that encapsulates the entire retry
policy (401 re-warmup, 5xx exponential backoff, Windows-10053 delay
doubling, 4xx fail-fast, retry-budget exhaustion). Folder creation uses
a `set[str]` cache to avoid re-issuing successful POSTs across calls.
Streaming uploads go through `requests-toolbelt.MultipartEncoder`,
optionally wrapping the file in `BandwidthLimiter` first.

---

## 2. Module layout

```
src/cmcourier/adapters/upload/cmis_uploader.py
├── CmisConfig                          # frozen+slots dataclass
├── BandwidthLimiter                    # token-bucket file wrapper
│   ├── __init__(stream, mbps)
│   ├── read(size)
│   ├── seek / tell / close / name      # passthrough
│   └── __enter__ / __exit__
├── _SYSTEM_FOLDER_PREFIX = "$"
├── _WINDOWS_ABORT_MARKER = "10053"
├── _MAX_BACKOFF_S = 60.0
├── _RESPONSE_BODY_TRUNCATION = 1024
├── CmisUploader                        # the IUploader impl
│   ├── __init__(config)
│   ├── test_connection() -> Mapping[str, str]
│   ├── ensure_folder(folder_path)
│   ├── upload(file, folder_path, object_type_id, ...) -> str
│   ├── _warmup_session()
│   ├── _post_with_retries(url, data, headers, txn_num) -> Response
│   ├── _create_folder_segment(parent_path, segment)
│   ├── _build_multipart_for_upload(file, doc_name, mime_type, object_type_id, properties) -> MultipartEncoder
│   ├── _parse_object_id(response) -> str
│   └── _backoff_sleep(attempt, doubled)
```

Every method ≤ 50 lines. The retry loop is at the soft edge — extract
helpers if it grows.

---

## 3. Public API contracts

### 3.1 `CmisConfig`

```python
@dataclass(frozen=True, slots=True)
class CmisConfig:
    base_url: str
    repo_id: str
    username: str
    password: str
    timeout_seconds: float = 300.0
    verify_ssl: bool = False
    max_bandwidth_mbps: float = 0.0
    retry_max_attempts: int = 3
    retry_base_delay_s: float = 2.0
```

### 3.2 `BandwidthLimiter`

```python
class BandwidthLimiter:
    """Token-bucket read throttle for a file-like stream.

    Throttles ``read(size)`` so the average rate does not exceed
    ``mbps`` megabytes per second (1 MB = 1_000_000 bytes). If
    ``mbps <= 0``, the wrapper is a no-op passthrough.
    """
```

### 3.3 `CmisUploader.upload`

```python
def upload(
    self,
    file: StagedFile,
    folder_path: str,
    object_type_id: str,
    document_name: str,
    mime_type: str,
    properties: Mapping[str, str],
) -> str:
    """Stream *file* to ``{base_url}/{repo_id}/root/{folder_path}`` and
    return the resulting CMIS objectId.

    Raises:
        CMISClientError: HTTP 4xx (do NOT retry).
        CMISServerError: HTTP 5xx after retries exhausted (raised wrapped
            in RetriesExhaustedError via __cause__).
        RetriesExhaustedError: retry budget exhausted.
    """
```

---

## 4. Algorithm sketches

### 4.1 Lazy warmup

```python
def _warmup_session(self) -> None:
    url = f"{self._cfg.base_url}/{self._cfg.repo_id}?cmisselector=repositoryInfo"
    resp = self._session.get(url, timeout=self._cfg.timeout_seconds)
    if resp.status_code >= 500:
        raise CMISServerError(status_code=resp.status_code, response_body=_truncate(resp.text))
    if resp.status_code >= 400:
        raise CMISClientError(status_code=resp.status_code, response_body=_truncate(resp.text))
    self._warm = True
```

### 4.2 Retry loop

```python
def _post_with_retries(self, url, data, headers, txn_num):
    last_exc: Exception | None = None
    doubled = False
    for attempt in range(1, self._cfg.retry_max_attempts + 1):
        if not self._warm:
            self._warmup_session()
        try:
            resp = self._session.post(url, data=data, headers=headers,
                                      timeout=self._cfg.timeout_seconds)
        except ConnectionError as exc:
            last_exc = exc
            doubled = _WINDOWS_ABORT_MARKER in str(exc)
            if doubled:
                _log.error("cmis: windows abort 10053",
                           extra={"txn_num": txn_num, "attempt": attempt})
            self._backoff_sleep(attempt, doubled)
            continue
        if resp.status_code == 401 and attempt == 1:
            self._warm = False
            continue                    # next iteration re-warmups
        if resp.status_code < 400:
            return resp
        if resp.status_code < 500:
            raise CMISClientError(status_code=resp.status_code,
                                  response_body=_truncate(resp.text))
        # 5xx
        last_exc = CMISServerError(status_code=resp.status_code,
                                    response_body=_truncate(resp.text))
        self._backoff_sleep(attempt, doubled=False)
    raise RetriesExhaustedError(txn_num=txn_num,
                                attempts=self._cfg.retry_max_attempts) from last_exc
```

Notes:
- The 401 branch consumes its retry without sleeping AND without
  counting an "attempt" toward exhaustion — but it does increment the
  `for` loop, so REQ-006 ("retry exactly once on 401") is preserved
  because a second 401 will reach the `< 400` check on attempt 2 (no
  re-warmup again because the `if attempt == 1` gate is gone).
- A more readable alternative: handle 401 specifically and return /
  raise from there. The implementation iterates this until tests
  surface the simplest shape.

### 4.3 Folder creation

```python
def ensure_folder(self, folder_path):
    segments = [s for s in folder_path.split("/") if s and not s.startswith(_SYSTEM_FOLDER_PREFIX)]
    parent = ""
    for seg in segments:
        abs_path = f"{parent}/{seg}".lstrip("/")
        if abs_path in self._folder_cache:
            parent = abs_path
            continue
        self._create_folder_segment(parent, seg)
        self._folder_cache.add(abs_path)
        parent = abs_path


def _create_folder_segment(self, parent_path, segment):
    url = f"{self._cfg.base_url}/{self._cfg.repo_id}/root/{parent_path}"
    fields = {
        "cmisaction": "createFolder",
        "propertyId[0]": "cmis:objectTypeId",
        "propertyValue[0]": "cmis:folder",
        "propertyId[1]": "cmis:name",
        "propertyValue[1]": segment,
    }
    enc = MultipartEncoder(fields=fields)
    try:
        self._post_with_retries(url, enc, {"Content-Type": enc.content_type},
                                txn_num=f"folder:{segment}")
    except CMISClientError as exc:
        if exc.status_code == 409:
            return  # idempotent — already exists
        raise
```

The 409-as-success branch lives here (folder-creation specific), not in
the generic retry loop.

### 4.4 Upload assembly

```python
def upload(self, file, folder_path, object_type_id, document_name, mime_type, properties):
    self.ensure_folder(folder_path)
    url = f"{self._cfg.base_url}/{self._cfg.repo_id}/root/{folder_path.lstrip('/')}"
    with open(file.path, "rb") as fh:
        stream: object = (
            BandwidthLimiter(fh, self._cfg.max_bandwidth_mbps)
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
        )
    return self._parse_object_id(resp)
```

### 4.5 `_build_multipart_for_upload`

```python
def _build_multipart_for_upload(self, stream, doc_name, mime_type, object_type_id, properties):
    fields = {
        "cmisaction": "createDocument",
        "propertyId[0]": "cmis:objectTypeId",
        "propertyValue[0]": object_type_id,
        "propertyId[1]": "cmis:name",
        "propertyValue[1]": doc_name,
        "propertyId[2]": "cmis:contentStreamMimeType",
        "propertyValue[2]": mime_type,
    }
    for i, (k, v) in enumerate(properties.items()):
        fields[f"propertyId[{i + 3}]"] = k
        fields[f"propertyValue[{i + 3}]"] = v
    fields["content"] = (doc_name, stream, mime_type)
    return MultipartEncoder(fields=fields)
```

### 4.6 `_parse_object_id`

```python
def _parse_object_id(self, response):
    data = response.json()
    succinct = data.get("succinctProperties")
    if isinstance(succinct, Mapping) and "cmis:objectId" in succinct:
        return str(succinct["cmis:objectId"])
    properties = data.get("properties")
    if isinstance(properties, Mapping):
        obj = properties.get("cmis:objectId")
        if isinstance(obj, Mapping) and "value" in obj:
            return str(obj["value"])
    return str(data.get("id", "unknown"))
```

### 4.7 BandwidthLimiter (token bucket)

```python
class BandwidthLimiter:
    def __init__(self, stream, mbps):
        self._stream = stream
        self._rate = mbps * 1_000_000.0  # bytes per second
        self._tokens = 0.0
        self._last_refill = time.monotonic()
        self._enabled = mbps > 0

    def read(self, size=-1):
        if not self._enabled:
            return self._stream.read(size)
        if size < 0:
            size = 1 << 20  # 1 MB chunks for unbounded reads
        self._refill_until(size)
        self._tokens -= size
        return self._stream.read(size)

    def _refill_until(self, needed):
        while self._tokens < needed:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens += elapsed * self._rate
            self._last_refill = now
            if self._tokens < needed:
                deficit = (needed - self._tokens) / self._rate
                time.sleep(deficit)

    # Passthroughs
    def seek(self, *a, **kw): return self._stream.seek(*a, **kw)
    def tell(self): return self._stream.tell()
    def close(self): return self._stream.close()
    @property
    def name(self): return getattr(self._stream, "name", "<bandwidth-limited>")
    def __enter__(self): return self
    def __exit__(self, *a): self.close()
```

---

## 5. Test plan

### 5.1 Library: `responses>=0.25,<1.0`

`responses` registers HTTP mocks on a per-test basis and asserts the
real `requests` library hits them. No `unittest.mock` of `requests`
internals.

For multipart streaming tests, `responses.add_callback` lets us inspect
the request body's content type and (truncated) length without trying
to parse the multipart wire format byte-by-byte.

### 5.2 Tests in `tests/integration/adapters/test_cmis_uploader.py`

| Group | Tests | Acceptance scenarios |
|-------|-------|----------------------|
| `TestCmisConfig` | 2 | REQ-001..002 defaults + frozen |
| `TestWarmup` | 3 | 4.1 + lazy warmup not on construction + warmup 5xx raises |
| `TestTestConnection` | 3 | 4.2 + missing keys → empty string + 4xx error |
| `TestEnsureFolder` | 5 | 4.3, 4.4, 4.5 + cache prevents re-POST + non-cached after 409 still in cache |
| `TestUploadHappyPath` | 4 | 4.6, 4.7, 4.8, 4.13 |
| `TestUploadRetry` | 4 | 4.9, 4.10, 4.11, 4.12 |
| `TestUploadWindows10053` | 1 | 4.16 |
| `TestBandwidthLimiter` | 3 | 4.14, 4.15 + passthrough methods (seek/tell/close) |
| `TestLoggingDiscipline` | 1 | logs carry txn_num+attempt, never full property values |

Total: ~26 tests.

### 5.3 Test helpers

- A `_make_config(**overrides)` factory returning a `CmisConfig` with
  short delays (`retry_base_delay_s=0.0`) so retry tests do not
  actually sleep.
- A `_make_staged(tmp_path, *, size_bytes=1024)` helper that writes a
  synthetic PDF (just `b"%PDF-1.4\n"` + padding to `size_bytes`) and
  returns a `StagedFile`. Synthetic content — no real PDF needed for
  the upload contract; the adapter does not parse the body.
- `monkeypatch.setattr("cmcourier.adapters.upload.cmis_uploader.time.sleep", lambda s: None)`
  to skip the real `time.sleep` in retry tests. The `bandwidth_test`
  uses the real `time.sleep` because it asserts on elapsed time.

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..002 (config) | §3.1 | TestCmisConfig |
| REQ-003..004 (construction) | §3.1 | TestWarmup (lazy) |
| REQ-005..006 (warmup) | §4.1 | TestWarmup, TestUploadRetry (401 re-warmup) |
| REQ-007..008 (test_connection) | §4.1 | TestTestConnection |
| REQ-009..012 (ensure_folder) | §4.3 | TestEnsureFolder |
| REQ-013..016 (upload) | §4.4, §4.5, §4.6 | TestUploadHappyPath |
| REQ-017..021 (retry policy) | §4.2 | TestUploadRetry, TestUploadWindows10053 |
| REQ-022..024 (BandwidthLimiter) | §4.7 | TestBandwidthLimiter |
| REQ-025 (logging) | §4.2 | TestLoggingDiscipline |
| NFR-002 (coverage ≥85%) | — | `pytest --cov` |
| NFR-003 (50-line cap) | — | Visual review |

---

## 7. Files touched

```
NEW   src/cmcourier/adapters/upload/cmis_uploader.py
EDIT  src/cmcourier/adapters/upload/__init__.py
NEW   tests/integration/adapters/test_cmis_uploader.py
EDIT  pyproject.toml                                # responses dev dep
EDIT  CHANGELOG.md                                  # [0.12.0]
EDIT  README.md                                     # Status checklist
NEW   specs/010-cmis-upload-adapter/{spec,plan,tasks}.md
```

No domain changes. `requests`, `requests-toolbelt` already in deps.

---

## 8. Risks

- **Risk**: `MultipartEncoder.content_type` includes a randomly-generated
  boundary string; equality assertions on it fail. Mitigation: tests
  assert the `Content-Type` header STARTS WITH `multipart/form-data;
  boundary=`, not equality.
- **Risk**: `responses` library + `MultipartEncoder` may double-consume
  the file stream (`responses` may call `body.read()` to capture the
  body, after which the real upload sees an empty stream).
  Mitigation: in tests, register `responses.add_callback` with
  `match_querystring=False` and a callback that returns the canned
  body without reading the request body; the test asserts on
  `request.headers["Content-Type"]` and on the call count rather than
  body bytes.
- **Risk**: token-bucket test flakiness on slow CI. Mitigation: ±20%
  tolerance + a sufficiently large/slow throttle (0.5 MB/s on 1 MB =
  2 s nominal, comfortable margin).
- **Risk**: `mypy --strict` on the retry loop's `last_exc: Exception | None`
  + `raise ... from last_exc` may flag `last_exc` as possibly None.
  Mitigation: explicit `assert last_exc is not None` before raise or
  initialize as `RuntimeError("no attempts made")` placeholder.

---

## 9. Estimated effort

- Spec / plan / tasks (this commit): done
- Phase 1 (dev dep): 5 min
- Phase 2 (tests RED): ~120 min — biggest fixture surface of the project
- Phase 3 (impl GREEN): ~100 min
- Phase 4 (verification): 20 min
- Phase 5 (docs + commit + merge): 15 min
- **Total**: ~4 h 20 min

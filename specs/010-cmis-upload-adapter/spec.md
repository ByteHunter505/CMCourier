# Spec — 010-cmis-upload-adapter

**Status**: Draft
**Stage**: S5 — Upload (REBIRTH §8, §10.1)
**Constitution alignment**: Principle I (hexagonal — concrete `IUploader`),
II (idempotency surfaces: 409 = OK), III (single-responsibility),
IV (streaming via `MultipartEncoder`), VI (real test pyramid via the
`responses` mock-HTTP library — no production HTTP in tests).

---

## 1. Intent

Implement `CmisUploader` — the concrete `IUploader` that ships staged
PDFs to IBM Content Manager via the **CMIS Browser Binding** REST/JSON
protocol. Handles the IBM-specific quirks documented in REBIRTH §8:
JSESSIONID warmup, recursive folder creation with idempotent 409, streaming
multipart uploads, exponential-backoff retries on 5xx, fail-fast on 4xx,
and a 3-path `objectId` parser for the response shape variants.

This is the **last adapter** before the MVP `rvabrep-pipeline`
orchestrator can run end-to-end against staging.

---

## 2. Scope

### In scope

- `adapters/upload/cmis_uploader.py` exporting:
  - `CmisConfig` (frozen+slots dataclass with connection + retry +
    bandwidth knobs).
  - `BandwidthLimiter` (token-bucket file-stream wrapper).
  - `CmisUploader` (the `IUploader` implementation).
- `ensure_folder(path)` — recursive creation walking from root, idempotent
  via HTTP 409 = success AND via an in-memory `set` cache; skips system
  folders that start with `$` (REBIRTH §8.3).
- `upload(file, folder_path, object_type_id, document_name, mime_type, properties)`
  — streaming multipart POST via `requests-toolbelt.MultipartEncoder`,
  followed by `cmis:objectId` parse with 3-fallback (REBIRTH §8.8).
- `test_connection()` — GET `repositoryInfo` and return a dict of
  diagnostics (also doubles as the JSESSIONID warmup).
- **JSESSIONID warmup** lazily on first call to any state-changing
  method (REBIRTH §8.2).
- **Retry policy** (REBIRTH §8.7):
  - HTTP 201 → success.
  - HTTP 401 → re-warmup session, retry ONCE.
  - HTTP 409 (folder creation only) → success.
  - HTTP 4xx (other) → raise `CMISClientError`, do NOT retry.
  - HTTP 5xx → exponential backoff, retry up to `retry_max_attempts`.
  - `ConnectionError` whose message contains `10053` (Windows abort) →
    DOUBLE the normal retry delay; treat as 5xx.
  - Retry budget exhausted → raise `RetriesExhaustedError(txn_num, attempts)`.
- **BandwidthLimiter**: a token-bucket file wrapper that throttles
  `read()` to `max_bandwidth_mbps` MB/s. `0.0` means unlimited (no
  wrapping). Applied to the file stream BEFORE `MultipartEncoder`.
- Integration tests using the `responses` library to mock HTTP
  (Constitution Principle VI: real adapter, no requests/Session
  mocking — only the network is stubbed).

### Out of scope

- **Thread-local sessions** (REBIRTH §8.2 "Per thread"). MVP is
  single-threaded. The adapter holds ONE `requests.Session`. A follow-up
  change refactors to `threading.local()` when the orchestrator wants
  worker pools.
- Pre-flight `doctor` integration (REBIRTH §10.5). The doctor command
  uses `test_connection()` directly; cmocking the doctor itself ships
  with the orchestrator.
- AIMD auto-tuning of bandwidth or worker count (post-MVP per
  `docs/roadmap/POST-MVP.md`).
- ACL / metadata-only updates against existing documents. The MVP only
  performs `createFolder` and `createDocument`.

---

## 3. Functional requirements (RFC 2119)

### Configuration

- **REQ-001** `CmisConfig` MUST be a `frozen=True, slots=True` dataclass
  with fields: `base_url`, `repo_id`, `username`, `password`,
  `timeout_seconds: float = 300.0`, `verify_ssl: bool = False`,
  `max_bandwidth_mbps: float = 0.0`, `retry_max_attempts: int = 3`,
  `retry_base_delay_s: float = 2.0`.
- **REQ-002** All `CmisConfig` fields except defaults MUST be required;
  the constructor MUST NOT silently default-fill credentials.

### Construction

- **REQ-003** `CmisUploader.__init__(config)` MUST NOT perform any HTTP
  call. The adapter is lazy: warmup fires on first `ensure_folder` /
  `upload` / `test_connection`.
- **REQ-004** The constructor MUST initialize a single
  `requests.Session` with `auth=(username, password)` and
  `verify=verify_ssl`; the session MUST be reused across all calls.

### Session warmup

- **REQ-005** Before any POST, the adapter MUST issue a
  `GET {base_url}/{repo_id}?cmisselector=repositoryInfo`. The resulting
  `JSESSIONID` cookie MUST be stored on the session.
- **REQ-006** Warmup MUST run AT MOST ONCE per session lifetime under
  normal operation. On HTTP 401 from a subsequent POST, the adapter
  MUST re-warmup and retry exactly once.

### `test_connection`

- **REQ-007** `test_connection()` MUST GET `repositoryInfo` (acting as
  the warmup) and return a `Mapping[str, str]` with the keys
  `repository_id`, `product_name`, `product_version`, and `vendor_name`
  read from the response. Missing keys MUST map to the empty string.
- **REQ-008** Non-200 responses from `test_connection` MUST raise
  `CMISServerError(status_code=...)` for 5xx or `CMISClientError(...)`
  for 4xx.

### `ensure_folder`

- **REQ-009** `ensure_folder(folder_path)` MUST split `folder_path` into
  segments by `/`, ignoring leading/trailing empty segments and any
  segment that starts with `$` (e.g., `$type`).
- **REQ-010** For each non-system segment, the adapter MUST POST a
  `createFolder` multipart to the parent path and treat HTTP 200 / 201
  and 409 as success.
- **REQ-011** Once a segment has been verified or created, its absolute
  path MUST be cached in an in-memory `set[str]` so subsequent calls
  bypass HTTP entirely.
- **REQ-012** `ensure_folder` MUST be idempotent across concurrent
  invocations: HTTP 409 always counts as success, and the cache prevents
  re-issuing a successful create.

### `upload`

- **REQ-013** `upload(file, folder_path, object_type_id, document_name, mime_type, properties)`
  MUST POST a `createDocument` multipart to `{base_url}/{repo_id}/root/{folder_path}`.
- **REQ-014** The multipart body MUST include:
  - `cmisaction = "createDocument"`
  - `propertyId[0] = "cmis:objectTypeId"`,
    `propertyValue[0] = object_type_id`
  - `propertyId[1] = "cmis:name"`,
    `propertyValue[1] = document_name`
  - `propertyId[2] = "cmis:contentStreamMimeType"`,
    `propertyValue[2] = mime_type`
  - One `propertyId[i+3] / propertyValue[i+3]` pair per `(key, value)`
    in `properties`, indexed in iteration order.
  - `content = (document_name, <file stream>, mime_type)` where the
    file stream is `open(file.path, "rb")` wrapped in a
    `BandwidthLimiter` if `max_bandwidth_mbps > 0`.
- **REQ-015** The file MUST be sent via `requests-toolbelt.MultipartEncoder`
  with `Content-Type: m.content_type`; the adapter MUST NOT call
  `file.read()` directly (Constitution Principle IV).
- **REQ-016** On HTTP 201, the adapter MUST parse the response JSON and
  return the `cmis:objectId` as `str`, using REBIRTH §8.8's three-path
  fallback: (1) `succinctProperties["cmis:objectId"]`; (2)
  `properties["cmis:objectId"]["value"]`; (3) `str(data.get("id", "unknown"))`.

### Retry policy

- **REQ-017** On HTTP 401 from `upload` or `ensure_folder`, the adapter
  MUST re-warmup the session and retry exactly once. A second 401 MUST
  raise `CMISClientError(status_code=401, ...)`.
- **REQ-018** On HTTP 5xx, the adapter MUST sleep for
  `retry_base_delay_s * 2**(attempt - 1)` seconds (capped at 60 s) and
  retry, up to `retry_max_attempts` total attempts.
- **REQ-019** On `ConnectionError` (or `requests.exceptions.ConnectionError`)
  whose `str(exc)` contains `"10053"`, the adapter MUST log at `ERROR`
  level naming `txn_num`, double the next sleep delay, and treat the
  failure as 5xx for retry purposes.
- **REQ-020** When `retry_max_attempts` is exhausted, the adapter MUST
  raise `RetriesExhaustedError(txn_num=..., attempts=...)`. The last
  underlying exception MUST be available via `__cause__`.
- **REQ-021** On HTTP 4xx OTHER than 401, the adapter MUST raise
  `CMISClientError(status_code=..., response_body=...)` immediately
  without retrying. The response body MUST be truncated to the first
  1024 chars for the exception context (REBIRTH §8.7: "log full payload
  as curl-equivalent" — full logging is the orchestrator's job).

### BandwidthLimiter

- **REQ-022** `BandwidthLimiter(stream, mbps)` MUST wrap a file-like
  object exposing `read(size: int) -> bytes`. The wrapper MUST throttle
  reads via a token bucket so the average read rate does not exceed
  `mbps` megabytes per second (where 1 MB = 1_000_000 bytes).
- **REQ-023** If `mbps <= 0`, the wrapper MUST NOT throttle; reads pass
  through unchanged.
- **REQ-024** The wrapper MUST proxy `close()`, `seek()`, `tell()`,
  `name`, and `__enter__` / `__exit__` to the underlying stream so it
  remains usable as a context manager and as a path for
  `MultipartEncoder` introspection.

### Logging discipline (Constitution VIII)

- **REQ-025** Logs MUST identify operational keys (`txn_num`,
  `folder_path`, HTTP status, attempt number, sleep duration) but MUST
  NOT log: full property values (BAC_CIF, BAC_Nombre_Cliente),
  full response bodies (truncated to 256 chars max for INFO/WARN,
  1024 for DEBUG only), or authorization headers.

---

## 4. Acceptance scenarios

### 4.1 Warmup on first call
- Given a freshly constructed `CmisUploader`.
- When `test_connection()` is called.
- Then exactly one GET to `repositoryInfo` is made; the session has a
  `JSESSIONID` cookie.

### 4.2 `test_connection` parses repository info
- Given a mocked `repositoryInfo` response with the standard CMIS shape.
- When `test_connection()` returns.
- Then the result has keys `repository_id`, `product_name`,
  `product_version`, `vendor_name`.

### 4.3 `ensure_folder` skips system folders
- Given `folder_path = "/$type/BAC_01_02_04_01_01"`.
- When `ensure_folder` is called.
- Then exactly ONE createFolder POST is made (for `BAC_01_02_04_01_01`),
  none for `$type`.

### 4.4 `ensure_folder` recursive with cache
- Given `folder_path = "/A/B/C"` and no prior calls.
- When `ensure_folder` is called twice in a row.
- Then on the first call, 3 createFolder POSTs are made (one per
  segment). On the second call, ZERO POSTs are made (cache hits).

### 4.5 `ensure_folder` 409 treated as success
- Given a createFolder mock that returns HTTP 409.
- When `ensure_folder` is called.
- Then no exception is raised, and the path is added to the cache.

### 4.6 `upload` happy path with succinct properties
- Given a multipart createDocument mock returning 201 with
  `succinctProperties.cmis:objectId = "abc-123"`.
- When `upload(...)` is called.
- Then the returned `objectId` is `"abc-123"` and the request body
  contains all configured `propertyId[i] / propertyValue[i]` pairs in
  order.

### 4.7 `upload` falls back to standard properties for objectId
- Given a 201 response with only `properties.cmis:objectId.value = "def-456"`.
- When `upload(...)` is called.
- Then the returned `objectId` is `"def-456"`.

### 4.8 `upload` falls back to data["id"] for objectId
- Given a 201 response with only `id = "ghi-789"` (no succinct, no
  properties).
- When `upload(...)` is called.
- Then the returned `objectId` is `"ghi-789"`.

### 4.9 `upload` retries 5xx with backoff
- Given two 503s followed by a 201.
- When `upload(...)` is called with `retry_max_attempts=3`,
  `retry_base_delay_s=0.0` (test override to avoid sleep).
- Then exactly 3 POSTs are made, the final one wins, and the result is
  the parsed objectId.

### 4.10 `upload` fails fast on 4xx
- Given a 400 response.
- When `upload(...)` is called.
- Then `CMISClientError(status_code=400, ...)` is raised after exactly
  ONE POST.

### 4.11 `upload` re-warms on 401 and retries once
- Given a 401 followed by a 201.
- When `upload(...)` is called.
- Then 2 POSTs to the upload URL plus 2 GETs to `repositoryInfo`
  (initial warmup + re-warmup) are made; the result is the parsed
  objectId.

### 4.12 `upload` exhausts retries → RetriesExhaustedError
- Given 4 consecutive 503s and `retry_max_attempts=3`.
- When `upload(...)` is called.
- Then `RetriesExhaustedError(txn_num=..., attempts=3)` is raised; the
  last `CMISServerError` is available via `__cause__`.

### 4.13 `upload` streams via MultipartEncoder
- Given a large staged file (synthetic, ~1 MB).
- When `upload(...)` is called.
- Then the request body is sent with the `MultipartEncoder` content type
  (`multipart/form-data; boundary=...`). The test inspects the
  recorded request to assert the boundary is present and the file's
  content matches.

### 4.14 BandwidthLimiter throttles read rate
- Given a 1 MB stream and `max_bandwidth_mbps = 0.5`.
- When the limiter is consumed end-to-end.
- Then elapsed time MUST be ≥ 2.0 seconds (1 MB / 0.5 MB/s) — within
  ±20 % tolerance for scheduler noise.

### 4.15 BandwidthLimiter `mbps=0` passes through
- Given `mbps = 0.0`.
- When `BandwidthLimiter(stream, 0.0)` is constructed.
- Then `isinstance(result, BandwidthLimiter)` is False — the function
  returns `stream` unchanged. (Or equivalent: the limiter is a no-op
  wrapper. Test asserts behavior, not type.)

### 4.16 Windows 10053 doubles delay
- Given a connection error with `str(exc)` containing `"10053"`,
  followed by a 201.
- When `upload(...)` is called.
- Then an `ERROR` log line names `10053` and the next sleep delay is
  double the configured base (measured via captured delays in a test
  monkey-patch of `time.sleep`).

---

## 5. Non-functional requirements

- **NFR-001** Memory: a single upload MUST stream the file from disk
  (Constitution IV). Inspecting the test process at peak MUST show that
  the test does NOT hold the full file in memory.
- **NFR-002** Branch coverage on `adapters/upload/cmis_uploader.py` MUST
  be ≥ 85% (lower target than other adapters because the retry/error
  matrix has many small branches; covering every retry permutation is
  impractical).
- **NFR-003** Function length cap (Constitution III): every method ≤ 50
  lines. The retry loop is the longest method and MUST stay under that
  budget; if it grows, extract a helper.
- **NFR-004** No third-party imports in the test file beyond `pytest`,
  `responses`, and `requests`.

---

## 6. Tooling expectations

- `ruff check src/ tests/`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.adapters.upload.*`: clean (uses the
  existing `types-requests` stubs; `requests-toolbelt` is already in
  `ignore_missing_imports`).
- `pre-commit run --all-files`: clean.
- `responses>=0.25,<1.0` added to `[project.optional-dependencies].dev`;
  `pip install -e .[dev]` re-runs to fetch it.
- `pytest`: full suite passes; net positive test count.

---

## 7. Open questions / risks

- **Risk**: `requests-toolbelt.MultipartEncoder` is incompatible with
  `responses`'s default body capture — `responses` may not see the
  multipart body. Mitigation: tests inspect the recorded `request.body`
  via the `responses` callback API; for the streaming test, we register
  a `responses.add_callback` that records the body length and content
  type rather than asserting on the raw body string.
- **Risk**: token bucket precision on slow CI runners may make the
  bandwidth test flaky. Mitigation: ±20 % tolerance + `0.5 MB/s` cap (not
  too slow, not too fast).
- **Risk**: `MultipartEncoder` consumes the underlying stream lazily;
  if `BandwidthLimiter` doesn't proxy `seek`/`tell`, the encoder may
  raise. Mitigation: REQ-024 requires the proxy; tests assert these
  methods exist.
- **Open question**: should the uploader expose a `metrics` hook
  (request timings, retry counts) for the future observability tier
  (REBIRTH §17.4)? **Resolved**: no — observability wraps the adapter
  in a decorator; the adapter only logs.

# 060 — Migrate CmisUploader from requests to httpx[http2]

## Why

On the staging diagnosis (058) we proved the bottleneck is **upload-bound,
outside the program**: the Alfresco server holds ~1.5 s p50 per POST, and
the average doc is small (~76 KB). For docs that small, the **overhead per
request** (RTT + per-request bookkeeping) dominates transfer time. The
canonical remedy when the workload is "many small uploads in parallel" is
HTTP/2 multiplexing: instead of N TCP connections each carrying one
request at a time, **one TCP connection carries all N requests
simultaneously**.

`requests` does not speak HTTP/2. `httpx` does. The Alfresco production
endpoint sits behind an Apache reverse proxy that negotiates HTTP/2 via
ALPN — so the migration is expected to pay off in prod, where it counts.
Staging (Tomcat-direct, HTTP/1.1) is a no-op fallback — the same code
keeps working.

## What

### 1. Adapter rewrite — `CmisUploader`

`requests.Session` → `httpx.Client(http2=True)`. httpx negotiates HTTP/2
via ALPN; if the server speaks only HTTP/1.1, it falls back transparently
— same wire protocol as today, same behaviour. When the server *does*
speak HTTP/2, the N concurrent workers share one TCP connection and
upload latency drops.

Concrete substitutions:

- `requests.Session()` → `httpx.Client(http2=True, limits=httpx.Limits(...))`.
- `HTTPAdapter(pool_connections=N, pool_maxsize=N)` → `httpx.Limits(
  max_connections=N, max_keepalive_connections=N)`.
- `requests_toolbelt.MultipartEncoder` → httpx's native `files=` /
  `data=` multipart API. The body is streamed from disk (same memory
  footprint).
- `requests.exceptions.ConnectionError` → `httpx.ConnectError /
  httpx.NetworkError / httpx.RemoteProtocolError`.
- The Windows 10053 abort detection (substring match on the exception
  string) is preserved — the OS-level message is the same regardless
  of the HTTP client library.

The `BandwidthLimiter` (rate-limited file wrapper) passes through
unchanged — httpx accepts any `IO[bytes]`-like for multipart files.

### 2. Tests — `test_cmis_uploader.py`

The 55+ tests use `responses` (a `requests`-specific HTTP mock).
Migrate them to `respx`, which is the httpx-native equivalent. Same
shape: register URL + method + response; assert on call URLs, headers,
status codes. The `@responses.activate` decorator becomes
`@respx.mock`.

### 3. Dependencies

- Remove `requests`, `requests-toolbelt`, `responses`, `types-requests`.
- Add `httpx[http2]` (which pulls `h2` + `hpack` + `hyperframe`), `respx`
  (dev-only).

### 4. Public API — unchanged

`IUploader.upload(...)` signature stays as it is (the spec 055 keyword
`batch_id` is still there). The wiring layer (`config/wiring.py`) keeps
constructing a `CmisUploader(CmisConfig(...))` exactly as before. Every
caller is byte-compatible.

## Out of scope

- `async`/`await`. httpx has `AsyncClient` but the orchestrator runs on
  a `ThreadPoolExecutor` and uses sync calls — converting to async would
  require rewriting the entire S5 dispatch loop. Sync `httpx.Client` is
  thread-safe and works perfectly with our existing pool. The HTTP/2
  multiplexing benefit does NOT require async — sync is enough.
- HTTP/2 server push or stream prioritization. Default httpx behaviour
  is fine.
- Removing the warm-pool concept. `warm_connection_pool(n)` still
  exists; with HTTP/2 it warms a single connection but the GET is still
  useful as a JSESSIONID prime + ALPN handshake.

## Acceptance criteria

- `CmisUploader` is built with `httpx.Client(http2=True)` and accepts
  the same `CmisConfig` it does today.
- A `respx.mock`-driven happy-path test asserts a successful upload
  returns the expected `cmis:objectId`.
- A `respx.mock` retry test asserts 5xx → retry → 201 still works (the
  retry policy in `_post_with_retries` is preserved).
- A `respx.mock` 4xx test asserts `CMISClientError` is still raised
  with the right status_code.
- A `respx.mock` Windows-10053 simulation asserts the doubled backoff
  is still applied.
- A test reads the on-the-wire protocol header from a real localhost
  HTTP/2 echo (or asserts `client.http2 is True` directly) so we have
  a regression line proving HTTP/2 is enabled.
- Full unit + integration suite green; mypy + ruff clean.
- `pyproject.toml` no longer carries `requests`, `requests-toolbelt`,
  `responses`, `types-requests`; carries `httpx[http2]` (main) and
  `respx` (dev).
- `CHANGELOG.md [0.62.0]` describes the migration with the prod
  expectation (HTTP/2 multiplexing on Apache-fronted Alfresco) and the
  staging behaviour (HTTP/1.1 fallback, no change in latency).
- `pyproject.toml` 0.61.0 → 0.62.0.

## Notes on test strategy

`respx` is API-compatible with `responses` in spirit but the syntax
differs. The migration is mechanical for the most part: register the
URL/method/json on a `respx.mock` router instead of `responses.add`,
and assert on `respx_mock.calls` instead of `responses.calls`. The
window where coverage could regress is the multipart body shape — we
add an explicit assertion that the request `Content-Type` starts with
`multipart/form-data; boundary=` (already there) plus that the body
contains the expected file content.

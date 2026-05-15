# 060 — Plan

Four phases. Tests are the bulk.

## Phase 1 — Adapter migration (~30 min)

### Files

- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - Imports: `requests` → `httpx`. Remove `requests.adapters.HTTPAdapter`,
    `requests.exceptions.ConnectionError`, `requests_toolbelt.MultipartEncoder`.
  - `__init__`: build `httpx.Client(http2=True, limits=httpx.Limits(
    max_connections=pool_size, max_keepalive_connections=pool_size),
    timeout=httpx.Timeout(timeout_seconds), verify=verify_ssl)`.
  - `_warmup_session`: `self._client.get(...)` instead of
    `self._session.get(...)`. Auth via `httpx.BasicAuth` or `auth=(u, p)`
    on the client.
  - `_build_multipart_for_upload`: rewrite to return a `files=` dict
    consumable by httpx's `client.post(..., files={...}, data={...})`.
    Keep `BandwidthLimiter` wrapping the file stream.
  - `_post_with_retries`: `client.post(...)` instead of `session.post(...)`.
    The retry / 401 re-warm / 5xx-loop logic is preserved.
  - `_emit_network`: `size_bytes` comes from the staged file (we already
    have it explicitly — `file.size_bytes` is passed through `upload()`),
    not from `encoder.len`. Cleaner.
  - Exception mapping:
    - `httpx.ConnectError` / `httpx.NetworkError` / `httpx.RemoteProtocolError`
      → treated as the old `RequestsConnectionError` for retry.
    - The `_WINDOWS_ABORT_MARKER` substring check remains — the OS error
      surface is the same regardless of HTTP library.
  - `verify_folder_exists` / `test_connection` / `get_type_definition` /
    `_lookup_existing_object_id`: mechanical `session.get` →
    `client.get`.

### Verify

`mypy src/cmcourier/adapters/upload/cmis_uploader.py` clean.

## Phase 2 — Test migration (~45 min)

### Files

- `tests/integration/adapters/test_cmis_uploader.py`
  - Imports: `import responses` → `import respx`. `import requests` stays
    (a few tests reference exception types — re-point to httpx).
  - `@responses.activate` → `@respx.mock`. The decorator gives us a
    `respx_mock` arg with the router.
  - `responses.add(responses.POST, url, json=..., status=...)` →
    `respx_mock.post(url).mock(return_value=httpx.Response(status, json=...))`.
  - `responses.calls` → `respx_mock.calls`. The call objects' attributes
    are slightly different: `call.request.url`, `call.request.headers`,
    `call.request.method` — same as the httpx Request type.
  - Connection-error simulations (`responses.add(..., body=requests.exceptions.ConnectionError(...))`)
    → `respx_mock.post(url).mock(side_effect=httpx.ConnectError("..."))`.
  - Auth tests: `httpx.Client` takes `auth=(username, password)` — the
    Basic-Auth header should still match.

### Verify

`pytest tests/integration/adapters/test_cmis_uploader.py -q` — all 55+
tests pass.

## Phase 3 — Dependency + release dance (~15 min)

### Files

- `pyproject.toml`:
  - `dependencies`: remove `requests`, `requests-toolbelt`. Add
    `httpx[http2]>=0.27,<1.0`.
  - `[project.optional-dependencies] dev`: remove `responses`,
    `types-requests`. Add `respx>=0.21,<1.0`.
- Bump `version` 0.61.0 → 0.62.0.
- `CHANGELOG.md` `[0.62.0]` — Changed (HTTP client migrated to
  httpx[http2]; HTTP/2 multiplexing in prod where Apache fronts
  Alfresco; HTTP/1.1 fallback otherwise — no behaviour change in
  staging Tomcat-direct).
- `README.md` feature row tick.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.62.0
```

### Verify

`grep -rn "import requests\|from requests" src/cmcourier/` — empty
result (only test files may still reference exception types via
httpx-namespace).

## Phase 4 — Full suite + FF to main (~10 min)

- `.venv/bin/python -m pytest tests/unit tests/integration` — full suite
  green.
- `.venv/bin/ruff check` + `.venv/bin/mypy src/cmcourier` — clean.
- Commit per phase:
  - Phase 1 + 2 combined: `feat(s5): migrate CmisUploader to httpx[http2] for HTTP/2 multiplexing in prod (060 Phase 1+2)`.
  - Phase 3: `docs(060): CHANGELOG 0.62.0 + version bump + deps swap (060 Phase 3)`.
- FF to main.

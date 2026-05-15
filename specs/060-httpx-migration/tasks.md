# 060 — Tasks

## Phase 1 — Adapter migration

- [ ] 1.1 Imports: requests / requests_toolbelt → httpx.
- [ ] 1.2 `__init__` builds `httpx.Client(http2=True, limits=..., timeout=..., auth=..., verify=...)`.
- [ ] 1.3 `_warmup_session`, `_post_with_retries`, `verify_folder_exists`,
      `test_connection`, `get_type_definition`, `_lookup_existing_object_id`:
      `session.*` → `client.*`.
- [ ] 1.4 `_build_multipart_for_upload`: returns httpx-compatible `files=` dict.
- [ ] 1.5 `_emit_network`: size_bytes from `staged_file.size_bytes`.
- [ ] 1.6 Exception mapping: httpx.ConnectError/NetworkError/RemoteProtocolError → retry path.
- [ ] 1.7 mypy clean.

## Phase 2 — Test migration

- [ ] 2.1 Imports: responses → respx; `import requests` → `import httpx`.
- [ ] 2.2 `@responses.activate` → `@respx.mock`.
- [ ] 2.3 Every `responses.add(...)` → equivalent `respx_mock.<method>(url).mock(...)`.
- [ ] 2.4 `responses.calls` → `respx_mock.calls`.
- [ ] 2.5 ConnectionError simulations → `httpx.ConnectError` via `side_effect`.
- [ ] 2.6 All 55+ tests pass.

## Phase 3 — Deps + CHANGELOG + version + README

- [ ] 3.1 `pyproject.toml` dependencies swap.
- [ ] 3.2 Version 0.61.0 → 0.62.0.
- [ ] 3.3 `CHANGELOG.md [0.62.0]`.
- [ ] 3.4 `README.md` feature row tick.
- [ ] 3.5 `pip install -e . --no-deps` + version check.
- [ ] 3.6 No stray requests imports in `src/cmcourier/`.

## Phase 4 — Full suite + FF

- [ ] 4.1 Full unit + integration suite green; ruff + mypy clean.
- [ ] 4.2 Commit Phase 1+2.
- [ ] 4.3 Commit Phase 3.
- [ ] 4.4 FF to main.

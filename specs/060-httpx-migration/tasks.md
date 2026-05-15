# 060 — Tasks

## Fase 1 — Migración del adapter

- [x] 1.1 Imports: requests / requests_toolbelt → httpx.
- [x] 1.2 `__init__` construye
      `httpx.Client(http2=True, limits=..., timeout=..., auth=..., verify=...)`.
- [x] 1.3 `_warmup_session`, `_post_with_retries`,
      `verify_folder_exists`, `test_connection`,
      `get_type_definition`, `_lookup_existing_object_id`:
      `session.*` → `client.*`.
- [x] 1.4 `_build_multipart_for_upload`: devuelve dict
      `files=` compatible con httpx.
- [x] 1.5 `_emit_network`: size_bytes desde
      `staged_file.size_bytes`.
- [x] 1.6 Mapeo de excepciones:
      httpx.ConnectError/NetworkError/RemoteProtocolError →
      camino de retry.
- [x] 1.7 mypy limpio.

## Fase 2 — Migración de tests

- [x] 2.1 Imports: responses → respx; `import requests` →
      `import httpx`.
- [x] 2.2 `@responses.activate` → `@respx.mock`.
- [x] 2.3 Cada `responses.add(...)` → `respx_mock.<method>(url).mock(...)`
      equivalente.
- [x] 2.4 `responses.calls` → `respx_mock.calls`.
- [x] 2.5 Simulaciones de ConnectionError →
      `httpx.ConnectError` vía `side_effect`.
- [x] 2.6 Los 55+ tests pasan.

## Fase 3 — Deps + CHANGELOG + version + README

- [x] 3.1 Swap de dependencies en `pyproject.toml`.
- [x] 3.2 Version 0.61.0 → 0.62.0.
- [x] 3.3 `CHANGELOG.md [0.62.0]`.
- [x] 3.4 Tick en fila de features de `README.md`.
- [x] 3.5 `pip install -e . --no-deps` + chequeo de versión.
- [x] 3.6 Sin imports sueltos de requests en
      `src/cmcourier/`.

## Fase 4 — Suite completa + FF

- [x] 4.1 Suite completa unit + integration verde; ruff +
      mypy limpios.
- [x] 4.2 Commit Fase 1+2.
- [x] 4.3 Commit Fase 3.
- [x] 4.4 FF a main.

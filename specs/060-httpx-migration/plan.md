# 060 — Plan

Cuatro fases. Los tests son la mayor parte.

## Fase 1 — Migración del adapter (~30 min)

### Archivos

- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - Imports: `requests` → `httpx`. Remover
    `requests.adapters.HTTPAdapter`,
    `requests.exceptions.ConnectionError`,
    `requests_toolbelt.MultipartEncoder`.
  - `__init__`: construir
    `httpx.Client(http2=True, limits=httpx.Limits(
    max_connections=pool_size,
    max_keepalive_connections=pool_size),
    timeout=httpx.Timeout(timeout_seconds), verify=verify_ssl)`.
  - `_warmup_session`: `self._client.get(...)` en vez de
    `self._session.get(...)`. Auth vía `httpx.BasicAuth` o
    `auth=(u, p)` sobre el client.
  - `_build_multipart_for_upload`: reescribir para devolver
    un dict `files=` consumible por
    `client.post(..., files={...}, data={...})` de httpx.
    Mantener `BandwidthLimiter` envolviendo el stream del
    archivo.
  - `_post_with_retries`: `client.post(...)` en vez de
    `session.post(...)`. La lógica de retry / re-warm de 401
    / loop de 5xx se preserva.
  - `_emit_network`: `size_bytes` viene del staged file (ya
    lo tenemos explícito — `file.size_bytes` se pasa a
    través de `upload()`), no de `encoder.len`. Más limpio.
  - Mapeo de excepciones:
    - `httpx.ConnectError` / `httpx.NetworkError` /
      `httpx.RemoteProtocolError` → tratados como el viejo
      `RequestsConnectionError` para retry.
    - El chequeo de substring `_WINDOWS_ABORT_MARKER` se
      queda — la superficie del error OS es la misma sin
      importar la library HTTP.
  - `verify_folder_exists` / `test_connection` /
    `get_type_definition` / `_lookup_existing_object_id`:
    mecánico `session.get` → `client.get`.

### Verify

`mypy src/cmcourier/adapters/upload/cmis_uploader.py` limpio.

## Fase 2 — Migración de tests (~45 min)

### Archivos

- `tests/integration/adapters/test_cmis_uploader.py`
  - Imports: `import responses` → `import respx`.
    `import requests` queda (algunos tests referencian tipos
    de excepción — re-apuntar a httpx).
  - `@responses.activate` → `@respx.mock`. El decorador nos
    da un arg `respx_mock` con el router.
  - `responses.add(responses.POST, url, json=..., status=...)`
    →
    `respx_mock.post(url).mock(return_value=httpx.Response(status, json=...))`.
  - `responses.calls` → `respx_mock.calls`. Los atributos
    de los objetos call son ligeramente distintos:
    `call.request.url`, `call.request.headers`,
    `call.request.method` — igual que el tipo Request de
    httpx.
  - Simulaciones de error de conexión
    (`responses.add(..., body=requests.exceptions.ConnectionError(...))`)
    →
    `respx_mock.post(url).mock(side_effect=httpx.ConnectError("..."))`.
  - Tests de auth: `httpx.Client` toma `auth=(username,
    password)` — el header Basic-Auth todavía debe matchear.

### Verify

`pytest tests/integration/adapters/test_cmis_uploader.py -q`
— los 55+ tests pasan.

## Fase 3 — Dependencia + release dance (~15 min)

### Archivos

- `pyproject.toml`:
  - `dependencies`: remover `requests`,
    `requests-toolbelt`. Agregar
    `httpx[http2]>=0.27,<1.0`.
  - `[project.optional-dependencies] dev`: remover
    `responses`, `types-requests`. Agregar
    `respx>=0.21,<1.0`.
- Bumpear `version` 0.61.0 → 0.62.0.
- `CHANGELOG.md` `[0.62.0]` — Changed (cliente HTTP migrado
  a httpx[http2]; multiplexing HTTP/2 en prod donde Apache
  fronta a Alfresco; fallback HTTP/1.1 sino — sin cambio de
  comportamiento en staging Tomcat-directo).
- Tick en fila de features de `README.md`.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.62.0
```

### Verify

`grep -rn "import requests\|from requests" src/cmcourier/`
— resultado vacío (solo los archivos de test pueden seguir
referenciando tipos de excepción vía el namespace de httpx).

## Fase 4 — Suite completa + FF a main (~10 min)

- `.venv/bin/python -m pytest tests/unit tests/integration` —
  suite completa verde.
- `.venv/bin/ruff check` + `.venv/bin/mypy src/cmcourier` —
  limpio.
- Commit por fase:
  - Fase 1 + 2 combinadas:
    `feat(s5): migrate CmisUploader to httpx[http2] for HTTP/2 multiplexing in prod (060 Phase 1+2)`.
  - Fase 3: `docs(060): CHANGELOG 0.62.0 + version bump + deps swap (060 Phase 3)`.
- FF a main.

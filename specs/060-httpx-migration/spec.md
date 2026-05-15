# 060 — Migrar CmisUploader de requests a httpx[http2]

## Por qué

En el diagnóstico de staging (058) probamos que el cuello de
botella es **upload-bound, afuera del programa**: el server
Alfresco aguanta ~1.5 s p50 por POST, y el doc promedio es
chico (~76 KB). Para docs así de chicos, el **overhead por
request** (RTT + bookkeeping per-request) domina el tiempo de
transferencia. El remedio canónico cuando la carga es "muchos
uploads chicos en paralelo" es **multiplexing** HTTP/2: en
vez de N conexiones TCP cada una llevando un request a la
vez, **una conexión TCP lleva los N requests simultáneamente**.

`requests` no habla HTTP/2. `httpx` sí. El endpoint de
producción de Alfresco está detrás de un proxy reverso Apache
que negocia HTTP/2 vía `ALPN` — así que la migración se
espera que pague en prod, donde cuenta. Staging
(Tomcat-directo, HTTP/1.1) es un fallback no-op — el mismo
código sigue andando.

## Qué

### 1. Reescritura del adapter — `CmisUploader`

`requests.Session` → `httpx.Client(http2=True)`. httpx negocia
HTTP/2 vía `ALPN`; si el server solo habla HTTP/1.1, hace
fallback transparente — mismo protocolo de cable que hoy,
mismo comportamiento. Cuando el server *sí* habla HTTP/2, los
N workers concurrentes comparten una conexión TCP y la
latencia de upload baja.

Substituciones concretas:

- `requests.Session()` →
  `httpx.Client(http2=True, limits=httpx.Limits(...))`.
- `HTTPAdapter(pool_connections=N, pool_maxsize=N)` →
  `httpx.Limits(max_connections=N,
  max_keepalive_connections=N)`.
- `requests_toolbelt.MultipartEncoder` → la API multipart
  nativa de httpx `files=` / `data=`. El body se streamea
  desde disco (mismo footprint de memoria).
- `requests.exceptions.ConnectionError` → `httpx.ConnectError
  / httpx.NetworkError / httpx.RemoteProtocolError`.
- La detección del aborto Windows 10053 (match de substring
  sobre el string de la excepción) se preserva — el mensaje
  a nivel OS es el mismo sin importar la library de cliente
  HTTP.

El `BandwidthLimiter` (wrapper de archivo rate-limited) pasa
sin cambios — httpx acepta cualquier `IO[bytes]`-like para
files de multipart.

### 2. Tests — `test_cmis_uploader.py`

Los 55+ tests usan `responses` (un mock HTTP específico de
`requests`). Migrarlos a `respx`, que es el equivalente
nativo de httpx. Misma forma: registrar URL + method +
response; assertear sobre URLs de llamada, headers, status
codes. El decorador `@responses.activate` pasa a ser
`@respx.mock`.

### 3. Dependencias

- Remover `requests`, `requests-toolbelt`, `responses`,
  `types-requests`.
- Agregar `httpx[http2]` (que tira de `h2` + `hpack` +
  `hyperframe`), `respx` (solo dev).

### 4. API pública — sin cambios

La firma de `IUploader.upload(...)` se queda como está (el
keyword `batch_id` de la spec 055 sigue ahí). La capa de
wiring (`config/wiring.py`) sigue construyendo
`CmisUploader(CmisConfig(...))` exactamente como antes. Cada
caller es byte-compatible.

## Fuera de alcance

- `async`/`await`. httpx tiene `AsyncClient` pero el
  orchestrator corre sobre un `ThreadPoolExecutor` y usa
  llamadas sync — convertir a async requeriría reescribir el
  loop de dispatch entero de S5. El `httpx.Client` sync es
  thread-safe y funciona perfectamente con nuestro pool
  existente. El beneficio del multiplexing HTTP/2 NO requiere
  async — sync alcanza.
- Server push de HTTP/2 o priorización de streams. El
  comportamiento default de httpx está bien.
- Remover el concepto de pool tibio. `warm_connection_pool(n)`
  todavía existe; con HTTP/2 calienta una sola conexión pero
  el GET sigue siendo útil como prime de JSESSIONID +
  handshake de `ALPN`.

## Criterios de aceptación

- `CmisUploader` se construye con `httpx.Client(http2=True)`
  y acepta la misma `CmisConfig` que hoy.
- Un test happy-path impulsado por `respx.mock` assertea que
  un upload exitoso devuelve el `cmis:objectId` esperado.
- Un test de retry con `respx.mock` assertea que 5xx →
  retry → 201 sigue andando (la política de retry en
  `_post_with_retries` se preserva).
- Un test 4xx con `respx.mock` assertea que se sigue
  levantando `CMISClientError` con el status_code correcto.
- Una simulación Windows-10053 con `respx.mock` assertea que
  el backoff doblado todavía se aplica.
- Un test lee el header de protocolo on-the-wire desde un
  echo HTTP/2 real en localhost (o assertea
  `client.http2 is True` directo) así tenemos una línea de
  regresión probando que HTTP/2 está habilitado.
- Suite completa unit + integration verde; mypy + ruff
  limpios.
- `pyproject.toml` ya no lleva `requests`,
  `requests-toolbelt`, `responses`, `types-requests`; lleva
  `httpx[http2]` (main) y `respx` (dev).
- `CHANGELOG.md [0.62.0]` describe la migración con la
  expectativa de prod (multiplexing HTTP/2 sobre Alfresco
  fronted-por-Apache) y el comportamiento de staging
  (fallback HTTP/1.1, sin cambio en latencia).
- `pyproject.toml` 0.61.0 → 0.62.0.

## Notas sobre estrategia de tests

`respx` es API-compatible con `responses` en espíritu pero la
sintaxis difiere. La migración es mecánica en su mayoría:
registrar la URL/method/json en un router `respx.mock` en vez
de `responses.add`, y assertear sobre `respx_mock.calls` en
vez de `responses.calls`. La ventana donde la cobertura
podría regresarse es la forma del body de multipart —
agregamos una aserción explícita de que el `Content-Type` del
request arranca con `multipart/form-data; boundary=` (ya
está ahí) más que el body contiene el contenido del archivo
esperado.

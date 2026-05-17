# 076 — `MultipartEncoder` streaming para uploads CMIS

## Por qué

Durante las primeras pruebas productivas contra IBM Content Manager
v8, S5 (upload) corre a **3 MB/s** en circunstancias donde:

* El legacy ``RVIMigration`` corría a **45 MB/s** contra la **misma
  infra** (mismo CM, misma red, mismo banco).
* `curl -F` directo desde la misma compu mide **55 MB/s** contra el
  mismo CM (sin guardar el doc, pero los bytes se transmiten).
* `cmis.workers: 20`, `auto_tune.enabled: true` con
  `max_threads: 32` — el pool de upload está saturado (busy 20),
  no es problema de concurrencia.
* `p95: 51028 ms` — cada upload **individual** tarda ~51 segundos.
  El throughput no es lento por falta de paralelismo; es lento
  porque **cada upload por sí solo es brutal**.
* `current_mbps < 1`, `peak_mbps: 7` — picos breves cuando alguno
  termina su pre-buffer, después caen.
* Forzar `http2=False` no cambió nada — descartado HTTP/2 como
  causa.

## La causa raíz

`src/cmcourier/adapters/upload/cmis_uploader.py:790-795`:

```python
resp = self._client.post(
    url,
    data=data_fields,
    files={"content": file_field},
    timeout=self._timeout_s,
)
```

**`httpx.Client.post(files={...})` no hace true streaming**. Lee
el file handle entero en memoria para armar el body multipart como
un único `bytes` blob, después abre el socket TCP y transmite.

Para 20 workers en paralelo subiendo docs de ~25 MB:

* **20 × 25 MB = 500 MB** allocados en RAM simultáneamente antes
  de transmitir el primer byte.
* **20 threads** ejecutando el armado del body multipart en Python
  puro → pelea por el GIL.
* **20 buffers** atravesando el garbage collector seguido →
  GC pauses cascading.
* Los sockets TCP están **idle** durante la fase pre-buffer.

El legacy (pre-060) usaba `requests` + `requests-toolbelt.MultipartEncoder`:

* Encoder **lazy**: NO lee el archivo al construirse.
* Calcula `Content-Length` del file size + headers, sin tocar el body.
* Lee chunks de 8 KB del disco y los manda **directo al socket
  TCP**, on demand.
* Cero buffer en RAM, cero pelea por el GIL en el body armado,
  cero GC pressure.

curl con `-F` hace conceptualmente lo mismo (chunked transfer).
Por eso curl mide 55 MB/s y el legacy 45 MB/s contra el mismo CM
donde CMCourier mide 3 MB/s.

> Spec 060 (migración de `requests` a `httpx[http2]`) probó solo
> contra Alfresco con frontend Apache. HTTP/2 multiplexing con
> Alfresco absorbe el problema del pre-buffer porque concentra
> múltiples uploads en una sola conexión TCP eficiente. Contra
> IBM CM v8 (HTTP/1.1 puro, sin multiplexing), el bug se vuelve
> dominante.

## Qué

### Alcance

Reemplazar el armado del body multipart en `_post_with_retries`
para usar `MultipartEncoder` de `requests-toolbelt`, pasándolo a
httpx vía `content=` + `Content-Type` header explícito.

* **`src/cmcourier/adapters/upload/cmis_uploader.py:790-795`**:
  el `httpx.Client.post(data=..., files=...)` pasa a
  `httpx.Client.post(content=encoder, headers={"Content-Type": encoder.content_type})`.
* **El encoder se reconstruye en cada attempt** (es lazy, costo
  cero al construir; el `stream.seek(0)` actual sigue siendo
  necesario para que el file handle subyacente vuelva al inicio
  en retries).
* **`pyproject.toml`**: re-agregar `requests-toolbelt>=1.0,<2.0`
  como dependencia runtime. Ya estaba pre-060; spec 060 la sacó
  cuando migró a httpx, ahora la traemos de vuelta — solo
  usaremos el `MultipartEncoder`, no `requests` ni `RequestsAdapter`.

### Fuera de alcance

* **No revertir spec 060**. Seguimos con `httpx[http2]` para todo
  lo demás (warmup, retry policy, HTTP/2 multiplexing en
  Alfresco). Solo cambia el armado del body multipart.
* **No tocar lógica de retry / backoff / circuit-breaker**.
* **No agregar tests de integración con Alfresco real** — los
  tests existentes de `respx` (mock httpx) siguen funcionando
  porque el `client.post()` sigue siendo el mismo callsite.

## Criterios de aceptación

1. `cmis_uploader.py` importa `MultipartEncoder` desde
   `requests_toolbelt`.
2. El POST a CMIS usa `content=encoder` +
   `headers={"Content-Type": encoder.content_type}`, no
   `data=`/`files=`.
3. Retry rebuilds the encoder (cada attempt llama
   `MultipartEncoder(...)` de nuevo después de `stream.seek(0)`).
4. Tests unit cubren: encoder se construye con los fields y file
   correctos, Content-Type sale del encoder, los campos CMIS
   (`cmisaction`, `propertyId[N]`, `propertyValue[N]`,
   `content`) están todos en el body.
5. `pyproject.toml` declara `requests-toolbelt>=1.0,<2.0`.
6. `pytest -m unit` pasa sin regresiones.
7. Pre-commit verde (ruff + ruff-format + mypy).

## Riesgos

* **Re-agregamos una dep** que sacamos hace pocas specs. Acceptable —
  `requests-toolbelt` es maintained, ampliamente usado, y el
  problema que resuelve es real.
* **`MultipartEncoder` espera tuples `(filename, fileobj, content_type)`**
  para file fields, formato compatible con lo que ya tenemos en
  `file_field`. Cero adaptación.
* **El BandwidthLimiter envoltura sobre el file handle** sigue
  funcionando — MultipartEncoder lee del file via `.read(size)`
  como cualquier otro consumer.
* **Tests con `respx`**: respx mockea httpx a nivel de request
  enviada. Como ahora mandamos `content=` (bytes) en vez de
  `files=`, respx sigue capturando la request, pero el body
  se ve como un blob multipart en vez de campos separados.
  Adaptar los tests que asseraban sobre campos específicos.

## Plan B si NO resuelve

Si después del patch sigue en 3 MB/s, hipótesis siguientes (en
orden de probabilidad):

1. **GIL contention en `httpx.Client.post`** independiente del
   body — probaríamos `AsyncClient` o multiproceso para S5.
2. **Windows TCP send buffers default** mal tuneados —
   `netsh int tcp set global autotuninglevel=normal` o tuning
   por-socket.
3. **Algún cuello específico de IBM CM v8** que el legacy
   bypassaba con headers/comportamiento que aún no replicamos.

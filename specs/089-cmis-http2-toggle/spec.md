# 089 — `cmis.http2` toggle (opt-out de HTTP/2 multiplexing)

## Por qué

Bug productivo descubierto en pruebas de throughput. Operador con
link de 1 Gbps subiendo archivos > 50 MB con 30 workers:

| Escenario | Throughput |
|---|---|
| `curl` UN archivo (HTTP/1.1) | ~100 MB/s (satura el link) |
| 30 workers paralelos (CMCourier, HTTP/2) | ~20 MB/s **agregado** |

0.67 MB/s por worker es absurdamente bajo. El cap NO es CPU (todos
busy) ni server-side per-doc (uploads grandes single funcionan).

## Causa raíz: flow-control window compartido de HTTP/2

CMCourier abre con `http2=True` desde spec 060. httpx negocia
HTTP/2 vía ALPN y reusa pocas conexiones TCP multiplexando muchos
streams encima. Cuando el server CMIS:

- Tiene `SETTINGS_INITIAL_WINDOW_SIZE` chico (default RFC: 64 KB
  por stream).
- No expande el connection-level window agresivamente.

…el throughput agregado queda capeado por la capacidad de
buffering del lado server. 30 streams compartiendo flow control
de una sola conexión TCP no escalan linealmente — se serializan.

HTTP/1.1 en cambio: cada worker mantiene **su propia TCP
connection** (hasta el `max_keepalive_connections` del pool), cada
una con su propio flow window TCP, sin multiplexing. Throughput
agregado escala con N workers hasta saturar el link.

## Qué

### Cambios

1. **`CmisConfigModel.http2: bool = True`** (schema): nuevo flag
   opt-out. Default `True` preserva spec 060 (negocia h2 vía ALPN).

2. **`CmisConfig.http2: bool = True`** (dataclass del adapter):
   mismo flag, propagado por wiring.

3. **`CmisUploader.__init__`**: pasa `http2=config.http2` al
   `httpx.Client` en vez del literal `True` hardcoded de spec 060.

4. **`wiring.py`**: copia el flag desde el schema al dataclass.

### Uso

```yaml
cmis:
  workers: 30
  http2: false                   # ← fuerza HTTP/1.1
```

Cuando el operador opta-out, cada worker abre una conexión TCP
exclusiva (hasta `pool_size = max(workers, auto_tune.max_threads)`),
sin multiplexing. Throughput agregado escala con N workers.

### Tests

* `tests/unit/adapters/upload/test_http2_toggle.py`:
  - default es `http2=True` (regresión)
  - `http2=False` propaga al constructor de `httpx.Client`
  - schema default + opt-in

## Criterios de aceptación

1. Sin override en YAML, `cmis.http2=True` y `httpx.Client` recibe
   `http2=True` — byte-idéntico a pre-089.
2. Con `cmis.http2: false`, `httpx.Client` recibe `http2=False` →
   solo HTTP/1.1.
3. Operador productivo en escenario "30 workers, archivos > 50 MB"
   reporta throughput agregado significativamente mejor con
   `http2: false`.
4. `pytest -m unit` pasa.

## Riesgos

* **Backward-compat total**. Configs pre-089 cargan idénticamente.
  Solo el operador que opta-out cambia el cliente.
* **HTTP/1.1 sin keepalive es lento**. El pool `max_keepalive`
  ya está dimensionado a `workers` desde spec 038 — keepalive
  funciona OK.
* **Servers sin HTTP/2**: ya funcionaban porque httpx con
  `http2=True` negocia ALPN y cae a 1.1. La spec 089 NO afecta ese
  path — solo agrega control explícito.
* **Compresión / header bloat**: HTTP/1.1 no tiene HPACK. Para
  CMIS, los headers son chicos (auth + multipart boundary), el
  overhead es despreciable.

## Notas

- Si en el futuro el server CMIS expone una manera de configurar
  `INITIAL_WINDOW_SIZE` más grande, HTTP/2 podría volver a ser más
  eficiente (menos TCP handshakes, header compression). Pero hoy,
  para este server con uploads grandes paralelos, HTTP/1.1 gana.
- httpx no expone un "force HTTP/2" — `http2=True` significa
  "negocia, fallback a 1.1". `http2=False` significa "solo 1.1".
  Por eso el flag es bool, no enum.

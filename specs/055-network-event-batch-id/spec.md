# 055 — Los eventos de red llevan el batch_id: desromper los handlers de bandwidth + slow-op

## Por qué

En un run de staging N=2 el operador reportó el tab UPLOAD
muerto: bandwidth `0.00 MB/s`, peak `0.00`, sparkline en
blanco, SLOW OPS "(none yet)". La spec 054 arregló *qué
recorder* lee el snapshot — un bug real — pero el operador
re-corrió y **todavía quedaba vacío**. 054 trató un síntoma;
esto es la causa raíz.

### La causa raíz — probada

`CmisUploader._emit_network` (`cmis_uploader.py`) construye el
`extra` del log record con `kind`, `duration_ms`, `url_prefix`,
`worker`, `status`, `size_bytes` — **pero nunca `batch_id`**.
El `CmisUploader` es un objeto compartido y usado
concurrentemente y su `upload()` nunca siquiera recibe un
`batch_id`.

Ambos handlers de métricas filtran por ese campo:

- `_BandwidthHandler.emit` →
  `if getattr(record, "batch_id", None) != self._batch_id: return`
- `_SlowOpHandler.emit` → el mismo cortocircuito
  `record_batch_id != self._batch_id`.

`getattr(record, "batch_id", None)` es `None`; `self._batch_id`
es un string real; `None != "B1"` → **cada evento
`cmis_upload` se descarta**, en *cada* recorder. La spec 042
agregó el filtro de `batch_id` a `_BandwidthHandler` (y 028 a
`_SlowOpHandler`) asumiendo que los eventos lo llevaban —
nunca lo llevaron. Desde entonces, el 100% del bandwidth de
upload y los slow-ops de upload se descartaron silenciosamente.

Probado con un repro que reproduce el `extra` exacto de
`_emit_network`:

```
(A) extra WITHOUT batch_id -> peak_mbps=0.0  cumulative=0        slow_ops=0
(B) extra WITH    batch_id -> peak_mbps=8.0  cumulative=8000000  slow_ops=2
```

Mismo evento, mismos bytes — la única diferencia es el campo
`batch_id`.

Esto también es por qué la spec 053 encontró que los archivos
`network-*.jsonl` no tienen `batch_id` y tuvo que asociarlos
por ventana de tiempo: la misma omisión de `_emit_network`.

## Qué

Pasar el `batch_id` del chunk a través del camino de upload
para que cada evento de red emitido durante `upload()` lo
lleve.

### 1. `IUploader.upload` — nuevo keyword requerido `batch_id`

`upload(self, file, folder_path, object_type_id, document_name,
mime_type, properties, *, batch_id: str) -> str`. Keyword-only
y **requerido** — sin default. Un default `""` re-introduciría
silenciosamente el bug la primera vez que un caller se olvide;
`batch_id` es un input de dominio legítimo, no un shim de
compatibilidad.

### 2. `CmisUploader` — propagarlo a cada emisor de red

- `CmisUploader.upload` acepta `batch_id` y lo pasa a
  `_post_with_retries`, `_emit_upload_attempt`,
  `_emit_upload_failed`.
- `_post_with_retries(..., *, batch_id: str)` lo pasa a
  `_emit_network`.
- `_emit_network(kind, t0, status, size_bytes, url, batch_id)`
  agrega `extra["batch_id"] = batch_id`.
- `_emit_upload_attempt` / `_emit_upload_failed` agregan
  `extra["batch_id"] = batch_id` también — el mismo
  `batch_id` ya está en scope, y hace los eventos de
  diagnóstico `s5_upload_attempt` / `s5_upload_failed` en
  `network-*.jsonl` también batch-atribuibles.

### 3. El call site — `staged.py`

El stage S5 del `StagedPipeline` ya tiene `batch_id` en scope
(construye el `StageTimer` con él). La llamada
`self._uploader.upload(...)` pasa `batch_id=batch_id`.

## Fuera de alcance

- Revertir la asociación por ventana de tiempo de la spec 053
  en `analyze.py`. Una vez que los records
  `network-*.jsonl` lleven `batch_id` de nuevo, el analyzer
  *podría* volver a un filtro exacto por `batch_id` — pero es
  un cambio separado, aditivo. El camino de ventana de tiempo
  de 053 sigue funcionando sin cambios; una spec de follow-up
  puede simplificarlo.
- `verify_folder_exists` / `test_connection` /
  `get_type_definition` — estos son pre-flight, single-shot,
  fuera del lifetime de cualquier batch; no emiten eventos
  `cmis_upload` y no son candidatos a slow-op.
- El split `_metrics` vs `_upload_metrics` de la spec 054 — ya
  entregado y correcto; es lo que hace que los eventos ahora
  entregados aterricen en el recorder correcto para un run
  N=2. 055 + 054 juntas arreglan el tab.

## Criterios de aceptación

- Una llamada a `CmisUploader.upload()` (HTTP mockeado) hecha
  mientras un `MetricsRecorder` tiene un batch abierto resulta
  en un `recorder.bandwidth.peak_mbps()` / `cumulative_bytes()`
  no-cero y un `aggregator_snapshot()` poblado — un test de
  regresión lo assertea. Este es el test que habría agarrado
  el bug: ejercita el `_emit_network` real, no un `extra`
  hand-built.
- El log record `cmis_upload` emitido por `_emit_network` tiene
  un atributo `batch_id` igual al valor pasado a `upload()`.
- `IUploader.upload` y cada implementación + call site toman
  el nuevo keyword; `mypy` queda limpio (el keyword requerido
  fuerza que cada call site sea actualizado — sin omisiones
  silenciosas).
- Suite completa unit + integration verde; mypy + ruff
  limpios.
- `CHANGELOG.md [0.58.0]`; `pyproject.toml` 0.57.0 → 0.58.0.

## Notas sobre estrategia de tests

El gap que dejó pasar esto: `test_cmis_uploader.py` mockea
HTTP pero nunca attachea un `MetricsRecorder` vivo, así que
nunca observó que el record emitido no tenía `batch_id`; y el
test de slow-op de `test_data_provider.py` construía a mano un
dict `extra` *con* `batch_id`, así que testeaba una forma que
el uploader real nunca produce. El test de regresión de 055
cierra ambos: una llamada real a `CmisUploader.upload()` bajo
un `MetricsRecorder.start_batch()` real, asserteando que el
sampler y aggregator realmente recibieron los bytes.

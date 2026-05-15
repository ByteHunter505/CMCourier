# 054 — Wiring del recorder del tab UPLOAD: terminar el split de 042

## Por qué

En un run de staging N=2 el operador reportó que el tab UPLOAD
estaba muerto: bandwidth `0.00 MB/s`, peak `0.00 MB/s`, la
sparkline de UPLOAD SPEED en blanco, SLOW OPS "(none yet)" — y
el timer por-chunk contaba desde un punto *muy anterior* al
arranque de S5, como si empezara en el lanzamiento del programa.

Dos bugs, ambos en `src/cmcourier/tui/data_provider.py`, ambos
fallout incompleto de la spec 042.

### Contexto — qué hizo 042

042 separó el binding del recorder de la TUI en dos:

- `recorder_provider` → `orchestrator.active_recorder()` — el
  recorder del chunk **más-recientemente-arrancado**. Cuando el
  chunk N+1 entra a PREP mientras el chunk N todavía está
  subiendo, esto se da vuelta a N+1.
- `upload_recorder_provider` → `orchestrator.upload_recorder()`
  — el recorder del chunk **realmente adentro de S5**. Se queda
  en N hasta que N termina.

Cada `MetricsRecorder` tiene su propio `_BandwidthHandler` y
`_SlowOpHandler` que **filtran log records por `batch_id`**
(`metrics.py` — `record.batch_id != self._batch_id` →
descartado). Así que el recorder del chunk en PREP (N+1) recibe
**cero** eventos `cmis_upload` — esos llevan el id del batch N
y aterrizan solo en el recorder de N.

En `data_provider.py`, `self._metrics` sigue a
`recorder_provider` (PREP-aware) y `self._upload_metrics` sigue
a `upload_recorder_provider` (UPLOAD-bound).

### Bug 1 — bandwidth / peak / sparkline / slow ops leen del recorder de PREP

042 movió `_current_chunk_progress` para leer
`self._upload_metrics`, pero **cuatro campos en `snapshot()`
quedaron en `self._metrics`**:

- `bandwidth_current_mbps = self._metrics.bandwidth.current_mbps()`
- `bandwidth_peak_mbps = self._metrics.bandwidth.peak_mbps()`
- `bandwidth_series = self._metrics.bandwidth.series(60)`
- `slow_ops_all = self._metrics.aggregator_snapshot()`

Durante el upload de N (con N+1 en PREP) `self._metrics` es el
recorder de N+1 — cuyo sampler de bandwidth y aggregator de
slow-op nunca vieron un solo byte del upload de N. Resultado:
los cuatro leen empty/cero. El test existente
`test_slow_ops_passes_through_aggregator` nunca lo agarró
porque construye el provider **sin** `upload_recorder_provider`,
así que `_metrics == _upload_metrics` y los dos no pueden
divergir.

### Bug 2 — el timer por-chunk mide desde el arranque de PREP

`_current_chunk_progress` deriva el `elapsed_s` del chunk
activo desde `prep_started_monotonic` — el momento en que el
chunk empezó a **preparar**, no a subir. El tab UPLOAD lo
renderiza como "chunk elapsed", así que para el chunk 0 cuenta
desde aproximadamente el lanzamiento del programa. También
envenena `current_chunk_avg_mbps = bytes_uploaded / elapsed_s`
— dividiendo bytes subidos por una ventana que incluye toda la
fase PREP, así que la velocidad promedio se lee mucho más baja
que la realidad.

`ChunkState` ya lleva `upload_started_monotonic` (stampeado
cuando el chunk entra a S5) y un `upload_elapsed_s` frozen
(stampeado en DONE) — el provider simplemente no los estaba
usando.

## Qué

### 1. Apuntar los campos de bandwidth + slow-ops al recorder de UPLOAD

En `snapshot()`, los cuatro campos de arriba leen de
`self._upload_metrics` en vez de `self._metrics`.
`self._upload_metrics` ya hace fallback a `self._metrics`
cuando ningún `upload_recorder_provider` está wireado (runs
single-batch), así que el comportamiento single-batch queda
sin cambios.

### 2. Medir el timer por-chunk desde el arranque de S5

`_current_chunk_progress` resuelve el `elapsed_s` del chunk
activo por status:

- `UPLOAD` → `now − upload_started_monotonic` (en vivo).
- `DONE` → el `upload_elapsed_s` frozen.
- `PREP` (o desconocido) → `0.0` — S5 no arrancó, no hay
  upload elapsed todavía. El guard de `_chunk_timer_line` ya
  suprime la línea cuando elapsed y bytes son ambos cero.
- Sin chunk activo (single-batch) → sin cambios: el elapsed
  global del run.

`current_chunk_avg_mbps` entonces divide bytes subidos por la
ventana de *upload*, así que reporta el throughput real de S5.

## Fuera de alcance

- Re-taguear los log records `network-*` / `system-*` con un
  `batch_id` real (la plomería de contextvar nombrada como
  fuera-de-alcance en 053) — no relacionado; esta spec es
  puramente el binding in-memory de la TUI.
- Cualquier cambio al filtrado de `_BandwidthHandler` /
  `_SlowOpHandler` — el filtro per-batch es correcto; el bug
  es qué recorder lee el snapshot.
- La columna RATE del tab CHUNKS (052) — ya lee
  `upload_elapsed_s` por-chunk y no se ve afectada.

## Criterios de aceptación

- Con un provider wireado con **divergent**
  `recorder_provider` (un recorder de PREP) y
  `upload_recorder_provider` (un recorder de UPLOAD que tiene
  data de bandwidth + slow-op), `snapshot()` devuelve
  `bandwidth_current_mbps` no-cero, `bandwidth_peak_mbps`
  no-cero, un `bandwidth_series` no-vacío, y los slow ops del
  recorder de UPLOAD en `slow_ops_all` — un test assertea cada
  uno.
- Para un chunk activo en status `UPLOAD`,
  `current_chunk_elapsed_s` mide desde
  `upload_started_monotonic`, no `prep_started_monotonic` —
  un test con ambos timestamps seteados assertea que el gap se
  excluye.
- Para un chunk activo en status `DONE`,
  `current_chunk_elapsed_s` iguala el `upload_elapsed_s` frozen.
- Para un chunk activo en status `PREP`,
  `current_chunk_elapsed_s` es `0.0`.
- El comportamiento single-batch (sin `upload_recorder_provider`)
  queda sin cambios — los tests existentes del data-provider
  quedan verdes.
- Suite completa unit + integration verde; mypy + ruff limpios.
- `CHANGELOG.md [0.57.0]`; `pyproject.toml` 0.56.0 → 0.57.0.

## Notas sobre estrategia de tests

El gap que dejó pasar ambos bugs es que ningún test del
data-provider wireaba recorders PREP y UPLOAD **divergentes**.
Los tests nuevos construyen el provider con dos
`MetricsRecorder` distintos — uno alimentado con data
PREP-shaped, uno alimentado con data UPLOAD-shaped (bytes + un
`cmis_upload` lento) — y assertean que el snapshot lee los
campos UPLOAD-shaped del de UPLOAD. Los casos del timer
por-chunk alimentan un `chunks_provider` devolviendo un único
dict de chunk con el status bajo test y ambos stamps monotónicos
seteados.

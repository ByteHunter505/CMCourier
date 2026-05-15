# 067 — Fixes de bugs de TUI en modo streaming

## Por qué

Reportados por el operador durante el primer run end-to-end
de streaming (configs 063→066 entregadas). Cuatro bugs
distintos, todos convergiendo en el mismo issue subyacente:
`StreamingOrchestrator` reusa la superficie de binding de la
TUI diseñada para el orchestrator batched sin realmente
poblar sus campos en vivo.

### Bug 1 — Barra de progreso del UPLOAD clavada en CURRENT/CURRENT

`upload_tab.render_upload` computa:

```python
target = max(count + snap.queue_depth, 1)
bar = _bar(count, target, width=28)
```

`snap.queue_depth` viene de
`pool_stats.snapshot().queue_depth`. El
`_stage_5_single` / `_stage_5_dual` del orchestrator batched
llama `pool_stats.set_queue_depth(...)` por ciclo. El
orchestrator de streaming nunca lo hace — así que queue_depth
queda en 0, target iguala a count, la barra muestra
`count/count` permanentemente.

### Bug 2 — El timer del chunk nunca arranca, avg speed siempre 0

`_current_chunk_progress` lee `status` del ChunkState
sintético. Streaming setea `status="PREP"` para todo el run,
así que:

```python
else:
    # PREP (o desconocido) — S5 no arrancó; sin upload elapsed todavía.
    elapsed_s = 0.0
```

Con `elapsed_s = 0`, `avg_mbps = 0`, y `_chunk_timer_line`
devuelve `None` porque elapsed Y bytes son los dos cero (la
función baila out temprano para evitar renderizar una línea
ruidosa de cero).

### Bug 3 — Tab CHUNKS frozen en cero durante el run

El chunk_state sintético tiene `s5_done`, `s5_failed`,
`doc_count`, `prep_done` todos seteados solo en el update
FINAL al final del run. Durante el run, se quedan en sus
valores iniciales de cero, así que el renderer del tab CHUNKS
muestra todo frozen en 0.

### Bug 4 — Contador de queue de LANES monotónico arriba, excede el bucket size

`_dispatcher_loop` mantiene contadores privados:

```python
heavy_depth = 0
light_depth = 0
while True:
    ...
    if size_bytes >= threshold:
        heavy_queue.put(stage_item)
        heavy_depth += 1
        self._lane_controller.set_queue_depth("heavy", heavy_depth)
```

El contador solo incrementa — nunca decrementa cuando un
consumer popea de `heavy_queue`. Así que la "queue" reportada
es un *conteo acumulado de encolados*, no una ocupación en
vivo. Después de 5000 docs muestra "queue 2500" aunque el
tamaño real de la queue nunca excede `bucket_size=200`.

La expectativa del operador (correcta): el campo "queue" de
LANES debería matchear `heavy_queue.qsize()` y
`light_queue.qsize()` — el conteo in-flight en vivo. Esto
también es lo que la heurística de rebalance del
LaneController necesita para funcionar correctamente (la
migración impulsada por drain dispara solo cuando la queue
de un lane llega a cero — bajo el contador buggy nunca lo
hace).

## Qué

Los cuatro fixes viven enteramente en `streaming.py`. Sin
cambios al renderer de la TUI ni al orchestrator batched.

### Fix 1 — Plomear `pool_stats.set_queue_depth` desde streaming

El orchestrator actualiza
`pool_stats.set_queue_depth(...)` con el conteo total
pendiente en vivo:
`main_bucket.qsize() + heavy_queue.qsize() + light_queue.qsize()`
(modo single-lane: solo `main_bucket.qsize()`).

Los updates ocurren después de cada `bucket.put` del producer
y cada `bucket.get` / `lane_queue.get` del consumer. El
snapshot de pool_stats es read-mostly así que la contención
de lock es mínima.

Resultado: `target = count + pending`, la barra muestra
progreso real a través del slice in-flight.

### Fix 2 + 3 — chunk_state sintético en vivo durante el run

Cuando los threads spawnean, el orchestrator transiciona el
`ChunkState` sintético a `status="UPLOAD"` con
`upload_started_monotonic=start`. PREP y UPLOAD corren
simultáneamente en streaming; "UPLOAD" es la fase dominante
para el modelo mental del operador (el único con un readout
de timer/throughput significativo).

Después de cada outcome S5 (en `_upload_loop` y
`_lane_upload_loop`), el orchestrator llama a un nuevo
helper interno:

```python
def _publish_chunk_state(self, *, batch_id: str, tally: _StreamingTally,
                          tally_lock: threading.Lock) -> None:
    with tally_lock:
        snap = (tally.s5_done, tally.s5_failed, tally.s5_skipped,
                tally.s1_filtered, tally.cross_batch_skipped)
    s5d, s5f, s5sk, fil, csk = snap
    docs = s5d + s5f + s5sk
    with self._state_lock:
        prev = self._chunk_state
        self._chunk_state = ChunkState(
            chunk_idx=0,
            batch_id=batch_id,
            status="UPLOAD",
            s5_done=s5d,
            s5_failed=s5f,
            doc_count=docs + fil + csk,
            prep_done=docs,
            prep_skipped=csk,
            prep_filtered=fil,
            upload_skipped=s5sk,
            upload_started_monotonic=(
                prev.upload_started_monotonic if prev else None
            ),
            prep_started_monotonic=(
                prev.prep_started_monotonic if prev else None
            ),
        )
```

Resultado:
* El tab CHUNKS muestra s5_done/s5_failed/doc_count en
  vivo.
* `_current_chunk_progress` ve `status="UPLOAD"` y computa
  `elapsed_s = now - upload_started_monotonic`, así que el
  timer tickea.
* `avg_mbps = (bytes_uploaded / 1MB) / elapsed_s` — no-cero
  una vez que el recorder acumula bytes de red.

### Fix 4 — Reporte de profundidad de lane basado en qsize real

Reemplazar los contadores monotónicos del dispatcher con
`lane_queue.qsize()`:

```python
# dispatcher, después del put:
self._lane_controller.set_queue_depth("heavy", heavy_queue.qsize())
```

Y el consumer reporta también:

```python
# _lane_upload_loop, después del get:
self._lane_controller.set_queue_depth(lane, lane_queue.qsize())
```

Resultado:
* El campo "queue" de LANES muestra el conteo in-flight en
  vivo per-lane.
* Nunca excede `bucket_size` (el maxsize de cada cola de
  lane).
* La heurística de rebalance del LaneController impulsada
  por drain realmente dispara cuando un lane llega a cero —
  pre-067 nunca lo hacía.

## Fuera de alcance

- Progreso-total verdadero (`count / total_triggers`) en
  modo streaming — requiere saber el total adelante de
  tiempo. El fix de arriba da
  `count / (count + currently-pending)`, que es una
  aproximación útil pero no "total". La spec 068 (TBD)
  puede plomear `--total` al chunk_state si hace falta.
- Visibilidad de in-flight per-stage (contadores separados
  para S1/S2/S3/S4). Fuera de alcance acá — una spec
  futura de visibilidad.

## Criterios de aceptación

- La barra de progreso del tab UPLOAD muestra
  `count / (count + pending)` durante un run streaming (no
  `count / count`), donde `pending` es el conteo in-flight
  en vivo visible al orchestrator.
- El timer por-chunk en el tab UPLOAD tickea desde el
  momento que los uploads arrancan, no después de
  completion del run.
- `current_chunk_avg_mbps` es no-cero una vez que el
  bandwidth se graba.
- El tab CHUNKS muestra `s5_done`, `s5_failed`,
  `doc_count`, `prep_done` en vivo durante el run.
- El `queue` de LANES en los tabs BUCKET y UPLOAD muestra
  el qsize en vivo de cada cola de lane. Nunca excede
  `bucket_size`. Decrementa a medida que los consumers
  drenan.
- El `_heavy_first_empty_at` / `_light_first_empty_at` del
  LaneController realmente se stampean durante un run con
  tráfico heavy y light (prueba que la heurística de drain
  es alcanzable).
- Todos los tests existentes pasan. Tests nuevos:
  * `_pool_stats.set_queue_depth` es llamado durante
    streaming.
  * `chunk_state.status == "UPLOAD"` a mitad de run (vía
    un test de polling).
  * `lane_controller.set_queue_depth("heavy", N)` recibe
    el valor de qsize real, no un conteo acumulado.
- mypy + ruff limpios.
- CHANGELOG `[0.69.0]`; pyproject 0.68.0 → 0.69.0.

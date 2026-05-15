# 065 — Lanes heavy/light en modo streaming

## Por qué

063 entrega modo streaming con S5 single-lane — cada doc
preparado va al mismo pool de consumer. 036 ya provee
**lanes heavy/light** (POST-MVP §1) para modo batched:
separar docs por `file_size_bytes >= heavy_threshold_bytes`
así un único PDF de 50 MB no puede starvear el bandwidth
que un grupo de JPEGs de 1 MB compartiría. En modo streaming
la misma starvation es *peor* — el bucket carece de la
noción de "este chunk", así que una secuencia de docs heavy
bloquea a los más livianos detrás de ellos en una cola FIFO.

El split es per-item: cada doc preparado lleva un
`staged_file.size_bytes` conocido (agregado en 036). La
decisión de lane debe ocurrir en tiempo de *consumo*,
después de que el producer ponga el item en el bucket —
porque el bucket mismo es FIFO.

## Qué

### 1. Decisión de lane en tiempo de consumo

El pool consumer único del orchestrator de streaming se
reemplaza por **dos pools** (heavy + light), cada uno
respaldado por un `queue.Queue` per-lane. Un nuevo thread
**dispatcher** liviano tira del bucket principal y rutea
cada item:

```
producers PREP ──▶ bucket principal ──▶ dispatcher
                                          │
                       size ≥ threshold?
                       ┌──────────┴──────────┐
                       ▼                     ▼
                cola lane heavy       cola lane light
                       │                     │
                consumer(s) heavy     consumer(s) light
```

El budget total de consumer queda en `_pool_ceiling()`; el
`LaneController` de 036 es dueño del split heavy/light
(ratio inicial, rebalance impulsado por drain). El
single-lane se preserva cuando
`heavy_light_lanes.enabled = false` (default).

### 2. Reusar infraestructura existente

* `LaneController` — ya existe (036), única fuente de
  verdad para los semáforos per-lane + daemon de
  rebalance.
* Clasificación per-item estilo `LaneSplitter` — pero la
  función entrega en 036 como un splitter *batch*.
  Agregamos un helper per-item
  `classify_lane(item, heavy_threshold_bytes)` que
  devuelve `"heavy"` | `"light"`.
* `_upload_one(item, batch_id, recorder, lane)` ya acepta
  un lane — usado sin cambios.

### 3. Wiring nuevo del orchestrator

Constructor de `StreamingOrchestrator`:

* Lee `heavy_light_lanes` de config. Cuando `enabled`,
  construye un `LaneController` exactamente como lo hace
  `StagedPipeline`.
* Spawnea un thread dispatcher + threads consumer
  heavy_count + light_count. La lógica del producer queda
  sin cambios.

La cuenta de consumer per-lane se deriva de
`_lane_controller.snapshot().heavy_budget` /
`light_budget` al arrancar; el daemon de rebalance ajusta
los semáforos. Los dos pools comparten el mismo tamaño
`_pool_ceiling()` así cuando AIMD escala hacia arriba, los
dos lanes pueden crecer.

### 4. Capa de wiring

`cli/app.py` remueve el WARN que 063 agregó. Cuando
`mode=="streaming" AND heavy_light_lanes.enabled=true`, el
orchestrator de streaming simplemente funciona.

### 5. TUI

El tab BUCKET (064) gana un sub-bloque "LANES" opcional
cuando un `LaneController` está presente — muestra
budget / busy / idle per-lane y el contador de rebalance
corriendo, reusando la forma de data `LaneSnapshot`
existente.

## Fuera de alcance

- Reordenar items adentro del bucket para intercalar
  heavy/light. El split-en-consumo del dispatcher es
  suficiente.
- Heurísticas de rebalance cross-lane más allá de las que
  036 ya entrega.

## Criterios de aceptación

- `processing.mode=="streaming"` con
  `heavy_light_lanes.enabled=true` corre limpio — los
  items heavy aterrizan en el lane heavy, los items light
  en el lane light.
- El WARN de arranque agregado en 063 (`heavy/light
  diferido a spec 065`) se remueve.
- El dispatcher sale limpio en `_POISON` del bucket
  principal.
- El tab BUCKET muestra el bloque per-lane cuando el modo
  dual está activo.
- Todos los tests existentes pasan. Nuevos tests cubren
  clasificación de lane + `fan-out` del dispatcher +
  shutdown limpio.
- CHANGELOG `[0.67.0]`; pyproject 0.66.0 → 0.67.0.

## Notas

- El dispatcher es un único thread — no puede pasar a ser
  el cuello de botella para ninguna carga realista (una
  comparación + `queue.put` por item).
- Mantenemos el tamaño del **bucket principal** =
  `bucket_size` configurado. Las colas per-lane usan
  `maxsize=bucket_size` también — así que el total
  in-flight es ~`3 × bucket_size` worst-case. La palanca
  del operador sigue siendo `bucket_size`.

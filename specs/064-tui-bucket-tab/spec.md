# 064 — Tab BUCKET de la TUI para modo streaming

## Por qué

063 entrega el orchestrator de streaming, pero la TUI
existente fue construida alrededor del modelo batched. En
modo streaming el tab CHUNKS muestra una única fila
sintética "STREAMING (1 chunk para todo el run)" — inútil
para observabilidad en vivo de un run de 5000 docs.

El operador necesita ver, de un vistazo, qué está haciendo
el *bucket*:

* nivel actual del bucket vs cap (indicador de
  `back-pressure`)
* nivel pico del bucket desde el arranque del run
* throughput de PREP (docs/s entrando al bucket)
* throughput de S5 (docs/s saliendo del bucket)
* conteos de workers en vivo (PREP busy/idle, S5
  busy/idle)
* totales por status (S5_DONE, S5_FAILED, S1_FILTERED,
  S1_SKIPPED)

## Qué

### 1. Nuevo tab BUCKET

Un nuevo tab adentro del widget `TabbedContent` existente
que pasa a ser **visible solo cuando** el orchestrator es
el de streaming (detectado vía un nuevo campo
`mode: "batched" | "streaming"` en el `TUIDataProvider`).
En modo batched el tab BUCKET está oculto y el tab CHUNKS
es la view per-chunk del operador; en modo streaming el
tab CHUNKS está oculto y el tab BUCKET toma el control.

### 2. Data plomeada a través de `TUIDataProvider`

* `bucket_level: int` — `qsize()` actual del bucket, o 0
* `bucket_cap: int` — `bucket_size` configurado
* `bucket_peak: int` — qsize pico desde el arranque del run
* `prep_throughput: float` — docs/s promediado sobre los
  últimos 5s
* `upload_throughput: float` — misma métrica para S5
* `prep_busy: int` / `prep_idle: int` — conteos de estado
  de threads producer (best-effort, snapshot en refresh)
* `upload_busy: int` / `upload_idle: int` — del
  `WorkerPoolStats` existente
* `s5_done`, `s5_failed`, `s1_filtered`, `s1_skipped` —
  tally acumulado leído del `chunks_snapshot()` del
  orchestrator (una sola fila sintética en modo streaming)

### 3. El `StreamingOrchestrator` expone la data

* `bucket_level()` — lee `_bucket.qsize()` (el qsize de
  queue.Queue es aproximado pero suficientemente bueno
  para un refresh de 1 segundo)
* `peak_qsize` — ya existe (063)
* `prep_pool_stats()` — snapshot con forma de
  `WorkerPoolStats` de los threads producer; para 064
  usamos un *par de contadores atómicos* (`prep_in_flight`)
  en el orchestrator (incrementado antes de
  `streaming_prep_one`, decrementado después).
* `chunks_snapshot()` — ya existe; leemos su única fila
  para los conteos acumulados.

### 4. Detección de modo streaming

La capa de binding de TUI en `cli/app.py` pasa
`mode=config.processing.mode` al `TUIDataProvider`. El
data provider expone una propiedad `mode` que los tabs de
la TUI quereyan en el primer render para decidir
visibilidad.

Los tabs UPLOAD, PREP, DETAIL existentes siguen
funcionando — ya leen el único recorder global.

## Fuera de alcance

- Un tab "live" unificado que subsuma BUCKET + CHUNKS —
  las dos formas coexisten en esta spec. Un cambio
  futuro las puede unificar.
- Filtering del DETAIL streaming-aware por `S5_DONE` etc.
  — DETAIL ya muestra cada fila de `migration_log`, que es
  correcto.
- Split heavy/light en el tab BUCKET — diferido a 065 (el
  splitter no existe en streaming todavía).

## Criterios de aceptación

- En modo batched (default), la TUI es byte-idéntica a la
  de 063 — tab CHUNKS presente, tab BUCKET ausente.
- En modo streaming, el tab BUCKET está presente con
  lecturas en vivo: nivel vs cap, pico, throughput
  PREP+UPLOAD, conteos de workers,
  s5_done/s5_failed/s1_filtered/s1_skipped acumulados.
- Un run streaming de 100 triggers con `bucket_size=10`
  muestra el nivel variando entre 0 y 10 a lo largo del
  run.
- El snapshot `StreamingOrchestrator.prep_pool_stats()`
  expone `in_flight`, `total_workers`.
- Todos los tests existentes siguen pasando; tests
  unitarios nuevos de TUI para el modelo
  `_BucketTabBindings` del tab BUCKET + plomería de modo
  del DataProvider.
- mypy + ruff limpios. CHANGELOG `[0.66.0]`; pyproject
  0.65.0 → 0.66.0.

## Notas sobre estrategia de tests

- `tests/unit/orchestrators/test_streaming.py` gana un
  test `test_prep_pool_stats_tracks_in_flight`.
- `tests/unit/tui/test_data_provider.py` (o equivalente)
  recibe `test_mode_property_is_streaming_when_configured`.
- El tab Textual mismo no necesita un test de render
  completo; bindear los campos es suficiente.

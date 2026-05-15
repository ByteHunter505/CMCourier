# 063 — Orchestrator de streaming (core, single-lane)

## Por qué

El pipeline actual corre en **modo batched**: los triggers se
chunkean en grupos de tamaño `batch_size`, y un
`MultiBatchOrchestrator` corre N=2 chunks en vuelo — el chunk
N sube mientras el chunk N+1 prepara. Eso funciona, pero para
la migración de producción de 20M docs son visibles dos
costos estructurales:

1. **Pico de memoria** = `batch_size × batches_in_flight`.
   Hoy 100 × 2 = ~200 docs en vuelo; con batch_size=1000
   eran ~2000.
2. **El valle entre chunks.** Cuando el S5 del chunk N
   termina más rápido que el PREP del chunk N+1, S5 espera
   idle. Cuando el PREP termina más rápido que S5, PREP
   bloquea en el slot in-flight.

El operador pidió la alternativa canónica
producer-consumer: **un `bucket` (buffer acotado) de items
con PREP completado, drenado por S5 continuamente**. El PREP
rellena mientras el bucket drena. S5 nunca espera a que el
PREP de un chunk entero complete — arranca apenas el bucket
tiene su primer item. El pico de memoria colapsa a
`bucket_size` (independiente del conteo total de triggers).

## Qué

### 1. Dos modos de pipeline lado a lado

```yaml
processing:
  mode: "batched"  | "streaming"     # default: "batched" (no disruptivo)
```

`"batched"` mantiene cada byte del comportamiento de
`MultiBatchOrchestrator` intacto — incluyendo
`batches_in_flight`, el swap de recorder/AIMD per-chunk, y
el tab CHUNKS existente. `"streaming"` activa un orchestrator
nuevo.

### 2. El orchestrator de streaming

Un nuevo `StreamingOrchestrator` vive al lado del
`MultiBatchOrchestrator`, construido por la capa de wiring
cuando `processing.mode == "streaming"`. Expone la misma
forma `.run(...)` y devuelve un `MultiBatchRunReport` para
compatibilidad con la CLI — el campo `chunks` del reporte
lleva un único chunk sintético (el run completo).

Modelo interno:

- **Bucket**: `queue.Queue[_StageItem](maxsize=bucket_size)`.
- **Producers**: `prep_workers` threads daemon. Cada
  producer tira un trigger de un iterador thread-safe sobre
  la fuente de triggers, corre S1→S4 sobre él vía nuevo
  `StagedPipeline.streaming_prep_one(trigger, batch_id,
  recorder)`, y empuja cualquier item sobreviviente al
  bucket. Las fallas de dominio (`RVABREPDeletedError`,
  `IDRViNotMappedError`, etc.) se persisten al
  `migration_log` por los helpers per-stage existentes — sin
  casos especiales acá.
- **Consumers**: `cmis.workers` threads daemon dimensionados
  al techo de AIMD (`_pool_ceiling()`, spec 057). Cada
  consumer hace `bucket.get()`, corre S5 vía el `_upload_one`
  existente, llama `bucket.task_done()`.
- **Coordinación de shutdown**: cuando el iterador de
  triggers levanta `StopIteration`, el producer que la
  observó empuja `N` `poison pill`s (uno por consumer) al
  bucket. Los consumers `break` en `poison pill`.
- **Un solo batch_id para el run**.
  `tracking_store.start_batch(0)` en el tope,
  `complete_batch(...)` al final. Cada fila persistida en
  `migration_log` lleva este único id. (El
  `total_records=0` es aceptado por SQLite — es
  informativo, no una constraint.)
- **Un solo `MetricsRecorder` global** para el run. AIMD
  lee `current_stage_p95_with_count("S5")` de ese único
  recorder — sin swap per-chunk. El guard `min_samples`
  (spec 061) maneja el outlier de cold-start.
- **La `back-pressure` es automática**: cuando el bucket
  está lleno, `bucket.put()` bloquea al producer. Cuando el
  bucket está vacío, `bucket.get()` bloquea al consumer.
  Los workers idle consumen cero CPU.

### 3. Config

```python
class StreamingConfig(BaseModel):
    bucket_size: int = Field(default=100, ge=1)

class ProcessingConfig(BaseModel):
    mode: Literal["batched", "streaming"] = "batched"
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    # ...campos existentes se mantienen...
```

`processing.batches_in_flight` se ignora cuando
`mode=="streaming"` (documentado en el docstring del campo).

### 4. Wiring

`cli/app.py` lee `config.processing.mode`. La factory de
orchestrator devuelve o `MultiBatchOrchestrator(...)` o
`StreamingOrchestrator(...)`. Las dos honran la misma firma
`.run(...)` así el resto de `app.py` queda sin cambios.

### 5. Semánticas de resume

En modo streaming, **resume = un run nuevo**. La idempotencia
cross-batch (spec 062 — filas `S1_SKIPPED`) provee
trazabilidad para los docs ya subidos en cualquier run
anterior. `from_stage=N` y `batch_id` nombrado por el
operador son **rechazados** con un ValueError claro cuando
`mode=="streaming"`. El camino batched mantiene las
semánticas completas de resume.

## Fuera de alcance

- **Tab BUCKET de la TUI** (spec 064). El orchestrator nuevo
  todavía actualiza el `MetricsRecorder` base (stages, slow
  ops, bandwidth), así que los tabs PREP/UPLOAD/CHUNKS
  existentes degradan gracefully: PREP y UPLOAD muestran
  data real de stage; el tab CHUNKS mostrará una única fila
  sintética "STREAMING (1 chunk para todo el run)". 064 lo
  reemplaza con un tab BUCKET real.
- **Lanes heavy/light en streaming** (spec 065). Streaming
  arranca single-lane. El wiring construye el
  `StreamingOrchestrator` **sin** el `LaneController`
  aunque `heavy_light_lanes.enabled: true` — con un log
  WARN claro de arranque apuntando a la spec 065.
- **Snapshot `chunks_state` de la TUI**.
  `StreamingOrchestrator.chunks_snapshot()` devuelve una
  lista de una sola fila describiendo el run de streaming
  como un chunk conceptual. Suficiente para 063; el tab
  dedicado llega en 064.

## Criterios de aceptación

- `processing.mode` default a `"batched"` y rechaza valores
  desconocidos (Pydantic Literal).
  `processing.streaming.bucket_size` default a 100, rechaza
  `< 1`.
- Un `StreamingOrchestrator.run(...)` contra un set de
  fixture chico sube cada doc exitosamente — test
  end-to-end vía el `pipeline_harness` existente.
- El bucket topa la memoria: un test con `bucket_size=5` y
  50 triggers assertea que el `qsize()` del bucket nunca
  excede 5 a mitad de run (sondeado vía un hook).
- El shutdown es limpio: cada thread consumer joinea, sin
  zombies.
- `from_stage > 1` o `batch_id` non-None con
  `mode="streaming"` levanta `ValueError`.
- La idempotencia cross-batch (spec 062 / la spec) funciona
  en streaming exactamente como en batched — un re-run de
  los mismos triggers produce filas `S1_SKIPPED`.
- La capa de wiring elige el orchestrator correcto y
  surface un WARN claro cuando
  `heavy_light_lanes.enabled: true` se combina con
  `mode="streaming"` (diferido a la spec 065).
- Suite completa unit + integration verde; mypy + ruff
  limpios.
- `CHANGELOG.md [0.65.0]`; `pyproject.toml` 0.64.0 → 0.65.0.

## Notas sobre estrategia de tests

El `pipeline_harness` (`tests/integration/pipeline/conftest.py`)
se reusa: una nueva factory
`build_streaming_pipeline(triggers_csv, **kwargs)` wirea el
`StreamingOrchestrator`. El stubbing de CMIS basado en
`respx` existente funciona sin cambios — el orchestrator
nuevo pasa por el mismo `CmisUploader`. Dos tests clave:

- `test_streaming_run_uploads_all_docs` — happy path,
  fixture de 6 docs, cada doc aterriza `S5_DONE`.
- `test_streaming_bucket_caps_memory` — `bucket_size=5`,
  instrumentar la cola para grabar el `qsize()` pico,
  assertear ≤ 5.
- `test_streaming_rejects_resume_args` — `from_stage=3` o
  `batch_id="x"` con `mode="streaming"` levanta.
- `test_streaming_cross_batch_idempotency` — el segundo
  run produce filas `S1_SKIPPED` igual que el camino
  batched (062).

El orchestrator mismo recibe tests unitarios para la
thread-safety del iterador + shutdown de `poison pill` vía
un harness estilo `_FakePipeline`, espejando el patrón
usado en `tests/unit/orchestrators/test_multi_batch.py`.

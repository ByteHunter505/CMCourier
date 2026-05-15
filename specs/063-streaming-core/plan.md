# 063 — Plan

Dos fases.

## Fase 1 — Orchestrator de streaming + config + wiring + tests

### Archivos

- `src/cmcourier/config/schema.py`
  - Nuevo `StreamingConfig(BaseModel)` con
    `bucket_size: int = 100, ge=1`.
  - `ProcessingConfig.mode: Literal["batched", "streaming"] = "batched"`.
  - `ProcessingConfig.streaming: StreamingConfig`.
  - Nota en docstring de que `batches_in_flight` se ignora
    en streaming.

- `src/cmcourier/orchestrators/streaming.py` (archivo nuevo)
  - `class StreamingOrchestrator`. El constructor espeja
    `MultiBatchOrchestrator` (pipeline, config, log_dir)
    más un `bucket_size` explícito derivado de config.
  - `.run(*, source_descriptor, batch_size,
    batches_in_flight, ...)` — misma firma para
    compatibilidad CLI; rechaza `from_stage > 1` y
    `resume_batch_id` non-None con ValueError; ignora
    `batches_in_flight` y `batch_size`.
  - Internos:
    - `start_batch(0)` → un solo batch_id para el run.
    - `MetricsRecorder.start_batch(...)` una vez.
    - `bucket = queue.Queue[_StageItem | None](maxsize=bucket_size)`.
    - `trigger_iter` = iter(strategy.acquire(...)) topado
      por `total` si está seteado; protegido por un Lock.
    - Spawn de `prep_workers` threads producer + `cmis.workers`
      threads consumer (la cuenta de consumers == cuenta
      inicial de workers; AIMD ajusta el semáforo adentro
      de _upload_one, igual que batched).
    - Loop del producer: tirar trigger; llamar
      `pipeline.streaming_prep_one(trigger, batch_id,
      recorder)`; en éxito empujar al bucket. En
      StopIteration: empujar N `poison pill`s, salir.
    - Loop del consumer: `bucket.get()`; si `None`,
      `task_done()` después break; sino llamar
      `pipeline._upload_one(item, batch_id, recorder)`;
      contar outcome; `task_done()`.
    - Joinear todos los threads.
    - Cerrar batch, devolver un `MultiBatchRunReport` con
      un único `RunReport` sintético.
  - `chunks_snapshot()`: devuelve una lista de una sola
    fila describiendo el run (sintético, para el fallback
    del tab CHUNKS existente de la TUI).
  - `active_recorder()`, `upload_recorder()`: las dos
    devuelven el único recorder global.

- `src/cmcourier/orchestrators/staged.py`
  - Nuevo método público
    `streaming_prep_one(trigger, batch_id, recorder) -> _StageItem | None`.
    Corre S0/S1 sobre `[trigger]` (lista de un solo
    elemento), después para cada survivor corre `_s2_one`,
    `_s3_one`, `_s4_one` secuencialmente. Devuelve el
    item sobreviviente o `None` (filtered / failed /
    skipped cross-batch — todos ya persistidos por los
    helpers internos).

- `src/cmcourier/cli/app.py`
  - Factory `run_orchestrator_with_tui`: elegir
    `StreamingOrchestrator` cuando
    `config.processing.mode == "streaming"`.
  - Log WARN cuando `mode == "streaming"` y
    `heavy_light_lanes.enabled is True` (diferido a la
    spec 065).
  - Log WARN cuando `mode == "streaming"` y
    `--from-stage > 1` o se pasa un `--batch-id` nombrado
    por el operador — *y* el orchestrator levanta
    ValueError downstream.

### Tests

- `tests/unit/config/test_schema.py`
  - `processing.mode` default `"batched"`, rechaza
    `"invalid"`.
  - `processing.streaming.bucket_size` default 100,
    rechaza 0.

- `tests/integration/pipeline/test_streaming_pipeline.py`
  (nuevo)
  - Reusar `pipeline_harness`. Agregar un helper
    `build_streaming_pipeline` que construye el
    `StreamingOrchestrator` contra el pipeline compartido
    del harness.
  - `test_streaming_uploads_all_docs` — happy path de 2
    docs, cada doc `S5_DONE`.
  - `test_streaming_bucket_caps_memory` — `bucket_size=2`
    contra 6 docs (el set completo del fixture rvabrep);
    parchear `queue.Queue.put` o samplear `qsize()` para
    assertear pico ≤ 2.
  - `test_streaming_rejects_resume_args` — `from_stage=3`
    o `resume_batch_id="x"` con streaming levanta
    ValueError.
  - `test_streaming_cross_batch_idempotency` — el primer
    run sube, el segundo run produce filas `S1_SKIPPED`
    (camino 062).

- `tests/unit/orchestrators/test_streaming.py` (nuevo)
  - `test_iterator_is_thread_safe` — dos producers falsos
    consumen del iterador compartido; ningún trigger se
    procesa dos veces (contador).
  - `test_poison_pill_drains_consumers` — un producer con
    0 triggers; N consumers; todos joinean limpio.
  - `test_streaming_orchestrator_returns_runreport` —
    chequeo de forma.

### Verify

`pytest tests/unit tests/integration -q` verde. ruff + mypy
limpios.

### Commit

```
feat(orchestrator): streaming mode with bucket-based producer-consumer (063 Phase 1)
```

## Fase 2 — CHANGELOG 0.65.0 + version + README + FF

Release dance estándar + prueba de `cmcourier --version` +
FF a main.

Commit:
`docs(063): CHANGELOG 0.65.0 + version bump + streaming docs (063 Phase 2)`.

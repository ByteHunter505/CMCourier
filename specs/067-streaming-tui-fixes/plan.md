# 067 — Plan

Spec de fix de una sola fase. Todos los cambios en
`streaming.py` (+ tests).

## Fase 1 — fixes + tests

### `src/cmcourier/orchestrators/streaming.py`

1. **Helper de conteo pendiente**: nuevo
   `_publish_pending_count(main_bucket, heavy_queue,
   light_queue)` lee `qsize()` de cada cola, suma, llama
   `self._pipeline.pool_stats.set_queue_depth(total)`.
   Llamado después de cada `put` / `get`.

2. **Transición de status + chunk_state en vivo**:
   cuando los threads spawnean, transicionar el chunk
   sintético a `status="UPLOAD"` con
   `upload_started_monotonic=start` y
   `prep_started_monotonic=start`. Nuevo helper
   `_publish_chunk_state(batch_id, tally, tally_lock)`
   llamado después de cada outcome S5 adentro de
   `_upload_loop` y `_lane_upload_loop`. Lee el tally bajo
   lock, escribe el ChunkState sintetizado bajo
   `_state_lock`.

3. **Dispatcher + consumer reportan qsize real**:
   reemplazar los contadores privados
   `heavy_depth`/`light_depth` con
   `heavy_queue.qsize()` / `light_queue.qsize()`. Tanto el
   dispatcher (después del put) como el consumer (después
   del get) reportan.

### Tests (`tests/unit/orchestrators/test_streaming.py`)

- `test_streaming_publishes_queue_depth` — después de que
  unos pocos items pasen, `pipeline.pool_stats.queue_depth`
  es no-cero (contador en vivo).
- `test_streaming_status_transitions_to_upload_at_start` —
  pollear `chunks_snapshot()[0].status` poco después de que
  arranque `run`; esperar `"UPLOAD"`.
- `test_streaming_publishes_live_s5_counters` — durante un
  run con N triggers, `chunks_snapshot()[0].s5_done` crece
  de 0 hacia N.
- `test_dispatcher_reports_real_qsize` — en modo dual-lane,
  `lane_controller.snapshot().heavy.queue_depth` matchea
  `heavy_queue.qsize()` y nunca excede `bucket_size`.

### Verify

`pytest tests/unit tests/integration -q`. ruff + mypy
limpios.

### Commit

```
fix(streaming): live TUI bindings — bar/timer/CHUNKS/lane-queue (067 Phase 1)
```

## Fase 2 — release

- CHANGELOG `[0.69.0]`
- pyproject 0.68.0 → 0.69.0
- `.venv/bin/pip install -e . --no-deps` + chequeo de
  versión
- Tick en fila de features de README (bullet más chico —
  es un release de bugfix)
- FF a main

Commit:
`docs(067): CHANGELOG 0.69.0 + version bump (067 Phase 2)`.

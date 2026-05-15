# 065 — Plan

Dos fases.

## Fase 1 — wiring + tests

### Archivos

- `src/cmcourier/orchestrators/streaming.py`
  - Agregar campo `LaneController` (opcional, solo cuando
    `heavy_light_lanes.enabled` es true).
  - Agregar `queue.Queue`s per-lane en `run()`.
  - Reemplazar el pool consumer único con: 1 dispatcher +
    N consumers heavy + M consumers light.
  - Loop del dispatcher: tirar del bucket principal; si
    es `_POISON`, empujar `_POISON` a las dos colas de
    lane × cuenta de consumer y salir; sino leer
    `staged_file.size_bytes`, empujar a la cola heavy o
    light basado en el threshold.
  - Loop del consumer per-lane: `bucket.get()` de su cola
    de lane; en `_POISON`, salir; sino
    `streaming_upload_one(item, ..., lane=...)` (extender
    la firma) y contar.
  - `streaming_snapshot()` ya existe — gana un campo
    `lane_snapshot: LaneSnapshot | None` en
    `StreamingSnapshot`.

- `src/cmcourier/orchestrators/staged.py`
  - `streaming_upload_one(item, batch_id, recorder, lane=None)`
    — ya llama a
    `_upload_one(item, batch_id, recorder, lane)`, solo
    pasar el param a través (lane default a None).

- `src/cmcourier/cli/app.py`
  - Descartar el WARN de `streaming + heavy_light_lanes`
    (065 lo entrega).

- `src/cmcourier/tui/bucket_tab.py`
  - Imprimir un bloque LANES cuando
    `snap.lane_snapshot is not None`.

### Tests

- `tests/unit/orchestrators/test_streaming.py`
  - `test_dispatcher_routes_by_size` — alimentar items
    con `size_bytes` mixto; assertear que los items heavy
    van al lane heavy, los light al light. El
    `_FakePipeline` ya soporta
    `streaming_upload_one(item, batch_id, recorder, lane=None)`.
  - `test_clean_shutdown_with_lanes` — fuente vacía +
    modo dual drena todos los threads.
  - `test_streaming_snapshot_carries_lane_snapshot_when_enabled`.

- `tests/unit/tui/test_bucket_tab.py`
  - `test_renders_lane_block_when_lane_snapshot_present`.

### Verify

`pytest tests/unit tests/integration -q`. ruff + mypy
limpios.

### Commit

```
feat(orchestrator): heavy/light lanes in streaming mode (065 Phase 1)
```

## Fase 2 — release

- CHANGELOG `[0.67.0]`.
- pyproject 0.66.0 → 0.67.0.
- `.venv/bin/pip install -e . --no-deps`;
  `cmcourier --version`.
- Tick en fila de features de README.
- FF a main.

Commit:
`docs(065): CHANGELOG 0.67.0 + version bump (065 Phase 2)`.

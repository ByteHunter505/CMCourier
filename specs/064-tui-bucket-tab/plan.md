# 064 — Plan

Dos fases.

## Fase 1 — hooks del orchestrator + data provider + tab de TUI + tests

### Archivos

- `src/cmcourier/orchestrators/streaming.py`
  - Nuevo patrón `_prep_in_flight` AtomicInteger vía
    `threading.Lock` + contador; los producers `_inc()`
    antes de `streaming_prep_one`, `_dec()` en finally.
  - Nuevos métodos públicos:
    - `bucket_level() -> int` (lee `_bucket.qsize()` si el
      bucket existe sino 0)
    - `prep_in_flight() -> int`
    - `streaming_throughput() -> tuple[float, float]` —
      devuelve `(prep_docs_per_s, upload_docs_per_s)`
      sobre una ventana de 5s usando timestamps de
      ring-buffer mantenidos por los loops
      producer/consumer.

- `src/cmcourier/tui/data_provider.py`
  - Agregar arg de ctor
    `mode: Literal["batched", "streaming"] = "batched"`.
  - Agregar arg de ctor
    `bucket_provider: Callable[[], dict] | None = None`
    (devuelve un dict con claves level/cap/peak/throughput).
  - Nuevo método `bucket_snapshot()`.

- `src/cmcourier/tui/app.py` (o donde viva `CMCourierTUI`)
  - Agregar condicionalmente un `BucketTab` al
    `TabbedContent`.
  - Wirear refresh de `set_interval` para leer
    `bucket_snapshot()`.
  - Ocultar el tab CHUNKS en modo streaming (o swapear
    visibilidad).

- `src/cmcourier/cli/app.py`
  - Pasar `mode=config.processing.mode` y una lambda
    bucket_provider apuntando a los métodos `bucket_*` del
    orchestrator al `TUIDataProvider`.

### Tests

- `tests/unit/orchestrators/test_streaming.py`
  - `test_prep_in_flight_increments_during_prep` (usar un
    Barrier en el prep del fake para assertear contador >
    0 a mitad de vuelo).
  - `test_bucket_level_reflects_queue_state` (forzar el
    bucket lleno, assertear level == cap).
  - `test_streaming_throughput_window` (impulsar un burst
    conocido, assertear throughput positivo).

- `tests/unit/tui/test_data_provider.py` (nuevo o
  extendido)
  - `test_mode_default_batched`.
  - `test_mode_streaming_propagates`.
  - `test_bucket_snapshot_no_provider_returns_none`.

### Verify

`pytest tests/unit tests/integration -q`, ruff + mypy
limpios.

### Commit

```
feat(tui): BUCKET tab for streaming mode (064 Phase 1)
```

## Fase 2 — release

- CHANGELOG `[0.66.0]`.
- pyproject 0.65.0 → 0.66.0.
- `.venv/bin/pip install -e . --no-deps`;
  `cmcourier --version`.
- Tick en fila de features de README (changeset 065).
- FF a main.

Commit:
`docs(064): CHANGELOG 0.66.0 + version bump + bucket-tab docs (064 Phase 2)`.

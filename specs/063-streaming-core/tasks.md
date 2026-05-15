# 063 — Tasks

Branch: `feat/063-streaming-core`. Commit en dos fases.

## Fase 1 — implementación

- [ ] T1. `src/cmcourier/config/schema.py`
  - Agregar `StreamingConfig(BaseModel)` con
    `bucket_size: int = Field(default=100, ge=1)`.
  - Agregar `mode: Literal["batched", "streaming"] = "batched"`
    a `ProcessingConfig`.
  - Agregar
    `streaming: StreamingConfig = Field(default_factory=StreamingConfig)`
    a `ProcessingConfig`.
  - El docstring del campo `batches_in_flight` nota
    "ignorado en modo streaming".

- [ ] T2. `src/cmcourier/orchestrators/staged.py`
  - Nuevo método público
    `streaming_prep_one(trigger, batch_id, recorder)`:
    - Envuelve S0/S1 sobre `[trigger]` (preservando la
      persistencia de filter/skip).
    - Llama `_s2_one` → `_s3_one` → `_s4_one`
      secuencialmente para cada survivor.
    - Devuelve el único `_StageItem` sobreviviente o
      `None`.
  - Refactorizar el `_run_prep_stage` existente para
    compartir los helpers internos (sin cambio de
    comportamiento).

- [ ] T3. `src/cmcourier/orchestrators/streaming.py`
  (nuevo)
  - `class StreamingOrchestrator`. Misma firma `.run(...)`
    que `MultiBatchOrchestrator` para paridad de CLI.
  - Iterador thread-safe de triggers (`_TriggerIter` con
    `threading.Lock`).
  - `queue.Queue[_StageItem | None](maxsize=bucket_size)`.
  - Thread(s) producer `_prep_loop` — tirar trigger, prep,
    `put` (bloquea en lleno).
  - Thread(s) consumer `_upload_loop` — `get`, upload,
    `task_done`. Break en `None`.
  - `_shutdown_event` para abort cooperativo en Ctrl+C.
  - Devuelve un `MultiBatchRunReport` con un único
    `RunReport` sintético.
  - Rechazar `from_stage > 1` y `resume_batch_id` non-None
    con `ValueError`.

- [ ] T4. `src/cmcourier/cli/app.py`
  - Factory de orchestrator ramifica sobre
    `config.processing.mode`.
  - Log WARN cuando streaming + `heavy_light_lanes.enabled`
    (diferir a 065).
  - Misma sentencia de logger en args de resume en
    conflicto (el orchestrator también levanta — loguear
    primero para claridad del operador).

- [ ] T5. `src/cmcourier/orchestrators/__init__.py`
  - Re-exportar `StreamingOrchestrator`.

- [ ] T6. `tests/unit/config/test_schema.py`
  - `processing.mode` default = `"batched"`, rechaza
    `"invalid"`.
  - `processing.streaming.bucket_size` default = 100,
    rechaza 0 y -1.

- [ ] T7. `tests/unit/orchestrators/test_streaming.py`
  (nuevo)
  - `test_iterator_thread_safe` — dos producers, sin
    double-pull.
  - `test_poison_pill_drains_consumers` — fuente vacía,
    todos los consumers salen.
  - `test_rejects_from_stage_gt_one`.
  - `test_rejects_explicit_batch_id`.

- [ ] T8. `tests/integration/pipeline/test_streaming_pipeline.py`
  (nuevo)
  - `test_streaming_uploads_all_docs` — fixture de 6
    triggers, todos `S5_DONE`.
  - `test_streaming_bucket_caps_memory` — bucket_size=2,
    hook sobre `Queue.put`, assertear qsize pico ≤ 2.
  - `test_streaming_cross_batch_idempotency` — el segundo
    run rinde filas `S1_SKIPPED` (contrato 062 intacto).

- [ ] T9. Correr `pytest tests/unit tests/integration -q`.
  Requerido verde.
  - `ruff check .` + `mypy src` limpios.

- [ ] T10. Commit:
  - `feat(orchestrator): streaming mode with bucket-based producer-consumer (063 Phase 1)`

## Fase 2 — release dance

- [ ] T11. `CHANGELOG.md` — entrada `[0.65.0]`, secciones:
  - Added: modo streaming (`processing.mode`,
    `processing.streaming.bucket_size`).
  - Internal: `StreamingOrchestrator`,
    `streaming_prep_one`.
  - Notes: lanes heavy/light diferidos a 065; tab BUCKET
    de la TUI en 064.

- [ ] T12. `pyproject.toml` — versión 0.64.0 → 0.65.0.

- [ ] T13. `.venv/bin/pip install -e . --no-deps`.
  `cmcourier --version` → 0.65.0.

- [ ] T14. `README.md` — tick en fila de features para
  modo streaming.

- [ ] T15. Commit:
  - `docs(063): CHANGELOG 0.65.0 + version bump + streaming docs (063 Phase 2)`

- [ ] T16. FF a main
  (`git checkout main && git merge --ff-only feat/063-streaming-core`).
  Sin push.

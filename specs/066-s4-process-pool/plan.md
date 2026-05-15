# 066 — Plan

Dos fases.

## Fase 1 — módulo de pool + wiring del pipeline + tests

### Archivos

- `src/cmcourier/config/schema.py`
  - `ProcessingConfig.s4_use_processes: bool = True`
  - `ProcessingConfig.s4_max_processes: int | None = None`
    (con `Field(default=None, ge=1)`)

- `src/cmcourier/adapters/assembly/pool.py` (nuevo)
  - Global `_worker_assembler` a nivel módulo
  - `_pool_init(config: AssemblerConfig) -> None`
  - `_pool_assemble(document: RVABREPDocument) -> StagedFile`
  - `build_s4_process_pool(config: AssemblerConfig, max_workers: int | None) -> ProcessPoolExecutor`

- `src/cmcourier/orchestrators/staged.py`
  - `StagedPipeline.__init__` acepta
    `s4_process_pool: ProcessPoolExecutor | None = None`
  - `_s4_one`: cuando el pool está presente,
    `staged = self._s4_process_pool.submit(_pool_assemble, item.document).result()`
  - El `_s4_one` mantiene el wrapper StageTimer, así que la
    latencia todavía se graba en el recorder.

- `src/cmcourier/config/wiring.py`
  - Cuando `cfg.processing.s4_use_processes`: construir el
    pool vía `build_s4_process_pool(...)` y pasarlo al
    `StagedPipeline`.
  - El `shutdown(wait=True)` del pool necesita un hook de
    lifecycle — para la Fase 1, la capa de wiring lo
    registra vía `atexit` (lo más simple). Un follow-up lo
    puede mover a un método `close()` del pipeline.

### Tests

- `tests/unit/config/test_schema.py`
  - `processing.s4_use_processes` default a True
  - `processing.s4_max_processes` default a None, rechaza 0

- `tests/unit/adapters/assembly/test_pool.py` (nuevo)
  - `_pool_init` después `_pool_assemble` funciona
    end-to-end (corrido en el mismo proceso — solo
    verifica que los helpers son correctos)
  - `_pool_assemble` es importable + picklable

- `tests/integration/pipeline/test_streaming_pipeline.py`
  - `test_streaming_with_s4_process_pool` — fixture chico
    con el pool habilitado, assertea el mismo conteo
    `s5_done` que sin él

- `tests/unit/orchestrators/test_staged_pool_ceiling.py`
  (o archivo nuevo)
  - `_s4_one` despacha vía pool cuando el pool está
    provisto
  - `_s4_one` hace fallback a assembly directo cuando el
    pool es None

### Verify

`pytest tests/unit tests/integration -q`. ruff + mypy
limpios.

### Commit

```
feat(assembly): S4 in ProcessPoolExecutor for real CPU-bound parallelism (066 Phase 1)
```

## Fase 2 — release

- CHANGELOG `[0.68.0]`
- pyproject 0.67.0 → 0.68.0
- `.venv/bin/pip install -e . --no-deps` + chequeo de
  versión
- Tick en fila de features de README
- FF a main

Commit:
`docs(066): CHANGELOG 0.68.0 + version bump + s4-pool docs (066 Phase 2)`.

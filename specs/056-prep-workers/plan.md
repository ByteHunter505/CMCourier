# 056 — Plan

Dos fases (~1.5 h total).

## Fase 1 — Config de `prep_workers` + paralelizar S2/S3/S4 + tests (~70 min)

### Archivos

- `src/cmcourier/config/schema.py`
  - `ProcessingConfig` — agregar
    `prep_workers: int = Field(default=1, ge=1)`.

- `src/cmcourier/orchestrators/staged.py`
  - `__init__` — agregar `prep_workers: int = 1`; guardar
    `self._prep_workers = max(1, int(prep_workers))`.
  - Extraer el body per-item de cada stage en un helper que
    **atrapa sus propias excepciones de dominio** y devuelve
    `tuple[_StageItem | None, bool]` =
    `(survivor_o_None, falla_contada)`:
    - `_s2_one(item, batch_id, rec)` — lookup de mapping.
    - `_s3_one(item, batch_id, rec)` — cache try_get / metadata
      resolve / cache put.
    - `_s4_one(item, batch_id, rec)` — assemble.
  - Nuevo helper de dispatch compartido
    `_run_prep_stage(items, worker) -> tuple[list[_StageItem], int]`:
    - `self._prep_workers == 1` →
      `results = [worker(i) for i in items]` (serial —
      byte-idéntico al loop actual).
    - sino → `with ThreadPoolExecutor(max_workers=self._prep_workers,
      thread_name_prefix="cmcourier-prep") as pool:
      results = list(pool.map(worker, items))` (`pool.map`
      preserva el orden de input).
    - `survivors = [s for s, _ in results if s is not None]`;
      `failed = sum(1 for _, c in results if c)`.
  - `_stage_s2` / `_stage_s3` / `_stage_s4` — pasan a ser
    wrappers finos: construir el `worker` (un
    `functools.partial` o closure local bindeando `batch_id` +
    `rec`) y llamar a `_run_prep_stage`.
  - El camino S0/S1 (`_stage_s0_s1`) queda intacto.

- La capa de wiring que construye `StagedPipeline` — pasar
  `prep_workers=config.processing.prep_workers`. (Localizar
  vía `grep -rn "StagedPipeline(" src/cmcourier/` —
  probablemente `cli/app.py` o un módulo builder; actualizar
  cada call site de construcción.)

### Tests — `tests/` (el módulo de tests del staged-pipeline)

- `test_prep_workers_defaults_to_one` — `ProcessingConfig()` →
  `prep_workers == 1`; `prep_workers=0` levanta
  `ValidationError`.
- `test_prep_stage_serial_path_when_one_worker` —
  `prep_workers=1` sobre un batch multi-item conocido →
  survivors + `failed` exactamente como el loop serial
  pre-056.
- `test_prep_stage_parallel_preserves_order` —
  `prep_workers=4` sobre un batch multi-item → `survivors` en
  **orden de input**, todos presentes.
- `test_prep_stage_parallel_failure_counting` — un batch con un
  item que falla por dominio → descartado de survivors,
  `failed == 1`, bajo `prep_workers=1` y `prep_workers=4`.
- `test_prep_stage_parallel_resume_already_done` — un item que
  falla pero que ya está `S*_DONE` de un run anterior →
  descartado, **no** contado en `failed` (el edge case de
  resume que el `bool` en el retorno del helper preserva).
- Si existe un builder/fixture de `StagedPipeline` en la suite
  de tests, pasarle `prep_workers`.

### Verify

Suite completa unit + integration + ruff + mypy.

### Commit

```
feat(prep): configurable prep_workers — parallelize S2/S3/S4 on a fixed thread pool (056 Phase 1)
```

## Fase 2 — CHANGELOG 0.59.0 + bump de versión + docs + FF (~20 min)

### Archivos

- `CHANGELOG.md` `[0.59.0]` — Added (`processing.prep_workers`
  — un pool de threads de tamaño fijo para S2/S3/S4; el
  armado S4 era completamente serial; default `1` mantiene
  comportamiento actual; S0/S1 quedan seriales por diseño).
- `pyproject.toml` 0.58.0 → 0.59.0.
- Tick en fila de features de `README.md`.
- `docs/samples/config-reference.yaml` — documentar
  `processing.prep_workers` con el default y la nota
  "S0/S1 quedan seriales".

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.59.0
```

### Commit

```
docs(056): CHANGELOG 0.59.0 + version bump + prep_workers config docs (056 Phase 2)
```

### FF a main.

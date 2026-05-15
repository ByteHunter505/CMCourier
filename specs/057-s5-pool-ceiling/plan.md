# 057 — Plan

Dos fases (~1 h total). Un solo archivo de fuente, quirúrgico.

## Fase 1 — Dimensionar el pool de S5 al techo de AIMD + tests (~40 min)

### Archivos

- `src/cmcourier/orchestrators/staged.py`
  - Nuevo helper `_pool_ceiling(self) -> int`:
    ```python
    if self._auto_tune_cfg is not None and self._auto_tune_cfg.enabled:
        return max(self._workers, self._auto_tune_cfg.max_threads)
    return self._workers
    ```
  - `_stage_5_single` —
    `ThreadPoolExecutor(max_workers=self._pool_ceiling(), ...)`;
    `self._pool_stats.set_pool_size(self._pool_ceiling())`
    (era `self._workers`).
  - `_stage_5_dual` — tanto `heavy_pool` como `light_pool`
    `ThreadPoolExecutor(max_workers=self._pool_ceiling(), ...)`.
    El `LaneController` ya tiene los caps per-lane + resize de
    budget de AIMD — sin cambios ahí.
  - Sin otros call sites: `grep` confirma que
    `ThreadPoolExecutor` en `staged.py` aparece en
    `_run_prep_stage` (056 — prep, no relacionado),
    `_stage_5_single`, `_stage_5_dual`.

### Tests

- `tests/unit/orchestrators/` (o donde vivan los tests
  unitarios de `StagedPipeline`) — `test_pool_ceiling`:
  - AIMD habilitado, `max_threads=16`, `cmis.workers=4` → `16`.
  - AIMD deshabilitado → `cmis.workers`.
  - `cmis.workers=20`, `max_threads=8` → `20` (el guard de
    `max(...)`).
  Construir un `StagedPipeline` mínimo (fakes/stubs para
  colaboradores) o testear vía una construcción fina; si
  existe un fixture builder, reusarlo.

- `tests/integration/pipeline/test_s5_worker_pool.py` —
  `TestS5PoolCeiling057`:
  - `test_single_pool_sized_to_ceiling_when_auto_tune_enabled`
    — parchear
    `cmcourier.orchestrators.staged.ThreadPoolExecutor` con un
    wrapper grabador que captura `max_workers` después delega
    a la clase real; correr un pipeline CLI real (el harness
    existente `_write_yaml` / `_stub_cmis`) con AIMD
    habilitado (`max_threads=16`, `workers=4`); assertear que
    el `max_workers` grabado para un pool con prefijo `s5` es
    `16`.
  - `test_single_pool_uses_workers_when_auto_tune_disabled` —
    misma captura, AIMD omitido; assertear
    `max_workers == 4`.
  - `test_dual_pools_sized_to_ceiling` — un config dual-lane
    (`heavy_light_lanes.enabled: true`) + un batch que se
    separa; assertear que tanto el pool `-heavy` como el
    `-light` grabaron `max_workers == ceiling`. Si disparar
    un lane split real en el harness CLI es pesado, hacer
    fallback a assertear que `_stage_5_dual` construye los
    pools al techo vía el mismo wrapper de captura impulsado
    directo.
  - Distinguir los pools de prep (056,
    `thread_name_prefix="cmcourier-prep"`) de los pools de S5
    (`"cmcourier-s5*"`) en el wrapper de captura así el pool
    de prep de 056 no contamina la aserción.

### Verify

Suite completa unit + integration + ruff + mypy.

### Commit

```
fix(s5): size the upload thread pool to the AIMD ceiling, not the initial worker count (057 Phase 1)
```

## Fase 2 — CHANGELOG 0.60.0 + bump de versión + README + FF (~20 min)

### Archivos

- `CHANGELOG.md` `[0.60.0]` — Fixed (el
  `ThreadPoolExecutor` de S5 estaba dimensionado a
  `cmis.workers`, así que el `ResizableSemaphore`
  redimensionado por AIMD nunca podía exceder la cuenta
  inicial de workers — `pool_in_use` topado en `cmis.workers`
  mientras la capacity de la TUI trepaba; la palanca de
  auto-tune estaba desconectada del motor desde 025/043).
- `pyproject.toml` 0.59.0 → 0.60.0.
- Tick en fila de features de `README.md`.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.60.0
```

### Commit

```
docs(057): CHANGELOG 0.60.0 + version bump (057 Phase 2)
```

### FF a main.

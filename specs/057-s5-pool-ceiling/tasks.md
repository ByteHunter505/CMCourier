# 057 — Tasks

## Fase 1 — Dimensionar el pool de S5 al techo de AIMD + tests

- [x] 1.1 `staged.py`: helper `_pool_ceiling()` —
      `max(workers, auto_tune.max_threads)` cuando AIMD
      habilitado, sino `workers`.
- [x] 1.2 `staged.py`: `_stage_5_single` construye su
      `ThreadPoolExecutor` con
      `max_workers=self._pool_ceiling()`; `set_pool_size` usa
      el techo también.
- [x] 1.3 `staged.py`: `_stage_5_dual` construye los dos
      `ThreadPoolExecutor` (heavy + light) con
      `max_workers=self._pool_ceiling()`.
- [x] 1.4 Tests: unit de `_pool_ceiling()` — AIMD on →
      `max_threads`, AIMD off → `workers`,
      `workers > max_threads` → `workers`.
- [x] 1.5 Tests: capturar `max_workers` vía un
      `ThreadPoolExecutor` instrumentado — `_stage_5_single`
      sobre un batch vacío es el techo con AIMD on,
      `cmis.workers` con AIMD off; ambos pools de
      `_stage_5_dual` son el techo. El pool de prep de 056
      excluido por el filtro de prefijo del thread-name
      `cmcourier-s5*`.
- [x] 1.6 Suite completa unit + integration verde (1218
      pasados; la única falla es el conocido test
      timing-flaky `test_dual_lane_throughput` — pasa aislado,
      no se ve afectado por 057 dado que `_pool_ceiling()`
      devuelve `cmis.workers` cuando AIMD está off). mypy +
      ruff limpios.
- [x] 1.7 Commit
      `fix(s5): size the upload thread pool to the AIMD ceiling, not the initial worker count (057 Phase 1)`.

## Fase 2 — CHANGELOG 0.60.0 + bump de versión + README + FF

- [x] 2.1 `CHANGELOG.md [0.60.0]` — Fixed.
- [x] 2.2 `pyproject.toml` 0.59.0 → 0.60.0.
- [x] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [x] 2.4 `cmcourier --version` reporta 0.60.0.
- [x] 2.5 Tick en fila de features de `README.md`.
- [x] 2.6 Suite completa + ruff + mypy limpios (verificado en
      Fase 1, 1218 pasados; la Fase 2 no toca código — solo
      docs/CHANGELOG/version).
- [x] 2.7 Commit
      `docs(057): CHANGELOG 0.60.0 + version bump (057 Phase 2)`.
- [ ] 2.8 FF a main.

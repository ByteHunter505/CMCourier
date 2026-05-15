# 066 — Tasks

Branch: `feat/066-s4-process-pool`.

## Fase 1

- [ ] T1. `config/schema.py` — agregar
      `s4_use_processes: bool = True` y
      `s4_max_processes: int | None = None` a
      `ProcessingConfig`
- [ ] T2. Nuevo `adapters/assembly/pool.py` con
      `_pool_init`, `_pool_assemble`, y
      `build_s4_process_pool` a nivel módulo
- [ ] T3. `orchestrators/staged.py` —
      `StagedPipeline.__init__` acepta
      `s4_process_pool: ProcessPoolExecutor | None`;
      `_s4_one` despacha vía pool cuando está presente
- [ ] T4. `config/wiring.py` — construir el pool cuando
      está configurado, pasarlo al pipeline, registrar
      shutdown vía atexit
- [ ] T5. Tests:
  - defaults del schema de config + validación ge=1
  - helpers del pool picklables + estables al import
  - `_s4_one` despacha al pool cuando está presente
  - `_s4_one` hace fallback a llamada directa cuando el
    pool es None
  - run streaming de integración con
    `s4_use_processes=true`
- [ ] T6. Correr suite completa unit + integration verde
- [ ] T7. ruff + mypy limpios
- [ ] T8. Commit:
  - `feat(assembly): S4 in ProcessPoolExecutor for real CPU-bound parallelism (066 Phase 1)`

## Fase 2

- [ ] T9. CHANGELOG `[0.68.0]`
- [ ] T10. pyproject 0.67.0 → 0.68.0
- [ ] T11. `pip install -e . --no-deps` + chequeo de
      versión
- [ ] T12. Tick en fila de features de README
- [ ] T13. Commit
      `docs(066): CHANGELOG 0.68.0 + version bump (066 Phase 2)`
- [ ] T14. FF a main

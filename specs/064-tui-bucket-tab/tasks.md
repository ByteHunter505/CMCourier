# 064 — Tasks

Branch: `feat/064-tui-bucket-tab`.

## Fase 1

- [ ] T1. Hooks del orchestrator
  - Contador `_prep_in_flight` + lock; producer `_inc()` /
    `_dec()`
  - `bucket_level()`, `prep_in_flight()`,
    `streaming_throughput()`
  - Trackear timestamps para throughput con ventana
    deslizante

- [ ] T2. `TUIDataProvider`
  - Campo `mode`
  - Callable `bucket_provider`
  - Método `bucket_snapshot()`

- [ ] T3. Tab Textual BUCKET
  - Nuevo widget `BucketTab`
  - Mount condicional basado en mode
  - Tick de refresh de 1s

- [ ] T4. Wiring de CLI
  - `cli/app.py` pasa `mode=` y `bucket_provider=` a la
    TUI

- [ ] T5. Tests
  - 3 tests unitarios de streaming (in_flight, level,
    throughput)
  - 3 tests unitarios de data-provider
  - 1 test liviano de binding de TUI (forma del
    rendering)

- [ ] T6. Verify: pytest unit + integration, ruff, mypy.

- [ ] T7. Commit:
  - `feat(tui): BUCKET tab for streaming mode (064 Phase 1)`

## Fase 2

- [ ] T8. CHANGELOG `[0.66.0]`
- [ ] T9. pyproject 0.65.0 → 0.66.0
- [ ] T10. `.venv/bin/pip install -e . --no-deps` +
  chequeo de versión
- [ ] T11. Tick en fila de features de README
- [ ] T12. Commit:
  `docs(064): CHANGELOG 0.66.0 + version bump + bucket-tab docs (064 Phase 2)`
- [ ] T13. FF a main

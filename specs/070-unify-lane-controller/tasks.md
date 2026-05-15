# 070 — Tasks

Branch: `feat/070-unify-lane-controller`.

## Fase 1

- [ ] T1. `streaming.py`: descartar la construcción
      `LaneController(...)` en `__init__`. Reemplazar el
      campo `self._lane_controller` con una propiedad que
      devuelve `self._pipeline.lane_controller`.
- [ ] T2. `_FakePipeline` en test_streaming expone el
      atributo `lane_controller`.
- [ ] T3. Test `test_streaming_reuses_pipeline_lane_controller`
      clavando la identidad.
- [ ] T4. Verificar pytest, ruff, mypy limpios.
- [ ] T5. Commit
      `fix(streaming): unify LaneController with pipeline — UPLOAD-tab LANES live (070 Phase 1)`

## Fase 2

- [ ] T6. CHANGELOG `[0.72.0]`
- [ ] T7. pyproject 0.71.0 → 0.72.0
- [ ] T8. `pip install -e . --no-deps` + chequeo de
      versión
- [ ] T9. Tick en fila de features de README
- [ ] T10. Commit
      `docs(070): CHANGELOG 0.72.0 + version bump (070 Phase 2)`
- [ ] T11. FF a main

# 068 — Tasks

Branch: `feat/068-aimd-aggressive-scaling`.

## Fase 1

- [ ] T1. `config/schema.py`: agregar 3 campos nuevos de
      AutoTune con defaults + validators
- [ ] T2. `services/auto_tune.py`: actualizar `decide()`
      para crecimiento multiplicativo, halve suave, umbral
      configurable, label de acción `"+N"`
- [ ] T3. Tests: defaults + rangos del schema
- [ ] T4. Tests: aserciones actualizadas de AIMD decide +
      4 tests nuevos de cobertura
- [ ] T5. pytest completo + ruff + mypy limpios
- [ ] T6. Commit
      `feat(auto-tune): aggressive growth + soft halve + tolerant threshold (068 Phase 1)`

## Fase 2

- [ ] T7. CHANGELOG `[0.70.0]`
- [ ] T8. pyproject 0.69.0 → 0.70.0
- [ ] T9. `pip install -e . --no-deps` + chequeo de
      versión
- [ ] T10. Tick en fila de features de README
- [ ] T11. Commit
      `docs(068): CHANGELOG 0.70.0 + version bump (068 Phase 2)`
- [ ] T12. FF a main

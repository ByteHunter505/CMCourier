# 068 — Tasks

Branch: `feat/068-aimd-aggressive-scaling`.

## Phase 1

- [ ] T1. `config/schema.py`: add 3 new AutoTune fields with
      defaults + validators
- [ ] T2. `services/auto_tune.py`: update `decide()` for
      multiplicative growth, soft halve, configurable threshold,
      action label `"+N"`
- [ ] T3. Tests: schema defaults + ranges
- [ ] T4. Tests: AIMD decide updated assertions + 4 new
      coverage tests
- [ ] T5. Full pytest + ruff + mypy clean
- [ ] T6. Commit `feat(auto-tune): aggressive growth + soft halve + tolerant threshold (068 Phase 1)`

## Phase 2

- [ ] T7. CHANGELOG `[0.70.0]`
- [ ] T8. pyproject 0.69.0 → 0.70.0
- [ ] T9. `pip install -e . --no-deps` + version verify
- [ ] T10. README feature row tick
- [ ] T11. Commit `docs(068): CHANGELOG 0.70.0 + version bump (068 Phase 2)`
- [ ] T12. FF to main

# 069 — Tasks

Branch: `feat/069-bandwidth-sampler-window`.

## Fase 1

- [ ] T1. `_BandwidthSampler.record_upload`: firma nueva
      + distribución uniforme sobre los buckets del
      intervalo
- [ ] T2. `_BandwidthHandler.emit`: derivar started_at,
      impulsar la firma nueva. Fallback defensivo cuando
      duration_ms falta.
- [ ] T3. Tests: sanity de distribución, fraccionario,
      sub-segundo, cumulative preservado, pico refleja
      sostenido.
- [ ] T4. Tests: el handler lee duration_ms / hace
      fallback.
- [ ] T5. pytest completo + ruff + mypy limpios.
- [ ] T6. Commit
      `fix(metrics): distribute bandwidth bytes over real transmission window (069 Phase 1)`

## Fase 2

- [ ] T7. CHANGELOG `[0.71.0]`
- [ ] T8. pyproject 0.70.0 → 0.71.0
- [ ] T9. `pip install -e . --no-deps` + chequeo de
      versión
- [ ] T10. Tick en fila de features de README
- [ ] T11. Commit
      `docs(069): CHANGELOG 0.71.0 + version bump (069 Phase 2)`
- [ ] T12. FF a main

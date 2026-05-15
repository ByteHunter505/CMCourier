# 065 — Tasks

Branch: `feat/065-streaming-heavy-light-lanes`.

## Fase 1

- [ ] T1. Extender `streaming_upload_one(..., lane=None)`
      en `staged.py`
- [ ] T2. `StreamingOrchestrator`: `LaneController`
      opcional, colas per-lane, thread dispatcher, pools
      consumer per-lane
- [ ] T3. Campo `StreamingSnapshot.lane_snapshot`;
      poblarlo en `streaming_snapshot()`
- [ ] T4. `cli/app.py`: descartar el WARN de 063 sobre
      streaming+lanes
- [ ] T5. El tab BUCKET renderiza el bloque LANES cuando
      está presente
- [ ] T6. Tests:
  - el dispatcher rutea por tamaño
  - shutdown limpio con lanes
  - el snapshot lleva `lane_snapshot`
  - el tab BUCKET renderiza el bloque de lane
- [ ] T7. Verificar pytest, ruff, mypy
- [ ] T8. Commit
      `feat(orchestrator): heavy/light lanes in streaming mode (065 Phase 1)`

## Fase 2

- [ ] T9. CHANGELOG `[0.67.0]`
- [ ] T10. pyproject 0.66.0 → 0.67.0
- [ ] T11. `pip install -e . --no-deps` + chequeo de
      versión
- [ ] T12. Tick en fila de features de README
- [ ] T13. Commit
      `docs(065): CHANGELOG 0.67.0 + version bump (065 Phase 2)`
- [ ] T14. FF a main

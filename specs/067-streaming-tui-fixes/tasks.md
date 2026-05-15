# 067 — Tasks

Branch: `feat/067-streaming-tui-fixes`.

## Fase 1

- [ ] T1. `streaming.py`: helper
      `_publish_pending_count` + llamada después de cada
      put/get
- [ ] T2. `streaming.py`: chunk sintético status="UPLOAD"
      en tiempo de spawn del thread + helper
      `_publish_chunk_state` llamado después de cada
      outcome S5
- [ ] T3. `streaming.py`: dispatcher + lane-consumer
      reportan `lane_queue.qsize()` al LaneController
      (descartar contadores monotónicos)
- [ ] T4. Tests: queue_depth publicado, status a mitad de
      run es UPLOAD, s5_done en vivo crece, profundidad
      de queue de lane = qsize y ≤ bucket_size
- [ ] T5. pytest completo + ruff + mypy limpios
- [ ] T6. Commit
      `fix(streaming): live TUI bindings — bar/timer/CHUNKS/lane-queue (067 Phase 1)`

## Fase 2

- [ ] T7. CHANGELOG `[0.69.0]`
- [ ] T8. pyproject 0.68.0 → 0.69.0
- [ ] T9. `pip install -e . --no-deps` + chequeo de
      versión
- [ ] T10. Tick en fila de features de README (bullet de
      bugfix)
- [ ] T11. Commit
      `docs(067): CHANGELOG 0.69.0 + version bump (067 Phase 2)`
- [ ] T12. FF a main

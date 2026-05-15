# 067 — Tasks

Branch: `feat/067-streaming-tui-fixes`.

## Phase 1

- [ ] T1. `streaming.py`: `_publish_pending_count` helper +
      call after every put/get
- [ ] T2. `streaming.py`: synthetic chunk status="UPLOAD" at thread
      spawn time + `_publish_chunk_state` helper called after every
      S5 outcome
- [ ] T3. `streaming.py`: dispatcher + lane-consumer report
      `lane_queue.qsize()` to LaneController (drop monotonic counters)
- [ ] T4. Tests: queue_depth published, status mid-run is UPLOAD,
      live s5_done grows, lane queue depth = qsize and ≤ bucket_size
- [ ] T5. Full pytest + ruff + mypy clean
- [ ] T6. Commit `fix(streaming): live TUI bindings — bar/timer/CHUNKS/lane-queue (067 Phase 1)`

## Phase 2

- [ ] T7. CHANGELOG `[0.69.0]`
- [ ] T8. pyproject 0.68.0 → 0.69.0
- [ ] T9. `pip install -e . --no-deps` + version verify
- [ ] T10. README feature row tick (bugfix bullet)
- [ ] T11. Commit `docs(067): CHANGELOG 0.69.0 + version bump (067 Phase 2)`
- [ ] T12. FF to main

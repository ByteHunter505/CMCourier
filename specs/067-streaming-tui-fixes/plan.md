# 067 — Plan

Single-phase fix spec. All changes in `streaming.py` (+ tests).

## Phase 1 — fixes + tests

### `src/cmcourier/orchestrators/streaming.py`

1. **Pending-count helper**: new `_publish_pending_count(main_bucket,
   heavy_queue, light_queue)` reads `qsize()` of each queue, sums,
   calls `self._pipeline.pool_stats.set_queue_depth(total)`. Called
   after each `put` / `get`.

2. **Status transition + live chunk_state**: when threads spawn,
   transition synthetic chunk to `status="UPLOAD"` with
   `upload_started_monotonic=start` and `prep_started_monotonic=
   start`. New `_publish_chunk_state(batch_id, tally, tally_lock)`
   helper called after every S5 outcome inside `_upload_loop` and
   `_lane_upload_loop`. Reads tally under lock, writes synthesised
   ChunkState under `_state_lock`.

3. **Dispatcher + consumer report real qsize**: replace the
   `heavy_depth`/`light_depth` private counters with
   `heavy_queue.qsize()` / `light_queue.qsize()` calls. Both
   dispatcher (after put) and consumer (after get) report.

### Tests (`tests/unit/orchestrators/test_streaming.py`)

- `test_streaming_publishes_queue_depth` — after a few items pass
  through, `pipeline.pool_stats.queue_depth` is non-zero
  (live counter).
- `test_streaming_status_transitions_to_upload_at_start` — poll
  `chunks_snapshot()[0].status` shortly after `run` starts; expect
  `"UPLOAD"`.
- `test_streaming_publishes_live_s5_counters` — during a run with
  N triggers, `chunks_snapshot()[0].s5_done` grows from 0 toward N.
- `test_dispatcher_reports_real_qsize` — in dual-lane mode,
  `lane_controller.snapshot().heavy.queue_depth` matches
  `heavy_queue.qsize()` and never exceeds `bucket_size`.

### Verify

`pytest tests/unit tests/integration -q`. ruff + mypy clean.

### Commit

```
fix(streaming): live TUI bindings — bar/timer/CHUNKS/lane-queue (067 Phase 1)
```

## Phase 2 — release

- CHANGELOG `[0.69.0]`
- pyproject 0.68.0 → 0.69.0
- `.venv/bin/pip install -e . --no-deps` + version verify
- README feature row tick (smaller bullet — it's a bugfix release)
- FF to main

Commit: `docs(067): CHANGELOG 0.69.0 + version bump (067 Phase 2)`.

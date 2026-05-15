# 065 — Plan

Two phases.

## Phase 1 — wiring + tests

### Files

- `src/cmcourier/orchestrators/streaming.py`
  - Add `LaneController` field (optional, only when
    `heavy_light_lanes.enabled` is true).
  - Add per-lane `queue.Queue`s in `run()`.
  - Replace single consumer pool with: 1 dispatcher + N heavy
    consumers + M light consumers.
  - Dispatcher loop: pull from main bucket; if `_POISON`, push
    `_POISON` into both lane queues × consumer count and exit;
    else read `staged_file.size_bytes`, push to heavy or light
    queue based on threshold.
  - Per-lane consumer loop: `bucket.get()` from its lane queue;
    on `_POISON`, exit; else `streaming_upload_one(item, ...,
    lane=...)` (extend the signature) and tally.
  - `streaming_snapshot()` already exists — gain a
    `lane_snapshot: LaneSnapshot | None` field on
    `StreamingSnapshot`.

- `src/cmcourier/orchestrators/staged.py`
  - `streaming_upload_one(item, batch_id, recorder, lane=None)`
    — already calls `_upload_one(item, batch_id, recorder, lane)`,
    just thread the param through (lane defaults to None).

- `src/cmcourier/cli/app.py`
  - Drop the `streaming + heavy_light_lanes` WARN (065 lands it).

- `src/cmcourier/tui/bucket_tab.py`
  - Print a LANES block when `snap.lane_snapshot is not None`.

### Tests

- `tests/unit/orchestrators/test_streaming.py`
  - `test_dispatcher_routes_by_size` — feed items with mixed
    `size_bytes`; assert heavy items go to heavy lane, light to
    light. The `_FakePipeline` already supports
    `streaming_upload_one(item, batch_id, recorder, lane=None)`.
  - `test_clean_shutdown_with_lanes` — empty source + dual mode
    drains all threads.
  - `test_streaming_snapshot_carries_lane_snapshot_when_enabled`.

- `tests/unit/tui/test_bucket_tab.py`
  - `test_renders_lane_block_when_lane_snapshot_present`.

### Verify

`pytest tests/unit tests/integration -q`. ruff + mypy clean.

### Commit

```
feat(orchestrator): heavy/light lanes in streaming mode (065 Phase 1)
```

## Phase 2 — release

- CHANGELOG `[0.67.0]`.
- pyproject 0.66.0 → 0.67.0.
- `.venv/bin/pip install -e . --no-deps`; `cmcourier --version`.
- README feature row tick.
- FF to main.

Commit: `docs(065): CHANGELOG 0.67.0 + version bump (065 Phase 2)`.

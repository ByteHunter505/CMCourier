# 064 — Plan

Two phases.

## Phase 1 — orchestrator hooks + data provider + TUI tab + tests

### Files

- `src/cmcourier/orchestrators/streaming.py`
  - New `_prep_in_flight` AtomicInteger pattern via `threading.Lock`
    + counter; producers `_inc()` before `streaming_prep_one`, `_dec()`
    in finally.
  - New public methods:
    - `bucket_level() -> int` (reads `_bucket.qsize()` if bucket
      exists else 0)
    - `prep_in_flight() -> int`
    - `streaming_throughput() -> tuple[float, float]` — returns
      `(prep_docs_per_s, upload_docs_per_s)` over a 5s window using
      ring-buffer timestamps maintained by the producer/consumer
      loops.

- `src/cmcourier/tui/data_provider.py`
  - Add `mode: Literal["batched", "streaming"] = "batched"` ctor arg.
  - Add `bucket_provider: Callable[[], dict] | None = None` ctor arg
    (returns a dict with level/cap/peak/throughput keys).
  - New `bucket_snapshot()` method.

- `src/cmcourier/tui/app.py` (or wherever `CMCourierTUI` lives)
  - Conditionally add a `BucketTab` to `TabbedContent`.
  - Wire `set_interval` refresh to read `bucket_snapshot()`.
  - Hide CHUNKS tab in streaming mode (or swap visibility).

- `src/cmcourier/cli/app.py`
  - Pass `mode=config.processing.mode` and a bucket_provider lambda
    pointing at the orchestrator's `bucket_*` methods to
    `TUIDataProvider`.

### Tests

- `tests/unit/orchestrators/test_streaming.py`
  - `test_prep_in_flight_increments_during_prep` (use a Barrier
    in the fake's prep to assert counter > 0 mid-flight).
  - `test_bucket_level_reflects_queue_state` (force the bucket
    full, assert level == cap).
  - `test_streaming_throughput_window` (drive a known burst,
    assert positive throughput).

- `tests/unit/tui/test_data_provider.py` (new or extended)
  - `test_mode_default_batched`.
  - `test_mode_streaming_propagates`.
  - `test_bucket_snapshot_no_provider_returns_none`.

### Verify

`pytest tests/unit tests/integration -q`, ruff + mypy clean.

### Commit

```
feat(tui): BUCKET tab for streaming mode (064 Phase 1)
```

## Phase 2 — release

- CHANGELOG `[0.66.0]`.
- pyproject 0.65.0 → 0.66.0.
- `.venv/bin/pip install -e . --no-deps`; `cmcourier --version`.
- README feature row tick (065 changeset).
- FF to main.

Commit: `docs(064): CHANGELOG 0.66.0 + version bump + bucket-tab docs (064 Phase 2)`.

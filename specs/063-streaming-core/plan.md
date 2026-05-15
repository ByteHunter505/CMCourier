# 063 — Plan

Two phases.

## Phase 1 — Streaming orchestrator + config + wiring + tests

### Files

- `src/cmcourier/config/schema.py`
  - New `StreamingConfig(BaseModel)` with `bucket_size: int = 100, ge=1`.
  - `ProcessingConfig.mode: Literal["batched", "streaming"] = "batched"`.
  - `ProcessingConfig.streaming: StreamingConfig`.
  - Docstring note that `batches_in_flight` is ignored in streaming.

- `src/cmcourier/orchestrators/streaming.py` (new file)
  - `class StreamingOrchestrator`. Constructor mirrors
    `MultiBatchOrchestrator` (pipeline, config, log_dir) plus an
    explicit `bucket_size` derived from config.
  - `.run(*, source_descriptor, batch_size, batches_in_flight, ...)`
    — same signature for CLI compatibility; rejects `from_stage > 1`
    and non-None `resume_batch_id` with ValueError; ignores
    `batches_in_flight` and `batch_size`.
  - Internals:
    - `start_batch(0)` → single batch_id for the run.
    - `MetricsRecorder.start_batch(...)` once.
    - `bucket = queue.Queue[_StageItem | None](maxsize=bucket_size)`.
    - `trigger_iter` = iter(strategy.acquire(...)) capped by `total`
      if set; protected by a Lock.
    - Spawn `prep_workers` producer threads + `cmis.workers` consumer
      threads (consumer count == initial worker count; AIMD adjusts
      semaphore inside _upload_one, same as batched).
    - Producer loop: pull trigger; call
      `pipeline.streaming_prep_one(trigger, batch_id, recorder)`; on
      success push to bucket. On StopIteration: push N poison pills,
      exit.
    - Consumer loop: `bucket.get()`; if `None`, `task_done()` then
      break; else call `pipeline._upload_one(item, batch_id, recorder)`;
      tally outcome; `task_done()`.
    - Join all threads.
    - Close batch, return a `MultiBatchRunReport` with a single
      synthetic `RunReport`.
  - `chunks_snapshot()`: returns a single-row list describing the
    run (synthetic, for the TUI's existing CHUNKS tab fallback).
  - `active_recorder()`, `upload_recorder()`: both return the single
    global recorder.

- `src/cmcourier/orchestrators/staged.py`
  - New public method
    `streaming_prep_one(trigger, batch_id, recorder) -> _StageItem | None`.
    Runs S0/S1 on `[trigger]` (single-element list), then for each
    survivor runs `_s2_one`, `_s3_one`, `_s4_one` sequentially. Returns
    the surviving item or `None` (filtered / failed / cross-batch
    skipped — all already persisted by the inner helpers).

- `src/cmcourier/cli/app.py`
  - `run_orchestrator_with_tui` factory: choose
    `StreamingOrchestrator` when `config.processing.mode == "streaming"`.
  - WARN log when `mode == "streaming"` and
    `heavy_light_lanes.enabled is True` (deferred to spec 065).
  - WARN log when `mode == "streaming"` and `--from-stage > 1` or
    operator-named `--batch-id` is passed — *and* the orchestrator
    raises ValueError downstream.

### Tests

- `tests/unit/config/test_schema.py`
  - `processing.mode` defaults `"batched"`, rejects `"invalid"`.
  - `processing.streaming.bucket_size` defaults 100, rejects 0.

- `tests/integration/pipeline/test_streaming_pipeline.py` (new)
  - Re-use `pipeline_harness`. Add a helper `build_streaming_pipeline`
    that constructs the `StreamingOrchestrator` against the harness's
    shared pipeline.
  - `test_streaming_uploads_all_docs` — 2-doc happy path, every doc
    `S5_DONE`.
  - `test_streaming_bucket_caps_memory` — `bucket_size=2` against 6
    docs (the rvabrep fixture's full set); patch `queue.Queue.put` or
    sample `qsize()` to assert peak ≤ 2.
  - `test_streaming_rejects_resume_args` — `from_stage=3` or
    `resume_batch_id="x"` with streaming raises ValueError.
  - `test_streaming_cross_batch_idempotency` — first run uploads, second
    run produces `S1_SKIPPED` rows (062 path).

- `tests/unit/orchestrators/test_streaming.py` (new)
  - `test_iterator_is_thread_safe` — two fake producers consume from
    the shared iterator; no trigger is processed twice (counter).
  - `test_poison_pill_drains_consumers` — single producer with 0
    triggers; N consumers; all join cleanly.
  - `test_streaming_orchestrator_returns_runreport` — shape check.

### Verify

`pytest tests/unit tests/integration -q` green. ruff + mypy clean.

### Commit

```
feat(orchestrator): streaming mode with bucket-based producer-consumer (063 Phase 1)
```

## Phase 2 — CHANGELOG 0.65.0 + version + README + FF

Standard release dance + `cmcourier --version` proof + FF to main.

Commit: `docs(063): CHANGELOG 0.65.0 + version bump + streaming docs (063 Phase 2)`.

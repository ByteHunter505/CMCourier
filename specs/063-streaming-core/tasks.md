# 063 — Tasks

Branch: `feat/063-streaming-core`. Two-phase commit.

## Phase 1 — implementation

- [ ] T1. `src/cmcourier/config/schema.py`
  - Add `StreamingConfig(BaseModel)` with `bucket_size: int = Field(default=100, ge=1)`.
  - Add `mode: Literal["batched", "streaming"] = "batched"` to `ProcessingConfig`.
  - Add `streaming: StreamingConfig = Field(default_factory=StreamingConfig)` to `ProcessingConfig`.
  - Field docstring on `batches_in_flight` notes "ignored in streaming mode".

- [ ] T2. `src/cmcourier/orchestrators/staged.py`
  - New public `streaming_prep_one(trigger, batch_id, recorder)` method:
    - Wraps S0/S1 on `[trigger]` (preserving filter/skip persistence).
    - Calls `_s2_one` → `_s3_one` → `_s4_one` sequentially for each survivor.
    - Returns the single surviving `_StageItem` or `None`.
  - Refactor existing `_run_prep_stage` to share the inner helpers (no behaviour change).

- [ ] T3. `src/cmcourier/orchestrators/streaming.py` (new)
  - `class StreamingOrchestrator`. Same `.run(...)` signature as
    `MultiBatchOrchestrator` for CLI parity.
  - Thread-safe trigger iterator (`_TriggerIter` with `threading.Lock`).
  - `queue.Queue[_StageItem | None](maxsize=bucket_size)`.
  - Producer thread(s) `_prep_loop` — pull trigger, prep, `put` (blocks on full).
  - Consumer thread(s) `_upload_loop` — `get`, upload, `task_done`. Break on `None`.
  - `_shutdown_event` for cooperative abort on Ctrl+C.
  - Returns a `MultiBatchRunReport` with a single synthetic `RunReport`.
  - Reject `from_stage > 1` and non-None `resume_batch_id` with `ValueError`.

- [ ] T4. `src/cmcourier/cli/app.py`
  - Orchestrator factory branches on `config.processing.mode`.
  - WARN log when streaming + `heavy_light_lanes.enabled` (defer to 065).
  - Same logger statement on conflicting resume args (the orchestrator
    also raises — log first for operator clarity).

- [ ] T5. `src/cmcourier/orchestrators/__init__.py`
  - Re-export `StreamingOrchestrator`.

- [ ] T6. `tests/unit/config/test_schema.py`
  - `processing.mode` default = `"batched"`, rejects `"invalid"`.
  - `processing.streaming.bucket_size` default = 100, rejects 0 and -1.

- [ ] T7. `tests/unit/orchestrators/test_streaming.py` (new)
  - `test_iterator_thread_safe` — two producers, no double-pull.
  - `test_poison_pill_drains_consumers` — empty source, all consumers exit.
  - `test_rejects_from_stage_gt_one`.
  - `test_rejects_explicit_batch_id`.

- [ ] T8. `tests/integration/pipeline/test_streaming_pipeline.py` (new)
  - `test_streaming_uploads_all_docs` — 6-trigger fixture, all `S5_DONE`.
  - `test_streaming_bucket_caps_memory` — bucket_size=2, hook on
    `Queue.put`, assert peak qsize ≤ 2.
  - `test_streaming_cross_batch_idempotency` — second run yields
    `S1_SKIPPED` rows (062 contract intact).

- [ ] T9. Run `pytest tests/unit tests/integration -q`. Green required.
  - `ruff check .` + `mypy src` clean.

- [ ] T10. Commit:
  - `feat(orchestrator): streaming mode with bucket-based producer-consumer (063 Phase 1)`

## Phase 2 — release dance

- [ ] T11. `CHANGELOG.md` — `[0.65.0]` entry, sections:
  - Added: streaming mode (`processing.mode`, `processing.streaming.bucket_size`).
  - Internal: `StreamingOrchestrator`, `streaming_prep_one`.
  - Notes: heavy/light lanes deferred to 065; TUI BUCKET tab in 064.

- [ ] T12. `pyproject.toml` — version 0.64.0 → 0.65.0.

- [ ] T13. `.venv/bin/pip install -e . --no-deps`. `cmcourier --version` → 0.65.0.

- [ ] T14. `README.md` — feature row tick for streaming mode.

- [ ] T15. Commit:
  - `docs(063): CHANGELOG 0.65.0 + version bump + streaming docs (063 Phase 2)`

- [ ] T16. FF to main (`git checkout main && git merge --ff-only feat/063-streaming-core`). No push.

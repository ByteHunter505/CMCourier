# 028 — Implementation Plan

> Companion to `spec.md`. Four phases, ~10h total.

---

## Phase 1 — Schema + chunker (~1.5h)

1. Add `ProcessingConfig` Pydantic model to
   `cmcourier/config/schema.py`. Field:
   `batches_in_flight: int = Field(default=2, ge=1, le=5)`.
2. Add `processing: ProcessingConfig =
   Field(default_factory=ProcessingConfig)` to
   `PipelineConfig`.
3. Add 4 schema tests to `tests/unit/config/test_schema.py`.
4. Create `cmcourier/orchestrators/chunked.py` with:
   ```python
   from collections.abc import Iterable, Iterator
   from typing import TypeVar

   T = TypeVar("T")

   def chunked(items: Iterable[T], size: int) -> Iterator[list[T]]:
       ...
   ```
5. 4 unit tests in `tests/unit/orchestrators/test_chunked.py`.

**Done when**: `pytest tests/unit/config tests/unit/orchestrators/test_chunked.py`
passes.

---

## Phase 2 — MetricsRecorder per-batch routing (~2h)

1. Modify `_SlowOpHandler` to accept a `batch_id` in its
   constructor and **filter** records by
   `record.batch_id`. Records without `batch_id` or with a
   mismatched value are silently dropped at the handler
   level (never reach the aggregator).
2. Modify `MetricsRecorder.start_batch` to:
   - Stash `batch_id` on the recorder.
   - Pass it to the new handler.
3. Add 3 unit tests in
   `tests/unit/observability/test_metrics.py`:
   - Two concurrent recorders, each with a different
     `batch_id`, attach their handlers; emit a log record
     with batch_id A; assert only recorder A's aggregator
     saw the op.
   - Records without a `batch_id` are dropped (no
     phantom slow ops).
   - The bandwidth handler (un-filtered) continues to see
     every record.

**Risk**: existing tests that emit network records without
a `batch_id` (e.g. ad-hoc unit tests for the uploader) may
no longer be visible in the slow-ops aggregator. Audit the
existing test suite; most likely no real change because the
tests that care set the batch_id.

**Done when**: 715-ish tests passing; 3 new isolation tests
green.

---

## Phase 3 — MultiBatchOrchestrator + CLI (~4h)

1. Create
   `cmcourier/orchestrators/multi_batch.py` with:
   - `@dataclass(frozen=True) class MultiBatchRunReport`.
   - `class MultiBatchOrchestrator` with a `run(...)` method
     that:
     - Receives a fully-built `StagedPipeline` and the same
       kwargs `StagedPipeline.run` accepts plus
       `batches_in_flight: int`.
     - For `batches_in_flight == 1` or a `resume_batch_id`:
       delegate to `pipeline.run(...)` and wrap the
       `RunReport` in a `MultiBatchRunReport` with one
       chunk.
     - For `batches_in_flight >= 2`:
       - `triggers = list(pipeline._trigger_strategy.acquire(...))`
       - `chunks = list(chunked(triggers, batch_size))`
       - Prep-worker pool of size `batches_in_flight - 1`
         executing `_prep_chunk(chunk_idx, triggers)`.
       - One upload thread consuming a `queue.Queue` of
         prepared chunks and running `_upload_chunk`.
       - Each chunk gets its own `batch_id` via
         `tracking_store.start_batch`.
       - Each chunk gets its own assembler temp subdir:
         `{config.assembly.temp_dir}/{batch_id}/`.
2. Tests in
   `tests/unit/orchestrators/test_multi_batch.py`:
   - N=1 passes through unchanged.
   - N=2 overlap: events from chunk N+1's S0 occur before
     chunk N's S5 completes (timestamp assert).
   - N=4 concurrent prep without recorder crosstalk.
   - Exception in one chunk: others finish; report lists
     it.
3. CLI wire-up:
   - Add `--batches-in-flight <N>` flag to every pipeline
     run command. Default: from config.
   - `--resume` forces 1 (warning log if user passed both).
   - Refactor `_run_with_optional_tui` to route through the
     orchestrator. The TUI's `TUIDataProvider` is bound to
     the most-recently-started chunk's MetricsRecorder
     (acceptable simplification for this change).
4. Integration tests in
   `tests/integration/cli/test_multi_batch.py`:
   - `--batches-in-flight 1` happy path matches pre-028.
   - `--batches-in-flight 2` with 3-row trigger CSV +
     `--batch-size 1` produces 3 chunks. All succeed.
   - `--resume` overrides to N=1.

**Risk**: the TUI may flicker as it rebinds its provider
each chunk. Acceptable for v1 — long-multi-batch TUI is
out of scope.

**Done when**: integration tests pass; existing
`tests/integration/cli/test_cli.py` still green.

---

## Phase 4 — Docs + verification + FF merge (~2.5h)

1. Create `docs/how-to/multi-batch.md`:
   - The producer-consumer model in one diagram.
   - Default `batches_in_flight=2`; how to change it.
   - Memory budgeting guidance.
   - Examples: `--batches-in-flight`, `--resume`.
2. CHANGELOG `[0.30.0]` + `[Unreleased]` reconciliation.
3. README status checklist tick (28th change).
4. POST-MVP §7 marked SHIPPED.
5. Full gate: ruff + mypy + pytest (≥715).
6. Conventional commit + FF merge into `main`.

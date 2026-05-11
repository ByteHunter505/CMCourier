# 028 — Multi-Batch Orchestrator (`batches_in_flight`)

> Status: **Proposed** — 2026-05-11
> Author: bitBreaker
> Predecessor: 020, 025, 026, 027
> POST-MVP roadmap reference: `docs/roadmap/POST-MVP.md §7`

---

## 1. Summary

Replace the single-pass `pipeline.run()` execution model
(one batch, S0→S5 sequential) with a **producer-consumer
multi-batch orchestrator** that:

- **Chunks** the trigger source into multiple batches of
  `batch_size` triggers each.
- Runs **up to `processing.batches_in_flight` batches
  concurrently**, with `N-1` prep workers (S0–S4) feeding a
  single upload worker (S5).
- Each chunk gets its **own** `batch_id` in the tracking DB
  and its **own** `batch_summary` log event (per-chunk p95,
  per-chunk slow ops, per-chunk system samples).

Default `batches_in_flight=2` — i.e. the "siempre dos lotes
en vuelo" model: one batch preparing (S0–S4) while another
uploads (S5). The original POST-MVP §7 listed this as the
MVP overlap, but it was never implemented — the current
code processes everything in one sequential pass. This
change closes that gap.

---

## 2. Motivation

- **Operator mental model mismatch.** Operators expect the
  producer-consumer overlap described in REBIRTH and
  POST-MVP §7; the code did not match. Migrating 20 k docs
  in 1 k batches today is one big sequential pass, not 20
  overlapped batches.
- **Throughput**: while CMIS is uploading batch N, S0–S4 of
  batch N+1 can run concurrently — there's no reason for
  the trigger source / indexing / metadata / assembly stages
  to sit idle while the network is busy.
- **Prerequisite for §1 (heavy/light lanes)**: §1 splits a
  prepared batch by size into two upload pools. That model
  only makes sense once we have a meaningful unit of work
  ("one prepared chunk") to split.

---

## 3. Scope

### In scope

- New `ProcessingConfig` Pydantic block under
  `PipelineConfig.processing` with:
  - `batches_in_flight: int = Field(default=2, ge=1, le=5)`.
- New module
  `cmcourier/orchestrators/multi_batch.py` exposing:
  - `chunked(items, size) -> Iterator[list[T]]` — pure
    chunker.
  - `MultiBatchOrchestrator` — runs a `StagedPipeline`
    multiple times, once per chunk, with producer-consumer
    overlap.
  - `MultiBatchRunReport` — aggregated `RunReport` across
    chunks (totals + per-chunk list).
- Refactor: `MetricsRecorder.start_batch` now scopes the
  slow-ops aggregator and bandwidth handler to **that
  specific `batch_id`** so multiple recorders can be live
  simultaneously without crosstalk.
- CLI routes all pipeline run commands through the new
  orchestrator. When `batches_in_flight=1`, the orchestrator
  is effectively a thin pass-through (no behavior change).
- ≥16 unit tests + ≥3 integration tests covering: chunker
  correctness, per-chunk batch_id allocation, N=1
  regression, N=2 overlap, N=4 concurrent prep,
  exception in one chunk does not block others, total
  RunReport aggregation.
- Documentation: `docs/how-to/multi-batch.md` operator
  guide.

### Out of scope

- **TUI extension** — the current TUI shows one batch at a
  time. Surfacing all N in-flight batches in the UPLOAD tab
  is a separate change (we keep the TUI showing the most
  recently completed chunk's view, which is enough for the
  operator to monitor a long run).
- **Stress test with synthetic data measuring throughput
  improvement vs single-batch**. Acceptance criterion #2
  from §7 asks for this, but it requires real-world-like
  workloads that mocks can't simulate (mocked CMIS replies
  in 0 ms). Documented as a follow-up to validate against
  the staging dry run.
- **Memory budgeting formula** beyond a simple "N × biggest
  staged file" note in the how-to doc. Real numbers
  require real-data measurement.
- **Bandwidth limiter refactor** (per-stream → shared) —
  that's blocked on §1, where lanes need to share a token
  bucket. Out of scope here.

---

## 4. Requirements

### Configuration

- **REQ-001**: New `ProcessingConfig` Pydantic model under
  `cmcourier.config.schema` with `model_config = _STRICT`
  and one field:
  - `batches_in_flight: int = Field(default=2, ge=1, le=5)`.
- **REQ-002**: New `PipelineConfig.processing:
  ProcessingConfig = Field(default_factory=ProcessingConfig)`.
- **REQ-003**: ≥4 schema tests cover: defaults, custom
  value 1..5 accepted, value 0 rejected, value 6 rejected.

### Chunker

- **REQ-004**: `chunked(items, size)` returns an iterator
  of lists, each of size ≤ `size`. The last chunk may be
  smaller. Order preserved. Empty input → empty iterator.
- **REQ-005**: ≥4 unit tests for the chunker.

### MetricsRecorder refactor

- **REQ-006**: `MetricsRecorder.start_batch(pipeline,
  batch_id)` MUST tag its slow-ops handler with that
  `batch_id` so the handler ignores records whose
  `record.batch_id` differs.
- **REQ-007**: `MetricsRecorder._stage_buckets` is **reset
  per `start_batch` call** as today (per-chunk p95 is
  per-chunk, not cumulative across chunks).
- **REQ-008**: When multiple MetricsRecorders are alive
  concurrently and each attaches its own slow-ops handler
  to `cmcourier.metrics.network`, only the handler whose
  `batch_id` matches the record's `batch_id` records the
  op.
- **REQ-009**: The shared `_BandwidthSampler` continues to
  receive every record (no batch filtering) — bandwidth is
  a process-level signal, not per-batch.
- **REQ-010**: ≥3 unit tests for concurrent recorder
  isolation.

### MultiBatchOrchestrator

- **REQ-011**: `MultiBatchOrchestrator.run(pipeline,
  source_descriptor, *, total_records, batch_size,
  batches_in_flight, from_stage, resume_batch_id)`:
  - Acquires triggers from `pipeline._trigger_strategy`.
  - Chunks them into batches of `batch_size`.
  - Runs prep (S0–S4) in `(batches_in_flight - 1)` prep
    worker threads (or 1 when N=1 — effectively serial).
  - Routes prepared chunks via a `queue.Queue` to a single
    upload worker (S5).
  - Each chunk's run reuses the existing `StagedPipeline`
    methods (`_stage_s0_s1`..`_stage_s5`) but with a
    **fresh `batch_id`** per chunk allocated via
    `tracking_store.start_batch`.
- **REQ-012**: For `batches_in_flight == 1`, the
  orchestrator runs sequentially (no thread pool) so the
  current single-batch behavior is exactly preserved.
- **REQ-013**: An exception in one chunk's prep or upload
  MUST NOT block other chunks. The chunk is logged at
  ERROR and the remaining chunks continue. The final
  `MultiBatchRunReport.failed_chunks` lists the chunk's
  `batch_id` + exception type.
- **REQ-014**: `MultiBatchOrchestrator` returns a
  `MultiBatchRunReport` with:
  - `chunks: list[RunReport]` — per-chunk reports.
  - `failed_chunks: list[tuple[str, str]]` — batch_id +
    exception class name.
  - Aggregate fields: `total_triggers`, `total_docs`,
    `s1_done`, `s1_skipped_cross_batch`, `s2..s5_done`,
    `s2..s5_failed`, `elapsed_seconds`.
- **REQ-015**: `--resume --batch-id X` forces
  `batches_in_flight=1` and skips chunking — the orchestrator
  delegates straight to `pipeline.run(batch_id=X, from_stage=N)`.

### CLI integration

- **REQ-016**: Every pipeline run command (`csv-trigger`,
  `rvabrep`, `as400-trigger`, `local-scan`, `single-doc`)
  routes through the orchestrator. The existing flag set
  is preserved.
- **REQ-017**: New CLI flag `--batches-in-flight <N>`
  (default: from config, override: 1..5) on every pipeline
  run command. `--resume` overrides to 1.
- **REQ-018**: The CLI's `_emit_outcome` prints a
  per-chunk one-liner plus a totals line:
  ```
  chunk 1/20  batch_id=ABC  total_docs=1000  s5_done=998  s5_failed=2
  chunk 2/20  batch_id=DEF  total_docs=1000  s5_done=1000 s5_failed=0
  ...
  TOTALS      batch_count=20 total_docs=20000 s5_done=19987 s5_failed=13 elapsed_s=512.4
  ```
- **REQ-019**: Exit code:
  - 0 if every chunk's `s5_failed == 0` AND
    `failed_chunks == []`.
  - 1 if any chunk had `s5_failed > 0`.
  - 3 if any chunk crashed.

### Tests

- **REQ-020**: ≥4 schema tests (REQ-003).
- **REQ-021**: ≥4 chunker unit tests (REQ-005).
- **REQ-022**: ≥3 MetricsRecorder concurrent-isolation
  tests (REQ-010).
- **REQ-023**: ≥4 orchestrator unit tests covering N=1
  regression, N=2 overlap, N=4 concurrent prep,
  exception isolation.
- **REQ-024**: ≥3 CLI integration tests covering
  `--batches-in-flight 1`, `--batches-in-flight 2`, and
  `--resume` forcing N=1.

### Verification

- **REQ-025**: `pytest` MUST report ≥715 passing (695 from
  027 + the new tests).
- **REQ-026**: `mypy src/cmcourier/` clean.
- **REQ-027**: `ruff check` + `ruff format --check` clean.
- **REQ-028**: `docs/how-to/multi-batch.md` exists with
  the producer-consumer model explained, memory budgeting
  guidance, and CLI examples.

---

## 5. Acceptance scenarios

1. **Backwards-compat**: A YAML without a `processing`
   block loads with `batches_in_flight=2` (the new
   default). Existing tests that supply small trigger
   sources (1 record) produce identical output to before
   — the single chunk goes through the orchestrator with
   no observable difference.
2. **Explicit N=1**: `processing.batches_in_flight: 1`
   forces the orchestrator into the serial path; behavior
   is byte-identical to pre-028.
3. **N=2 overlap on a 5-chunk source**: The orchestrator
   processes 5 chunks. Logs show prep of chunk N+1
   overlapping with upload of chunk N (timestamps on
   `stage_complete` events confirm).
4. **N=4 concurrent prep**: A 10-chunk source with N=4
   has up to 3 prep threads + 1 upload thread. All 10
   chunks finish; no race conditions in the metrics
   recorder.
5. **Chunk failure isolation**: One chunk raises in S2
   (synthetic). The remaining chunks continue; the run
   reports `failed_chunks=[(B3, IndexingError)]` and exit
   code 1 (because s5_failed > 0 from the failed chunk's
   point of view — or 3 if it crashed outright).
6. **Resume forces N=1**: `--resume --batch-id ABC`
   ignores `--batches-in-flight` and runs the single
   batch with the existing resume semantics.
7. **TUI unchanged**: The TUI still shows one batch
   at a time (the currently uploading chunk). Operators
   running long multi-batch jobs see each chunk in turn.

---

## 6. Risks

- **Trigger source thread-safety**: AS400 query strategies
  may have stateful cursors. The chunker consumes the
  trigger iterable SERIALLY from one thread (the
  orchestrator's main thread), then dispatches chunks to
  worker threads. Cursors are never shared across threads.
- **Tracking store concurrency**: 025 already made
  `SQLiteTrackingStore` thread-safe via `check_same_thread=False`
  + `_reader_lock`. Multiple chunks calling `start_batch`
  / `complete_batch` concurrently works.
- **PDF assembler temp dir collisions**: today multiple
  chunks could write to the same `assembly.temp_dir`. We
  add a per-chunk subdir
  `{temp_dir}/{batch_id}/` so concurrent assemblers
  cannot collide.
- **Memory**: with N=5 there are up to 4 fully-prepared
  chunks in flight. For a batch_size of 1000 and a
  per-doc staged size of 10 MB, that's up to 40 GB on
  disk + 4 × in-memory metadata. Documented in the how-to.
- **Slow-ops file collisions**: each chunk writes its own
  `slow-ops-{batch_id}.jsonl` so there's no collision (the
  filename embeds batch_id).
- **MetricsRecorder shared loggers**: multiple recorders
  attach their slow-op handlers to the same module-level
  `cmcourier.metrics.network` logger. The new per-handler
  batch_id filter (REQ-006..008) prevents crosstalk.

---

## 7. Dependencies

- **Hard**: 025 (thread-safety on S5 + tracking store),
  026 (system metrics — for the per-batch JSONL).
- **Unblocks**: POST-MVP §1 (heavy/light lanes — operates
  on one prepared chunk at a time, which 028 now produces
  as a first-class unit).

---

## 8. Estimate

~10 hours across four phases (see `tasks.md`).

# 063 — Streaming orchestrator (core, single-lane)

## Why

The current pipeline runs in **batched mode**: triggers are chunked
into `batch_size`-sized groups, and a `MultiBatchOrchestrator` runs
N=2 chunks in flight — chunk N uploads while chunk N+1 prepares.
That works, but for the production 20M-doc migration two structural
costs are visible:

1. **Memory peak** = `batch_size × batches_in_flight`. Today 100 × 2
   = ~200 docs in flight; with batch_size=1000 it was ~2000.
2. **The valley between chunks.** When chunk N's S5 finishes faster
   than chunk N+1's PREP, S5 waits idle. When PREP finishes faster
   than S5, PREP blocks on the in-flight slot.

The operator asked for the canonical producer-consumer alternative:
**a bucket (bounded buffer) of completed-PREP items, drained by S5
continuously.** PREP refills as the bucket drains. S5 never waits for
a whole chunk's PREP to complete — it starts as soon as the bucket has
its first item. Memory peak collapses to `bucket_size` (independent of
the total trigger count).

## What

### 1. Two pipeline modes side-by-side

```yaml
processing:
  mode: "batched"  | "streaming"     # default: "batched" (non-disruptive)
```

`"batched"` keeps every byte of behaviour from `MultiBatchOrchestrator`
intact — including `batches_in_flight`, the per-chunk recorder/AIMD
swap, and the existing CHUNKS tab. `"streaming"` activates a new
orchestrator.

### 2. The streaming orchestrator

A new `StreamingOrchestrator` lives next to `MultiBatchOrchestrator`,
constructed by the wiring layer when `processing.mode == "streaming"`.
It exposes the same `.run(...)` shape and returns a
`MultiBatchRunReport` for CLI compatibility — the report's `chunks`
field carries a single synthetic chunk (the whole run).

Internal model:

- **Bucket**: `queue.Queue[_StageItem](maxsize=bucket_size)`.
- **Producers**: `prep_workers` daemon threads. Each producer pulls
  one trigger from a thread-safe iterator over the trigger source,
  runs S1→S4 on it via new `StagedPipeline.streaming_prep_one(trigger,
  batch_id, recorder)`, and pushes any surviving item to the bucket.
  Domain failures (`RVABREPDeletedError`, `IDRViNotMappedError`, etc.)
  are persisted to `migration_log` by the existing per-stage helpers
  — no special-casing here.
- **Consumers**: `cmis.workers` daemon threads sized to the AIMD
  ceiling (`_pool_ceiling()`, spec 057). Each consumer does
  `bucket.get()`, runs S5 via the existing `_upload_one`, calls
  `bucket.task_done()`.
- **Shutdown coordination**: when the trigger iterator raises
  `StopIteration`, the producer that observed it pushes `N` poison
  pills (one per consumer) into the bucket. Consumers `break` on
  poison pill.
- **Single batch_id for the run**. `tracking_store.start_batch(0)` at
  the top, `complete_batch(...)` at the end. Every persisted row in
  `migration_log` carries this one id. (The `total_records=0` is
  accepted by SQLite — it is informative, not a constraint.)
- **Single global `MetricsRecorder`** for the run. AIMD reads
  `current_stage_p95_with_count("S5")` from that one recorder — no
  swap per-chunk. The `min_samples` guard (spec 061) handles the
  cold-start outlier.
- **Back-pressure is automatic**: when the bucket is full,
  `bucket.put()` blocks the producer. When the bucket is empty,
  `bucket.get()` blocks the consumer. Idle workers consume zero CPU.

### 3. Config

```python
class StreamingConfig(BaseModel):
    bucket_size: int = Field(default=100, ge=1)

class ProcessingConfig(BaseModel):
    mode: Literal["batched", "streaming"] = "batched"
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    # ...existing fields kept...
```

`processing.batches_in_flight` is ignored when `mode=="streaming"`
(documented in the field docstring).

### 4. Wiring

`cli/app.py` reads `config.processing.mode`. The orchestrator factory
returns either `MultiBatchOrchestrator(...)` or
`StreamingOrchestrator(...)`. Both honour the same `.run(...)`
signature so the rest of `app.py` is unchanged.

### 5. Resume semantics

In streaming mode, **resume = a new run**. Cross-batch idempotency
(spec 062 — `S1_SKIPPED` rows) provides traceability for docs
already uploaded in any prior run. `from_stage=N` and operator-named
`batch_id` are **rejected** with a clear ValueError when
`mode=="streaming"`. The batched path keeps full resume semantics.

## Out of scope

- **TUI BUCKET tab** (spec 064). The new orchestrator still updates the
  base `MetricsRecorder` (stages, slow ops, bandwidth), so the
  existing PREP/UPLOAD/CHUNKS tabs degrade-gracefully: PREP and
  UPLOAD show real stage data; the CHUNKS tab will show a single
  synthetic row "STREAMING (1 chunk for the whole run)". 064
  replaces it with a real BUCKET tab.
- **Heavy/light lanes in streaming** (spec 065). Streaming starts
  single-lane. The wiring constructs the `StreamingOrchestrator`
  **without** the `LaneController` even if
  `heavy_light_lanes.enabled: true` — with a clear startup WARN log
  pointing at spec 065.
- **TUI `chunks_state` snapshot**. `StreamingOrchestrator.chunks_snapshot()`
  returns a single-row list describing the streaming run as one
  conceptual chunk. Good enough for 063; the dedicated tab arrives in
  064.

## Acceptance criteria

- `processing.mode` defaults to `"batched"` and rejects unknown values
  (Pydantic Literal). `processing.streaming.bucket_size` defaults to
  100, rejects `< 1`.
- A `StreamingOrchestrator.run(...)` against a small fixture set
  uploads every doc successfully — end-to-end test via the existing
  `pipeline_harness`.
- The bucket caps memory: a test with `bucket_size=5` and 50 triggers
  asserts that the bucket's `qsize()` never exceeds 5 mid-run
  (probed via a hook).
- Shutdown is clean: every consumer thread joins, no zombies.
- `from_stage > 1` or non-None `batch_id` with `mode="streaming"`
  raises `ValueError`.
- Cross-batch idempotency (spec 062 / REBIRTH §10) works in streaming
  exactly as in batched — a re-run of the same triggers produces
  `S1_SKIPPED` rows.
- The wiring layer picks the right orchestrator and surfaces a clear
  WARN when `heavy_light_lanes.enabled: true` is combined with
  `mode="streaming"` (deferred to spec 065).
- Full unit + integration suite green; mypy + ruff clean.
- `CHANGELOG.md [0.65.0]`; `pyproject.toml` 0.64.0 → 0.65.0.

## Notes on test strategy

The `pipeline_harness` (`tests/integration/pipeline/conftest.py`) is
re-used: a new `build_streaming_pipeline(triggers_csv, **kwargs)`
factory wires the `StreamingOrchestrator`. The existing `respx`-based
CMIS stubbing works unchanged — the new orchestrator goes through the
same `CmisUploader`. Two key tests:

- `test_streaming_run_uploads_all_docs` — happy path, 6-doc fixture,
  every doc lands `S5_DONE`.
- `test_streaming_bucket_caps_memory` — `bucket_size=5`, instrument
  the queue to record peak `qsize()`, assert ≤ 5.
- `test_streaming_rejects_resume_args` — `from_stage=3` or
  `batch_id="x"` with `mode="streaming"` raises.
- `test_streaming_cross_batch_idempotency` — second run produces
  `S1_SKIPPED` rows just like the batched path (062).

The orchestrator itself gets unit tests for the iterator
thread-safety + poison-pill shutdown via a `_FakePipeline`-style
harness, mirroring the pattern used in
`tests/unit/orchestrators/test_multi_batch.py`.

# 056 — Configurable prep workers: parallelize S2/S3/S4

## Why

Watching the TUI on a staging run, the operator saw the assembly stage
(S4) crawling. It is — `_stage_s4` is a plain serial `for item in
items:` loop, one document at a time, on a single thread. So are
`_stage_s2` and `_stage_s3`. Meanwhile S5 (upload) has run on an
N-thread pool since spec 025.

The operator's ask, verbatim and deliberately scoped: *not* the full
S5 machinery (no AIMD auto-tune, no heavy/light lanes, no bandwidth
limiter) — just **a YAML knob for how many threads the prep can use**.

### What the prep actually is

The prep is five stages, chained serially over the item list:
**S0** (acquire the index) → **S1** (indexing) → **S2** (mapping) →
**S3** (metadata) → **S4** (assembly). They split into two groups:

- **S2 / S3 / S4 — homogeneous, parallel-safe.** All three have the
  identical shape: `for item in items:`, independent per-document
  work, then a tracking-store write. The tracking store is *already*
  thread-safe (it is the same store S5's N threads hammer today — an
  async writer queue + a reader lock). S3's `DocumentCacheService` and
  its `SqliteDocumentCache` adapter are *both* `threading.Lock`-guarded
  (verified). The `StageTimer` / `MetricsRecorder` are thread-safe
  ("per-stage metrics use a lock under the hood").
- **S0 / S1 — ordered, stateful.** `_stage_s0_s1` carries the
  cross-batch idempotency logic, the `resume_scope`, the
  `RVABREPDeletedError` filtering (051). Parallelizing it stops being
  "simple" and introduces real risk — and it is not the stage that
  hurts. **Out of scope.**

## What

### 1. `processing.prep_workers` — new YAML knob

Add `prep_workers: int = Field(default=1, ge=1)` to
`ProcessingConfig` (it already holds the processing-level concurrency
knob `batches_in_flight`). Default `1` → behaviour byte-identical to
today, so existing configs are unaffected and nobody is surprised.

### 2. `StagedPipeline` takes `prep_workers`

`__init__` gains `prep_workers: int = 1` (beside the existing
`workers`); stored as `self._prep_workers = max(1, int(prep_workers))`.
The wiring layer passes `config.processing.prep_workers`.

### 3. S2 / S3 / S4 run on a fixed-size pool

Extract each stage's per-item body into a helper
(`_s2_one` / `_s3_one` / `_s4_one`) that returns
`tuple[_StageItem | None, bool]` — `(survivor or None, was_a_counted_failure)`.
The `bool` preserves the current resume edge case: an item that
fails *but was already marked done in a prior run* is dropped from
survivors without incrementing `failed`.

A shared dispatch helper runs the bodies:

- `prep_workers == 1` → a plain serial list comprehension —
  **byte-identical to the current loop** (same pattern as
  `_stage_5_single` being "byte-identical to 025").
- `prep_workers > 1` → `ThreadPoolExecutor(max_workers=prep_workers)`
  with `pool.map(...)`. `pool.map` **preserves input order**, so
  `survivors` stays deterministic regardless of completion order — no
  ordering regression for the S5 stage that consumes it.

The per-item helpers already catch their own domain exceptions
(`IDRViNotMappedError`, `SourceFailedError`, `PDFAssemblyFailedError`,
…) inside the body — they return `(None, …)` rather than raising, so
`pool.map` never sees a domain failure. Unexpected exceptions
propagate exactly as they do in the serial loop today.

## Out of scope

- **S0 / S1** — ordered/stateful; explicitly excluded above.
- The S5 machinery — AIMD auto-tune, heavy/light lanes, bandwidth
  limiter, the `WorkerPoolStats` live panel. The operator asked for a
  plain thread count and nothing more.
- A TUI surface for prep workers — the PREP tab's existing per-stage
  progress is enough; this change just makes those numbers move
  faster. No new panel.
- `ProcessPoolExecutor` — S2/S3/S4 are I/O-bound (file copies, reading
  page images, metadata source I/O), so the GIL is released during the
  work and threads scale. No multiprocessing needed.

## Acceptance criteria

- `processing.prep_workers` parses, defaults to `1`, rejects `< 1`.
- With `prep_workers = 1`, S2/S3/S4 run the serial path — a test
  asserts the dispatch takes the non-pool branch (or, equivalently,
  that output is identical to the pre-056 loop on a fixed input).
- With `prep_workers = 4`, S2/S3/S4 process a multi-item batch
  correctly: every survivor present, `survivors` in **input order**,
  `failed` count correct including the already-done resume case — a
  test asserts each.
- A failing item (domain exception) is dropped from survivors and
  counted in `failed` exactly as in the serial path, under both
  `prep_workers = 1` and `> 1`.
- `StagedPipeline.__init__` accepts `prep_workers`; the wiring layer
  passes `config.processing.prep_workers`.
- Full unit + integration suite green; mypy + ruff clean.
- `CHANGELOG.md [0.59.0]`; `pyproject.toml` 0.58.0 → 0.59.0;
  `config-reference.yaml` documents `processing.prep_workers`.

## Notes on test strategy

S2/S3/S4 are exercised today by the `staged.py` pipeline tests with
fakes/stubs for the services. The 056 tests add a multi-item batch run
at `prep_workers = 4` and assert (a) correctness + input ordering,
(b) the failure/resume counting matches the serial path, and (c)
`prep_workers = 1` is unchanged. The thread-safety of the collaborators
(`tracking_store`, `DocumentCacheService`, `MetricsRecorder`) is
established — they are the same objects S5 already drives concurrently
— so the tests focus on the new dispatch logic, not on re-proving the
stores.

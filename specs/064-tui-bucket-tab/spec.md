# 064 — TUI BUCKET tab for streaming mode

## Why

063 ships the streaming orchestrator, but the existing TUI was
built around the batched model. In streaming mode the CHUNKS tab
shows a single synthetic row "STREAMING (1 chunk for the whole
run)" — useless for live observability of a 5000-doc run.

The operator needs to see, at a glance, what the *bucket* is
doing:

* current bucket level vs cap (back-pressure indicator)
* peak bucket level since run start
* PREP throughput (docs/s entering the bucket)
* S5 throughput (docs/s leaving the bucket)
* live worker counts (PREP busy/idle, S5 busy/idle)
* per-status totals (S5_DONE, S5_FAILED, S1_FILTERED, S1_SKIPPED)

## What

### 1. New BUCKET tab

A new tab inside the existing `TabbedContent` widget that becomes
**visible only when** the orchestrator is the streaming one
(detected via a new `mode: "batched" | "streaming"` field on the
`TUIDataProvider`). In batched mode the BUCKET tab is hidden and
CHUNKS tab is the operator's per-chunk view; in streaming mode
the CHUNKS tab is hidden and BUCKET tab takes over.

### 2. Data plumbed through `TUIDataProvider`

* `bucket_level: int` — current `qsize()` of the bucket, or 0
* `bucket_cap: int` — configured `bucket_size`
* `bucket_peak: int` — peak qsize since run start
* `prep_throughput: float` — docs/s averaged over the last 5s
* `upload_throughput: float` — same metric for S5
* `prep_busy: int` / `prep_idle: int` — producer thread state
  counts (best-effort, snapshot at refresh)
* `upload_busy: int` / `upload_idle: int` — from the existing
  `WorkerPoolStats`
* `s5_done`, `s5_failed`, `s1_filtered`, `s1_skipped` —
  cumulative tally read from the orchestrator's `chunks_snapshot()`
  (single synthetic row in streaming mode)

### 3. `StreamingOrchestrator` exposes the data

* `bucket_level()` — reads `_bucket.qsize()` (queue.Queue's qsize
  is approximate but good enough for a 1-second refresh)
* `peak_qsize` — already exists (063)
* `prep_pool_stats()` — `WorkerPoolStats`-shaped snapshot of
  the producer threads; for 064 we use an *atomic counter pair*
  (`prep_in_flight`) on the orchestrator (incremented before
  `streaming_prep_one`, decremented after).
* `chunks_snapshot()` — already exists; we read its single row
  for the cumulative counts.

### 4. Streaming-mode detection

The TUI binding layer in `cli/app.py` passes `mode=config.processing.mode`
to `TUIDataProvider`. The data provider exposes a `mode` property
the TUI tabs query at first render to decide visibility.

The existing UPLOAD, PREP, DETAIL tabs continue to work — they
already read the single global recorder.

## Out of scope

- A unified "live" tab that subsumes BUCKET + CHUNKS — both shapes
  coexist in this spec. A future change can unify them.
- Streaming-aware DETAIL filtering by `S5_DONE` etc. — DETAIL
  already shows every row from `migration_log`, which is correct.
- Heavy/light split in the BUCKET tab — deferred to 065 (the
  splitter doesn't exist in streaming yet).

## Acceptance criteria

- In batched mode (default), the TUI is byte-identical to 063 —
  CHUNKS tab present, BUCKET tab absent.
- In streaming mode, BUCKET tab is present with live readings:
  level vs cap, peak, PREP+UPLOAD throughput, worker counts,
  cumulative s5_done/s5_failed/s1_filtered/s1_skipped.
- A 100-trigger streaming run with `bucket_size=10` shows the
  level varying between 0 and 10 across the run.
- `StreamingOrchestrator.prep_pool_stats()` snapshot exposes
  `in_flight`, `total_workers`.
- All existing tests still pass; new TUI unit tests for the BUCKET
  tab's `_BucketTabBindings` model + DataProvider mode plumbing.
- mypy + ruff clean. CHANGELOG `[0.66.0]`; pyproject 0.65.0 → 0.66.0.

## Notes on test strategy

- `tests/unit/orchestrators/test_streaming.py` gains a
  `test_prep_pool_stats_tracks_in_flight` test.
- `tests/unit/tui/test_data_provider.py` (or equivalent) gets
  `test_mode_property_is_streaming_when_configured`.
- The Textual tab itself doesn't need a full render test; binding
  the fields is sufficient.

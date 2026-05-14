# 054 — UPLOAD-tab recorder wiring: finish the 042 split

## Why

On an N=2 staging run the operator reported the UPLOAD tab was dead:
bandwidth `0.00 MB/s`, peak `0.00 MB/s`, the UPLOAD SPEED sparkline
blank, SLOW OPS "(none yet)" — and the per-chunk timer was counting
from a point *long before* S5 started, as if it began at program
launch.

Two bugs, both in `src/cmcourier/tui/data_provider.py`, both
incomplete fallout from spec 042.

### Background — what 042 did

042 split the TUI's recorder binding in two:

- `recorder_provider` → `orchestrator.active_recorder()` — the
  **most-recently-started** chunk's recorder. When chunk N+1 enters
  PREP while chunk N is still uploading, this flips to N+1.
- `upload_recorder_provider` → `orchestrator.upload_recorder()` — the
  recorder of the chunk **actually inside S5**. Stays on N until N
  finishes.

Each `MetricsRecorder` owns a `_BandwidthHandler` and a
`_SlowOpHandler` that **filter log records by `batch_id`**
(`metrics.py` — `record.batch_id != self._batch_id` → dropped). So the
recorder of the chunk in PREP (N+1) receives **zero** `cmis_upload`
events — those all carry batch N's id and land only in N's recorder.

In `data_provider.py`, `self._metrics` follows `recorder_provider`
(PREP-aware) and `self._upload_metrics` follows
`upload_recorder_provider` (UPLOAD-bound).

### Bug 1 — bandwidth / peak / sparkline / slow ops read the PREP recorder

042 moved `_current_chunk_progress` to read `self._upload_metrics`,
but **four fields in `snapshot()` were left on `self._metrics`**:

- `bandwidth_current_mbps = self._metrics.bandwidth.current_mbps()`
- `bandwidth_peak_mbps = self._metrics.bandwidth.peak_mbps()`
- `bandwidth_series = self._metrics.bandwidth.series(60)`
- `slow_ops_all = self._metrics.aggregator_snapshot()`

During N's upload (with N+1 in PREP) `self._metrics` is N+1's
recorder — whose bandwidth sampler and slow-op aggregator never saw a
single byte of N's upload. Result: all four read empty/zero. The
existing `test_slow_ops_passes_through_aggregator` never caught it
because it builds the provider **without** `upload_recorder_provider`,
so `_metrics == _upload_metrics` and the two can't diverge.

### Bug 2 — the per-chunk timer measures from PREP start

`_current_chunk_progress` derives the active chunk's `elapsed_s` from
`prep_started_monotonic` — the moment the chunk began **preparing**,
not uploading. The UPLOAD tab renders that as "chunk elapsed", so for
chunk 0 it counts from roughly program launch. It also poisons
`current_chunk_avg_mbps = bytes_uploaded / elapsed_s` — dividing bytes
uploaded by a window that includes the entire PREP phase, so the
average speed reads far lower than reality.

`ChunkState` already carries `upload_started_monotonic` (stamped when
the chunk enters S5) and a frozen `upload_elapsed_s` (stamped at DONE)
— the provider just wasn't using them.

## What

### 1. Point the bandwidth + slow-ops fields at the UPLOAD recorder

In `snapshot()`, the four fields above read from `self._upload_metrics`
instead of `self._metrics`. `self._upload_metrics` already falls back
to `self._metrics` when no `upload_recorder_provider` is wired
(single-batch runs), so single-batch behaviour is unchanged.

### 2. Measure the per-chunk timer from S5 start

`_current_chunk_progress` resolves the active chunk's `elapsed_s` by
status:

- `UPLOAD` → `now − upload_started_monotonic` (live).
- `DONE` → the frozen `upload_elapsed_s`.
- `PREP` (or unknown) → `0.0` — S5 hasn't started, there is no upload
  elapsed yet. The `_chunk_timer_line` guard already suppresses the
  line when elapsed and bytes are both zero.
- No active chunk (single-batch) → unchanged: the global run elapsed.

`current_chunk_avg_mbps` then divides bytes uploaded by the *upload*
window, so it reports the real S5 throughput.

## Out of scope

- Re-tagging `network-*` / `system-*` log records with a real
  `batch_id` (the contextvar plumbing called out as out-of-scope in
  053) — unrelated; this spec is purely the in-memory TUI binding.
- Any change to `_BandwidthHandler` / `_SlowOpHandler` filtering — the
  per-batch filter is correct; the bug is which recorder the snapshot
  reads.
- The CHUNKS-tab RATE column (052) — it already reads per-chunk
  `upload_elapsed_s` and is unaffected.

## Acceptance criteria

- With a provider wired with **divergent** `recorder_provider` (a PREP
  recorder) and `upload_recorder_provider` (an UPLOAD recorder that
  has bandwidth + slow-op data), `snapshot()` returns non-zero
  `bandwidth_current_mbps`, `bandwidth_peak_mbps`, a non-empty
  `bandwidth_series`, and the UPLOAD recorder's slow ops in
  `slow_ops_all` — a test asserts each.
- For an active chunk in status `UPLOAD`, `current_chunk_elapsed_s`
  measures from `upload_started_monotonic`, not `prep_started_monotonic`
  — a test with both timestamps set asserts the gap is excluded.
- For an active chunk in status `DONE`, `current_chunk_elapsed_s`
  equals the frozen `upload_elapsed_s`.
- For an active chunk in status `PREP`, `current_chunk_elapsed_s` is
  `0.0`.
- Single-batch behaviour (no `upload_recorder_provider`) is unchanged
  — the existing data-provider tests stay green.
- Full unit + integration suite green; mypy + ruff clean.
- `CHANGELOG.md [0.57.0]`; `pyproject.toml` 0.56.0 → 0.57.0.

## Notes on test strategy

The gap that let both bugs ship is that no data-provider test wired
**divergent** PREP and UPLOAD recorders. The new tests build the
provider with two distinct `MetricsRecorder`s — one fed PREP-shaped
data, one fed UPLOAD-shaped data (bytes + a slow `cmis_upload`) — and
assert the snapshot reads UPLOAD-shaped fields from the UPLOAD one.
The per-chunk timer cases feed a `chunks_provider` returning a single
chunk dict with the status under test and both monotonic stamps set.

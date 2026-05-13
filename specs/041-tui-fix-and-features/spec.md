# 041 — TUI: log redirection fix + UPLOAD bytes/timer + CHUNKS expanded stats

## Why

Three operator-visible gaps in the live TUI surfaced during the
staging dry-run of 042/043:

1. **Logs trash the TUI frame.** Textual paints the terminal each
   ~250 ms, but every ``log.info()`` from the pipeline /
   adapters / uploader writes to stderr, breaking the frame
   mid-render. Operator can barely read the dashboard. Worst in
   batches >50 docs where each `stage_complete` line floods every
   refresh.

2. **UPLOAD tab is doc-counting, not byte-tracking.** The progress
   bar shows ``count / target`` in documents (e.g. ``5 / 10``).
   Operators correctly want **bytes** ("MB uploaded / MB
   remaining") because (a) docs vary 20× in size (1 KB PDF vs
   500 KB TIFF stack) and (b) bandwidth ceilings are byte-based.
   They also want a **chunk-scoped timer** — current display is
   global run elapsed; with multi-batch overlap (028) the
   per-chunk wall-clock is the metric that maps to "how long does
   one batch take?".

3. **CHUNKS tab is a status list, not a breakdown.** Today shows
   ``idx / batch_id / status / s5_done / s5_failed`` per chunk.
   Operators want the **full stage breakdown** per chunk
   (PREP done/failed/skipped/elapsed +
   UPLOAD done/failed/skipped/elapsed) plus aggregate totals
   (doc count, total bytes) so a glance at the tab answers
   "what did this run actually do?".

## What

### 1. Log redirection when TUI active

`observability/setup.py` gains a ``tui_active: bool`` flag
threaded from the CLI. When ``True``:

- The ``StreamHandler`` writing to ``stderr`` is **not added** to
  the root logger. Only the rotating ``FileHandler`` to
  ``observability.log_dir/app-YYYY-MM-DD.log`` remains.
- The TUI's own status updates write to its widgets, never to
  the terminal stream, so the frame stays clean.
- When ``--no-tui`` is set, behavior is identical to today.

This is a small, surgical fix — no changes to log formatting, no
new file structure, no rotation policy changes.

### 2. UPLOAD tab — bytes progress + chunk timer

The progress bar **stays in docs** (operator-intuitive), but the
line gains an MB ratio on the right and a new line shows per-chunk
average speed + elapsed + ETA:

```
  S5 UPLOAD     ████████░░░░░░░░░░░░░░░░░░░░     9 / 22 docs   127.3 MB / 312.8 MB
                chunk elapsed 00:02:14   avg 2.13 MB/s   est remaining 00:03:18
                p50 234.1 ms   p95 1,205.3 ms   p99 3,401.2 ms
```

To make this work the data provider gains five new snapshot fields:

- ``current_chunk_bytes_uploaded: int`` — cumulative bytes ACKed
  for the active chunk (from S5 ``stage_complete`` events).
- ``current_chunk_bytes_total: int`` — planned bytes for the
  chunk (sum of ``StagedFile.size_bytes`` post-S4).
- ``current_chunk_elapsed_s: float`` — wall-clock since the chunk
  entered S5 PREP (not since global run start).
- ``current_chunk_avg_mbps: float`` — ``bytes_uploaded /
  elapsed_s`` (MB/s). Distinct from the existing
  ``bandwidth_current_mbps`` which is a 1s rolling sample — this
  is the chunk-scoped average since start.
- ``current_chunk_eta_s: float | None`` — naive linear projection
  (``elapsed * (1 - progress) / progress``). Shown only when
  ``progress > 0.05`` to avoid wild guesses.

### 3. CHUNKS tab — full stage breakdown per chunk

Re-rendered as a wider table with per-chunk per-stage breakdown
plus an aggregate row at the bottom:

```
CHUNKS — pipeline csv-trigger-pipeline
──────────────────────────────────────────────────────────────────────────────
  idx  batch_id        docs    MB    PREP done/skip/fail (s)   UPLOAD done/skip/fail (s)
  ── ─ ────────────── ── ── ── ─── ──────────────────────── ────────────────────────────
  0    a1b2c3d4         95   42.1   95/0/0   (12.4s)         95/0/0   (8.9s)    ✓ DONE
  1    e5f6g7h8         88   38.7   88/0/0   (11.8s)         88/0/0   (8.2s)    ✓ DONE
  2    i9j0k1l2         91   40.3   91/0/0   (12.1s)         87/0/4   (9.4s)    ▲ UPLOAD
  3    m3n4o5p6         93   41.9    —        —                —        —       · QUEUED
  ── ─ ────────────── ── ── ── ─── ──────────────────────── ────────────────────────────
TOTAL  (4 chunks)      367  163.0   274/0/0  (36.3s)         270/0/4  (26.5s)
```

New per-chunk fields the data provider tracks:

- ``doc_count: int`` — total docs queued for this chunk.
- ``total_bytes: int`` — sum of staged file sizes (post-S4).
- ``prep_done / prep_skipped / prep_failed: int`` — S1..S4 outcomes.
- ``prep_elapsed_s: float`` — wall-clock for the PREP phase only.
- ``upload_skipped: int`` — S5 docs that the uploader skipped
  (idempotency hit, etc). The ``s5_done`` and ``s5_failed`` fields
  already exist.
- ``upload_elapsed_s: float`` — wall-clock for the S5 phase only.

The TOTAL row aggregates across all chunks for the operator-glance
"what did the whole run actually do?".

## Out of scope

- New metric collection in the pipeline itself. The data we need
  already lands in ``metrics.jsonl`` (each S1..S5 ``stage_complete``
  event has ``outcome``, ``duration_ms``, and ``size_bytes`` where
  applicable). The data provider just needs to aggregate it.
- Real-time bandwidth charts re-design (the sparkline stays).
- A keystroke to pause/resume / drill into a chunk — future spec.
- Persisting CHUNKS state across runs (it's live-only).
- Color theme changes. Same monochrome ASCII text.

## Acceptance criteria

- With TUI active, ``pipeline run`` shows a clean dashboard. No
  log lines leak into the terminal. The file
  ``sample/logs/app-YYYY-MM-DD.log`` still receives all events.
- With ``--no-tui``, behavior is identical to pre-041 (logs to
  stderr as before).
- UPLOAD tab shows MB progress + chunk timer + ETA when the chunk
  is past 5% complete.
- CHUNKS tab shows per-chunk doc_count + total_bytes + PREP
  breakdown + UPLOAD breakdown + TOTAL aggregate row.
- Existing TUI snapshot tests pass unchanged where they don't
  intersect the new fields.
- New snapshot tests cover both rendered tabs against synthetic
  ``TUISnapshot`` instances (no live pipeline required).
- mypy + ruff clean.
- CHANGELOG ``[0.44.0]`` entry.

## Notes on test strategy

Textual TUIs are notoriously hard to unit-test against. We won't
try to drive Textual itself in tests; we'll test the **pure render
functions** (``render_upload`` / ``render_chunks``) against
synthetic ``TUISnapshot`` instances. That mirrors how
``tests/unit/tui/test_*.py`` already works in this codebase.

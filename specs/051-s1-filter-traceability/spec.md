# 051 — S1 filter traceability (delete-coded RVABREP rows)

## Why

A `--total 2000` staging run showed S1 processing 1000 triggers per
chunk but only ~943 / ~954 docs reaching S2–S5. ~57 / ~46 docs per
chunk **vanished with zero traceability** — no count, no log, no TUI
surface. The operator's words: *"necesito mirar qué pasa, no
simplemente que desaparezca."*

Root cause, traced in the code:

`IndexingService._enrich_known_row` (`indexing.py:133`) — for a
`RvabrepRowTrigger` / `LocalScanTrigger`, if the RVABREP row carries a
delete code it does **`return []` silently**. No exception, no log, no
counter. In `_stage_s0_s1` the `for doc in docs:` loop simply doesn't
run for that trigger, so the doc is neither `done`, nor `skipped`
(cross-batch), nor `failed` — it is a **fourth outcome that the
pipeline has no name for**.

(The `ClientTrigger` path is inconsistent: `find_documents` *raises*
`RVABREPDeletedError`, which `_stage_s0_s1` currently treats as an S1
**failure** — also wrong: a doc deleted at source is not a pipeline
failure, it is correctly excluded.)

## What

Make "filtered at S1 — deleted at source" a **first-class outcome**:
counted, logged per-doc, and surfaced in the headless output and the
TUI.

### 1. `IndexingService` — stop swallowing the filter

`_enrich_known_row` raises `RVABREPDeletedError` for a delete-coded
row instead of `return []` — consistent with `find_documents` (the
`ClientTrigger` path already raises it). The "no docs at all" case
stays `return []` only for genuinely empty input, which can't happen
for a single known row.

### 2. `_stage_s0_s1` — a `filtered` tally, not a failure

`_stage_s0_s1` gains an `except RVABREPDeletedError` branch that:
- increments a `filtered` counter (NOT `timer.mark_failed()`),
- emits a structured INFO log per filtered doc: `txn_num` /
  `shortname` + `reason="deleted_at_source"`,
- `continue`s (the doc produces no item).

`RVABREPDeletedError` thus becomes a **filter**, not a failure, for
**both** trigger paths — a consistency fix. `RVABREPNotFoundError`
(a `ClientTrigger` pointing at a non-existent RVABREP row) stays an S1
**failure** — that genuinely is a data-integrity error, out of scope.

`_stage_s0_s1` returns `(items, skipped_cross_batch, filtered)`.

### 3. Thread the count through the report types

- `RunReport` gains `s1_filtered: int`.
- `StagedPipeline.run` + `prep_chunk` thread `s1_filtered` through
  (`prep_chunk` returns `(items, skipped, s1_done, s1_filtered,
  s2_failed, s3_failed, s4_failed)`).
- `MultiBatchRunReport` gains an `s1_filtered` aggregate property.
- `ChunkState` gains `prep_filtered: int = 0`; `_prep_one_chunk`
  populates it.

### 4. Surface it

- **Headless output** (`_emit_outcome` in `cli/app.py`): the final
  summary line gains `s1_filtered=N`.
- **TUI PREP tab** (`render_prep`): a line
  `FILTERED (S1, deleted at source)   N` under the stage table.
- **TUI CHUNKS tab** (`render_chunks`): the per-chunk `PREP d/s/f`
  column becomes `PREP d/s/f/x` (x = filtered); the TOTAL row too.
- **`data_provider`** (`_chunks_state_snapshot`): include
  `prep_filtered`.

## Out of scope

- **`DirectRvabrepTriggerStrategy.acquire`'s blank-row filter.** Blank
  shortname/system_id rows are dropped in S0 *before* becoming
  triggers (they're not in the S1 count of 1000), so they are not the
  operator's observed gap. `acquire` already emits a summary INFO log.
  Threading that count through is a separate, smaller follow-up.
- **Per-doc drill-down in the TUI** (the operator's issue #4 — select
  a chunk, list every file with name/size/status/reason). That is a
  larger feature on its own; 051 delivers the *counts + per-doc log*,
  not an interactive file list.
- **`RVABREPNotFoundError` reclassification.** Stays an S1 failure.
- The chunk MB/s + docs/s display (#2), the upload timer freeze (#3),
  and the bottleneck classifier — all separate items.

## Acceptance criteria

- `_enrich_known_row` raises `RVABREPDeletedError` for a delete-coded
  row; a unit test asserts it.
- `_stage_s0_s1` counts a delete-coded `RvabrepRowTrigger` as
  `filtered`, not `failed`, not `done` — and emits one INFO log with
  `txn_num` + `reason="deleted_at_source"`.
- For a chunk of N triggers where K rows are delete-coded:
  `s1_done + s1_filtered == N` (every trigger accounted for) — a test
  asserts this conservation.
- `RunReport.s1_filtered`, `MultiBatchRunReport.s1_filtered`,
  `ChunkState.prep_filtered` all carry the count.
- The headless summary line shows `s1_filtered=N`.
- `render_prep` shows the FILTERED line; `render_chunks` shows the
  `d/s/f/x` breakdown — tests on the renderers.
- Full unit + integration suite green; mypy + ruff clean.
- `CHANGELOG.md [0.54.0]`; `pyproject.toml` 0.53.0 → 0.54.0.

## Notes on test strategy

No live Alfresco needed — this is S1-level filtering, fully covered by
unit tests (`IndexingService`, `_stage_s0_s1`) + integration tests
(orchestrator threading the count, the renderers). The existing
`test_indexing.py` / `test_multi_batch.py` / `test_tabs.py` /
`test_chunks_tab.py` suites are the regression gate; new tests assert
the `filtered` outcome end to end.

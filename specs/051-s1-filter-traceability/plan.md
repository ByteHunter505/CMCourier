# 051 — Plan

Two phases (~2 h total).

## Phase 1 — Pipeline + TUI: the `filtered` outcome end to end (~1.5 h)

### Files

- `src/cmcourier/services/indexing.py`
  - `_enrich_known_row`: delete-coded row → `raise RVABREPDeletedError`
    (with `shortname` / `system_id` from the row) instead of
    `return []`. Update the docstring.
- `src/cmcourier/orchestrators/staged.py`
  - `_stage_s0_s1`: add `filtered = 0`; new `except RVABREPDeletedError`
    branch → `filtered += 1`, structured INFO log
    (`txn_num`/`shortname` + `reason="deleted_at_source"`), `continue`
    — does NOT call `timer.mark_failed()`. Return
    `(items, skipped_cross_batch, filtered)`.
  - `run`: unpack the new return; `RunReport` gains `s1_filtered`.
  - `prep_chunk`: return `(items, skipped, s1_done, s1_filtered,
    s2_failed, s3_failed, s4_failed)`.
  - `RunReport`: add `s1_filtered: int`.
- `src/cmcourier/orchestrators/multi_batch.py`
  - `MultiBatchRunReport`: add `s1_filtered` aggregate property.
  - `ChunkState`: add `prep_filtered: int = 0`.
  - `_prep_one_chunk`: unpack `s1_filtered` from `prep_chunk`; set
    `prep_filtered` in the chunk-state update; carry it into
    `_PreparedChunk`.
  - `_upload_one_chunk`: thread `s1_filtered` into the emitted
    `RunReport`.
  - `_PreparedChunk`: add `s1_filtered` field.
- `src/cmcourier/cli/app.py`
  - `_emit_outcome`: add `s1_filtered=N` to the headless summary line.
- `src/cmcourier/tui/data_provider.py`
  - `_chunks_state_snapshot`: include `prep_filtered` in the dict.
- `src/cmcourier/tui/prep_tab.py`
  - `render_prep`: add a `FILTERED (S1, deleted at source)` line.
    Pull the count from the snapshot — `TUISnapshot` gains
    `s1_filtered: int = 0`, populated by the provider from the
    active recorder / chunk state.
- `src/cmcourier/tui/chunks_tab.py`
  - `render_chunks`: `PREP d/s/f` → `PREP d/s/f/x`; TOTAL row too.
- `src/cmcourier/tui/data_provider.py`
  - `TUISnapshot.s1_filtered`; provider sums `prep_filtered` across
    chunk states (or reads the active recorder).

### Tests

- `tests/unit/services/test_indexing.py`:
  - `test_enrich_known_row_raises_on_delete_code` — delete-coded row
    → `RVABREPDeletedError`.
- `tests/integration/.../test_*` (staged pipeline):
  - `test_s0_s1_counts_deleted_row_as_filtered` — a delete-coded
    `RvabrepRowTrigger` increments `filtered`, not `failed`/`done`.
  - `test_s1_outcome_conservation` — `s1_done + s1_filtered == N`.
  - `test_s1_filtered_logged_with_reason` — caplog assertion on the
    INFO log + `reason="deleted_at_source"`.
- `tests/unit/orchestrators/test_multi_batch.py`:
  - `_FakePipeline.prep_chunk` updated to the 7-tuple return;
    `test_chunk_state_carries_prep_filtered`.
  - `MultiBatchRunReport.s1_filtered` aggregate test.
- `tests/unit/tui/test_tabs.py` + `test_chunks_tab.py`:
  - `render_prep` shows the FILTERED line; `render_chunks` shows
    `d/s/f/x`.

### Commit

```
feat(indexing,orchestrators,tui): first-class "filtered at S1" outcome (051 Phase 1)
```

## Phase 2 — CHANGELOG 0.54.0 + version bump + docs + FF (~30 min)

### Files

- `CHANGELOG.md` `[0.54.0]` — Fixed (delete-coded RVABREP rows
  silently dropped at S1), Changed (`RVABREPDeletedError` is a filter
  not a failure for both trigger paths; report types gain
  `s1_filtered`).
- `pyproject.toml` 0.53.0 → 0.54.0.
- `README.md` feature row tick.
- `docs/how-to/validation-checklist.md` — note the `s1_filtered`
  count in the run summary + what "filtered at S1" means.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.54.0
```

### Verify

Full unit + integration suite + ruff + mypy. No live Alfresco run —
051 is S1-level filtering, fully covered by the test suite. (Alfresco
may be wiped/in any state; 051 doesn't touch the CMIS path.)

### Commit

```
docs(051): CHANGELOG 0.54.0 + version bump + filter-traceability docs (051 Phase 2)
```

### FF to main.

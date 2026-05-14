# 052 — Plan

Three phases (~2.5 h total).

## Phase 1 — #3 frozen timer + #2 per-chunk rates (~45 min)

### Files

- `src/cmcourier/tui/data_provider.py`
  - `__init__`: `self._batch_completed_monotonic: float | None = None`.
  - `mark_batch_started`: reset `_batch_completed_monotonic = None`.
  - `mark_batch_complete`: stamp `_batch_completed_monotonic =
    time.monotonic()`.
  - `snapshot`: `end = self._batch_completed_monotonic or
    time.monotonic()`; `elapsed = end - _batch_started_monotonic`.
- `src/cmcourier/tui/chunks_tab.py`
  - `render_chunks`: per chunk + TOTAL row, compute and render
    `MB/s` + `docs/s` for the UPLOAD phase from `total_bytes`,
    `s5_done`, `upload_elapsed_s`. New `RATE` column (or extend the
    UPLOAD cell). Dash on `upload_elapsed_s <= 0`.

### Tests

- `tests/unit/tui/test_data_provider.py`:
  - `test_elapsed_frozen_after_complete` — two snapshots after
    `mark_batch_complete` return identical `elapsed_s`.
  - `test_elapsed_ticks_while_running` — still advances pre-complete.
- `tests/unit/tui/test_chunks_tab.py`:
  - `test_chunk_shows_upload_rate` — a chunk with bytes + elapsed
    shows `MB/s` and `docs/s`.
  - `test_zero_elapsed_renders_dash` — `upload_elapsed_s == 0` → dash,
    no `ZeroDivisionError`.

### Commit

```
feat(tui): freeze run timer on completion + per-chunk throughput (052 Phase 1)
```

## Phase 2 — #4 per-chunk drill-down (~1.25 h)

### Files

- `src/cmcourier/domain/ports.py`
  - `DocDetail` frozen dataclass: `txn_num`, `file_name`, `status`,
    `error_message`, `file_size_bytes`.
  - `ITrackingStore.list_docs_for_batch(batch_id) -> list[DocDetail]`
    (abstract).
- `src/cmcourier/adapters/tracking/sqlite.py`
  - `SQLiteTrackingStore.list_docs_for_batch` — `SELECT` per-doc rows
    for the batch under `_reader_lock`, map to `DocDetail`.
- `src/cmcourier/orchestrators/staged.py`
  - `StagedPipeline.tracking_store` — public property.
- `src/cmcourier/tui/data_provider.py`
  - `__init__`: `tracking_store` arg; `docs_for_batch(batch_id)`
    method delegating to the store.
- `src/cmcourier/cli/app.py`
  - `_run_with_optional_tui`: pass `tracking_store=pipeline.tracking_store`
    into `TUIDataProvider`.
- `src/cmcourier/tui/detail_tab.py` — new: `render_detail(chunk_meta,
  docs)` — header + per-doc table.
- `src/cmcourier/tui/app.py`
  - `compose`: add `TabPane("DETAIL", id="detail")` with a
    `Static#detail_body`.
  - `BINDINGS`: `[` → `select_prev_chunk`, `]` → `select_next_chunk`,
    `d` → `show_detail`.
  - `self._selected_chunk_idx: int | None = None`; the two actions
    move/clamp it against the live chunk count.
  - `_refresh_panels`: render the DETAIL pane — resolve the selected
    chunk from `snap.chunks_state`, call
    `self._provider.docs_for_batch(batch_id)`, pass to
    `render_detail`. No selection → a prompt.

### Tests

- `tests/integration/.../test_sqlite*` (or a new test):
  - `test_list_docs_for_batch_returns_per_doc_detail` — populate
    `migration_log`, assert the `DocDetail` list (status +
    `error_message` carried).
- `tests/unit/tui/test_data_provider.py`:
  - `test_docs_for_batch_delegates_to_store`.
- `tests/unit/tui/test_detail_tab.py` — new:
  - `render_detail` shows txn_num / file_name / size / status /
    reason; empty-docs and no-selection cases.
- `tests/unit/tui/` pilot test:
  - `test_detail_pane_selection` — `run_test()` pilot: `]` selects a
    chunk, the DETAIL pane renders its docs.

### Commit

```
feat(tracking,tui): per-chunk drill-down — DETAIL pane backed by the tracking store (052 Phase 2)
```

## Phase 3 — CHANGELOG 0.55.0 + version bump + docs + FF (~30 min)

### Files

- `CHANGELOG.md` `[0.55.0]` — Added (per-chunk MB/s + docs/s; DETAIL
  drill-down pane; `list_docs_for_batch`), Fixed (run timer froze
  never — now frozen on completion).
- `pyproject.toml` 0.54.0 → 0.55.0.
- `README.md` feature row tick.
- `docs/how-to/validation-checklist.md` — §F.1 (TUI): document the
  `[` / `]` chunk cursor + the DETAIL tab + the per-chunk rate
  columns.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.55.0
```

### Verify

Full unit + integration suite + ruff + mypy. No live Alfresco —
052 is dashboard + a tracking-store read; fully covered by the suite
+ a `run_test()` pilot.

### Commit

```
docs(052): CHANGELOG 0.55.0 + version bump + TUI drill-down docs (052 Phase 3)
```

### FF to main.

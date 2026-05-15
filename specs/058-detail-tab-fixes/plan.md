# 058 — Plan

Two phases (~1.5 h total).

## Phase 1 — Persist staged-file metadata + scrollable DETAIL + tests (~70 min)

### Files

- `src/cmcourier/domain/ports.py`
  - `ITrackingStore.record_staged_file_metadata(txn_num, batch_id, *,
    source_file_path, page_count, file_size_bytes) -> None` — new
    abstract method.

- `src/cmcourier/adapters/tracking/sqlite.py`
  - `SQLiteTrackingStore.record_staged_file_metadata` — `_enqueue` an
    `UPDATE migration_log SET source_file_path = ?, page_count = ?,
    file_size_bytes = ? WHERE rvabrep_txn_num = ? AND batch_id = ?`.

- `src/cmcourier/orchestrators/staged.py`
  - `_s4_one` — after `staged = self._assembler.assemble(...)` and the
    existing `mark_stage_pending` / `mark_stage_done` block, call
    `self._tracking_store.record_staged_file_metadata(
        txn, batch_id,
        source_file_path=str(staged.path),
        page_count=staged.page_count,
        file_size_bytes=staged.size_bytes,
    )`. Outside the `if not is_stage_done` guard — resume runs also
    backfill.

- `src/cmcourier/tui/app.py`
  - `from textual.containers import Container, VerticalScroll`.
  - The DETAIL `TabPane` yields
    `VerticalScroll(Static(id="detail_body"))` (no `Container`, no
    `classes="tab_body"` — see CSS below).
  - DEFAULT_CSS adds:
    ```
    #detail_body {
        height: auto;
        padding: 0 1;
    }
    ```
    The `Static.tab_body` rule stays for PREP / UPLOAD / CHUNKS.

- `src/cmcourier/tui/detail_tab.py`
  - `_MAX_ROWS = 2000` (was `100`). Header comment updated.

### Tests

- `tests/integration/adapters/test_sqlite_tracking_store.py`
  - `test_record_staged_file_metadata_updates_existing_row` — start a
    batch, mark S1-pending with `file_size_bytes=None`, call the new
    method with concrete values, flush, query the row directly via
    sqlite3, assert all three columns now hold the passed values.
  - `test_record_staged_file_metadata_idempotent` — call it twice with
    the same values; the second call is a no-op (row unchanged).

- `tests/integration/pipeline/test_staged_pipeline.py`
  - `test_s4_persists_staged_file_metadata_to_migration_log` — run the
    1-doc happy path, query the `migration_log` row, assert
    `file_size_bytes > 0`, `page_count > 0`, `source_file_path` ends
    with `.pdf`.

- `tests/unit/tui/test_detail_tab.py`
  - `test_renders_all_rows_when_under_max` — pass 1500 `DocDetail`s,
    assert every `txn_num` appears in the output and no `… more` hint.
  - The existing `test_truncates_large_chunk_with_cli_pointer` test
    updates: it passed 250 docs and expected truncation at 100. Either
    raise the count above 2000 to still hit truncation, or rewrite it
    to assert "no truncation under 2000". Pick the simpler one — make
    it assert that 250 docs all render with no truncation hint (the
    operator's actual case).

- `tests/unit/tui/test_app.py` (or wherever the TUI app is tested)
  - `test_detail_pane_is_scrollable` — `async with app.run_test() as
    pilot`: `detail_body = app.query_one("#detail_body")`; assert
    `isinstance(detail_body.parent, VerticalScroll)`. If
    `test_app.py` does not exist yet, add it.

### Verify

Full unit + integration suite + ruff + mypy.

### Commit

```
fix(tui): persist S4 staged-file metadata + scrollable DETAIL pane (058 Phase 1)
```

## Phase 2 — CHANGELOG 0.61.0 + version bump + README + FF (~20 min)

### Files

- `CHANGELOG.md` `[0.61.0]` — Fixed entries for both bugs.
- `pyproject.toml` 0.60.0 → 0.61.0.
- `README.md` feature row tick.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.61.0
```

### Commit

```
docs(058): CHANGELOG 0.61.0 + version bump (058 Phase 2)
```

### FF to main.

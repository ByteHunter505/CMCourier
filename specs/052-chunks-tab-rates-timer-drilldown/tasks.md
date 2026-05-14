# 052 — Tasks

## Phase 1 — #3 frozen timer + #2 per-chunk rates

- [ ] 1.1 `data_provider.py`: `_batch_completed_monotonic`;
      `mark_batch_started` resets it; `mark_batch_complete` stamps it;
      `snapshot` uses the frozen end time.
- [ ] 1.2 `chunks_tab.py` `render_chunks`: per-chunk + TOTAL `MB/s` +
      `docs/s` for the UPLOAD phase; dash on `upload_elapsed_s <= 0`.
- [ ] 1.3 Tests: `test_data_provider.py` elapsed-frozen +
      elapsed-ticks-while-running.
- [ ] 1.4 Tests: `test_chunks_tab.py` upload-rate + zero-elapsed dash.
- [ ] 1.5 mypy + ruff clean on touched files.
- [ ] 1.6 Commit
      `feat(tui): freeze run timer on completion + per-chunk throughput (052 Phase 1)`.

## Phase 2 — #4 per-chunk drill-down

- [ ] 2.1 `ports.py`: `DocDetail` dataclass +
      `ITrackingStore.list_docs_for_batch` abstract method.
- [ ] 2.2 `sqlite.py`: `SQLiteTrackingStore.list_docs_for_batch`
      (SELECT per-doc rows under `_reader_lock`).
- [ ] 2.3 `staged.py`: `StagedPipeline.tracking_store` public
      property.
- [ ] 2.4 `data_provider.py`: `tracking_store` arg +
      `docs_for_batch(batch_id)` method.
- [ ] 2.5 `cli/app.py`: wire `tracking_store=` into `TUIDataProvider`.
- [ ] 2.6 `tui/detail_tab.py` (new): `render_detail` — header +
      per-doc table.
- [ ] 2.7 `tui/app.py`: `DETAIL` TabPane; `[` / `]` / `d` bindings;
      `_selected_chunk_idx`; `_refresh_panels` renders DETAIL.
- [ ] 2.8 Tests: `list_docs_for_batch` integration test.
- [ ] 2.9 Tests: `docs_for_batch` delegation;
      `test_detail_tab.py` renderer; `run_test()` pilot for
      selection + DETAIL pane.
- [ ] 2.10 Full unit + integration suite green; mypy + ruff clean.
- [ ] 2.11 Commit
      `feat(tracking,tui): per-chunk drill-down — DETAIL pane backed by the tracking store (052 Phase 2)`.

## Phase 3 — CHANGELOG 0.55.0 + version bump + docs + FF

- [ ] 3.1 `CHANGELOG.md [0.55.0]` — Added / Fixed.
- [ ] 3.2 `pyproject.toml` 0.54.0 → 0.55.0.
- [ ] 3.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 3.4 `cmcourier --version` reports 0.55.0.
- [ ] 3.5 `README.md` feature row tick.
- [ ] 3.6 `docs/how-to/validation-checklist.md` §F.1 — `[` / `]`
      cursor + DETAIL tab + rate columns.
- [ ] 3.7 Full suite + ruff + mypy clean.
- [ ] 3.8 Commit
      `docs(052): CHANGELOG 0.55.0 + version bump + TUI drill-down docs (052 Phase 3)`.
- [ ] 3.9 FF to main.

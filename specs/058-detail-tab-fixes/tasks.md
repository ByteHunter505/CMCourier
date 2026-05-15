# 058 — Tasks

## Phase 1 — Persist staged-file metadata + scrollable DETAIL + tests

- [ ] 1.1 `domain/ports.py`: `ITrackingStore.record_staged_file_metadata`
      abstract method.
- [ ] 1.2 `adapters/tracking/sqlite.py`: `SQLiteTrackingStore`
      implementation — UPDATE via the async writer.
- [ ] 1.3 `orchestrators/staged.py`: `_s4_one` calls the new method
      after successful assemble — outside the `is_stage_done` guard so
      resume runs also backfill.
- [ ] 1.4 `tui/app.py`: DETAIL TabPane uses `VerticalScroll`; CSS adds
      `#detail_body { height: auto; padding: 0 1 }`.
- [ ] 1.5 `tui/detail_tab.py`: `_MAX_ROWS = 2000`.
- [ ] 1.6 Tests: `test_sqlite_tracking_store` — UPDATE semantics +
      idempotence.
- [ ] 1.7 Tests: `test_staged_pipeline` — pipeline run leaves
      `file_size_bytes > 0` on `migration_log`.
- [ ] 1.8 Tests: `test_detail_tab` — 1500 rows render in full, no
      truncation hint.
- [ ] 1.9 Tests: `test_app` — `#detail_body.parent` is a
      `VerticalScroll`.
- [ ] 1.10 Full unit + integration suite green; mypy + ruff clean.
- [ ] 1.11 Commit
      `fix(tui): persist S4 staged-file metadata + scrollable DETAIL pane (058 Phase 1)`.

## Phase 2 — CHANGELOG 0.61.0 + version bump + README + FF

- [ ] 2.1 `CHANGELOG.md [0.61.0]` — Fixed.
- [ ] 2.2 `pyproject.toml` 0.60.0 → 0.61.0.
- [ ] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 2.4 `cmcourier --version` reports 0.61.0.
- [ ] 2.5 `README.md` feature row tick.
- [ ] 2.6 Full suite + ruff + mypy clean.
- [ ] 2.7 Commit
      `docs(058): CHANGELOG 0.61.0 + version bump (058 Phase 2)`.
- [ ] 2.8 FF to main.

# 041 — Tasks

## Phase 1: log redirection when TUI is active

- [ ] 1.1 `configure_logging(..., tui_active: bool = False)` —
      skip stderr StreamHandler when True.
- [ ] 1.2 `_tui_runner.py` calls `configure_logging(tui_active=True)`
      before launching Textual.
- [ ] 1.3 Each CLI command keeps the existing
      `configure_logging(tui_active=False)` call for the
      `--no-tui` branch.
- [ ] 1.4 Unit tests: handler set under both modes.
- [ ] 1.5 Integration test: TUI run stderr is empty.
- [ ] 1.6 mypy + ruff clean.
- [ ] 1.7 Commit
      `fix(observability,tui): silence stderr logging while TUI is active (041 Phase 1)`.

## Phase 2: UPLOAD tab MB progress + chunk timer

- [ ] 2.1 Add 4 new fields to `TUISnapshot`:
      current_chunk_bytes_uploaded / _bytes_total /
      _elapsed_s / _eta_s.
- [ ] 2.2 `TUIDataProvider` tracks them per S4/S5
      ``stage_complete`` event (size_bytes) and a
      per-chunk ``prep_started_at``.
- [ ] 2.3 `render_upload` swaps the progress bar from
      doc-count to bytes; keeps the docs count as a second line.
- [ ] 2.4 Add "chunk elapsed / est remaining" line.
- [ ] 2.5 Snapshot tests: 0% / 40% / 100% renders.
- [ ] 2.6 mypy + ruff clean.
- [ ] 2.7 Commit
      `feat(tui,observability): UPLOAD tab MB progress + chunk timer (041 Phase 2)`.

## Phase 3: CHUNKS tab expanded breakdown

- [ ] 3.1 Extend per-chunk entries in
      ``TUIDataProvider.chunks_state`` with doc_count,
      total_bytes, prep_done/skipped/failed,
      prep_elapsed_s, upload_skipped, upload_elapsed_s.
- [ ] 3.2 `render_chunks` rewritten as wider table with TOTAL
      aggregate row.
- [ ] 3.3 Column widths tuned for 80-col terminals.
- [ ] 3.4 Empty/QUEUED chunks render as ``—``.
- [ ] 3.5 Snapshot tests: multi-stage chunks +
      all-DONE + empty-state.
- [ ] 3.6 mypy + ruff clean.
- [ ] 3.7 Commit
      `feat(tui,observability): CHUNKS tab expanded per-stage breakdown + totals (041 Phase 3)`.

## Phase 4: docs + CHANGELOG 0.44.0 + version bump + FF

- [ ] 4.1 `docs/how-to/local-staging-simulation.md` Step 6 —
      mention new TUI fields.
- [ ] 4.2 `CHANGELOG.md [0.44.0]` entry.
- [ ] 4.3 `README.md` feature row tick.
- [ ] 4.4 `pyproject.toml` 0.43.0 → 0.44.0.
- [ ] 4.5 Smoke: `csv-trigger-pipeline run --total 10` (TUI on)
      — no stderr leak, MB shown, CHUNKS table populated.
- [ ] 4.6 Full suite + mypy + ruff clean.
- [ ] 4.7 Commit
      `docs(041): TUI runbook + CHANGELOG 0.44.0 + version bump (041 Phase 4)`.
- [ ] 4.8 FF to main.

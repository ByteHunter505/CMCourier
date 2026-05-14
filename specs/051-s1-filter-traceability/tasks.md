# 051 — Tasks

## Phase 1 — The `filtered` outcome end to end

- [ ] 1.1 `indexing.py` `_enrich_known_row`: delete-coded row →
      `raise RVABREPDeletedError` (not `return []`).
- [ ] 1.2 `staged.py` `_stage_s0_s1`: `filtered` counter +
      `except RVABREPDeletedError` branch (INFO log w/ txn_num +
      `reason="deleted_at_source"`, no `mark_failed`); return
      `(items, skipped, filtered)`.
- [ ] 1.3 `staged.py` `RunReport`: add `s1_filtered`; `run` +
      `prep_chunk` thread it through (prep_chunk → 7-tuple).
- [ ] 1.4 `multi_batch.py`: `MultiBatchRunReport.s1_filtered`
      aggregate; `ChunkState.prep_filtered`; `_PreparedChunk`
      field; `_prep_one_chunk` + `_upload_one_chunk` thread it.
- [ ] 1.5 `cli/app.py` `_emit_outcome`: `s1_filtered=N` in the
      headless summary line.
- [ ] 1.6 `data_provider.py`: `TUISnapshot.s1_filtered`;
      `_chunks_state_snapshot` includes `prep_filtered`; provider
      sums it into the snapshot.
- [ ] 1.7 `prep_tab.py` `render_prep`: FILTERED line.
- [ ] 1.8 `chunks_tab.py` `render_chunks`: `PREP d/s/f` →
      `d/s/f/x` + TOTAL row.
- [ ] 1.9 Unit test: `_enrich_known_row` raises on delete code.
- [ ] 1.10 Integration tests: `_stage_s0_s1` counts filtered (not
      failed/done); `s1_done + s1_filtered == N` conservation;
      INFO log w/ reason.
- [ ] 1.11 `test_multi_batch.py`: update `_FakePipeline.prep_chunk`
      7-tuple; `prep_filtered` in chunk state; aggregate property.
- [ ] 1.12 TUI renderer tests: FILTERED line + `d/s/f/x`.
- [ ] 1.13 Full unit + integration suite green; mypy + ruff clean.
- [ ] 1.14 Commit
      `feat(indexing,orchestrators,tui): first-class "filtered at S1" outcome (051 Phase 1)`.

## Phase 2 — CHANGELOG 0.54.0 + version bump + docs + FF

- [ ] 2.1 `CHANGELOG.md [0.54.0]` — Fixed / Changed.
- [ ] 2.2 `pyproject.toml` 0.53.0 → 0.54.0.
- [ ] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 2.4 `cmcourier --version` reports 0.54.0.
- [ ] 2.5 `README.md` feature row tick.
- [ ] 2.6 `docs/how-to/validation-checklist.md` — `s1_filtered` note.
- [ ] 2.7 Full suite + ruff + mypy clean.
- [ ] 2.8 Commit
      `docs(051): CHANGELOG 0.54.0 + version bump + filter-traceability docs (051 Phase 2)`.
- [ ] 2.9 FF to main.

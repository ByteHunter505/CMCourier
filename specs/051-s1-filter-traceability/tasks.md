# 051 — Tasks

## Fase 1 — El outcome `filtered` end to end

- [ ] 1.1 `indexing.py` `_enrich_known_row`: fila con código de
      borrado → `raise RVABREPDeletedError` (no `return []`).
- [ ] 1.2 `staged.py` `_stage_s0_s1`: contador `filtered` +
      rama `except RVABREPDeletedError` (log INFO con txn_num +
      `reason="deleted_at_source"`, sin `mark_failed`); devolver
      `(items, skipped, filtered)`.
- [ ] 1.3 `staged.py` `RunReport`: agregar `s1_filtered`; `run` +
      `prep_chunk` lo pasan (prep_chunk → 7-tupla).
- [ ] 1.4 `multi_batch.py`: agregado
      `MultiBatchRunReport.s1_filtered`; `ChunkState.prep_filtered`;
      campo `_PreparedChunk`; `_prep_one_chunk` +
      `_upload_one_chunk` lo pasan.
- [ ] 1.5 `cli/app.py` `_emit_outcome`: `s1_filtered=N` en la
      línea de resumen headless.
- [ ] 1.6 `data_provider.py`: `TUISnapshot.s1_filtered`;
      `_chunks_state_snapshot` incluye `prep_filtered`; el
      provider lo suma al snapshot.
- [ ] 1.7 `prep_tab.py` `render_prep`: línea FILTERED.
- [ ] 1.8 `chunks_tab.py` `render_chunks`: `PREP d/s/f` →
      `d/s/f/x` + fila TOTAL.
- [ ] 1.9 Test unitario: `_enrich_known_row` levanta en código
      de borrado.
- [ ] 1.10 Tests de integración: `_stage_s0_s1` cuenta filtered
      (no failed/done); conservación
      `s1_done + s1_filtered == N`; log INFO con reason.
- [ ] 1.11 `test_multi_batch.py`: actualizar
      `_FakePipeline.prep_chunk` a 7-tupla; `prep_filtered` en
      chunk state; propiedad agregada.
- [ ] 1.12 Tests del renderer de TUI: línea FILTERED + `d/s/f/x`.
- [ ] 1.13 Suite completa unit + integration verde; mypy + ruff
      limpios.
- [ ] 1.14 Commit
      `feat(indexing,orchestrators,tui): first-class "filtered at S1" outcome (051 Phase 1)`.

## Fase 2 — CHANGELOG 0.54.0 + bump de versión + docs + FF

- [ ] 2.1 `CHANGELOG.md [0.54.0]` — Fixed / Changed.
- [ ] 2.2 `pyproject.toml` 0.53.0 → 0.54.0.
- [ ] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 2.4 `cmcourier --version` reporta 0.54.0.
- [ ] 2.5 Tick en fila de features de `README.md`.
- [ ] 2.6 `docs/how-to/validation-checklist.md` — nota de
      `s1_filtered`.
- [ ] 2.7 Suite completa + ruff + mypy limpios.
- [ ] 2.8 Commit
      `docs(051): CHANGELOG 0.54.0 + version bump + filter-traceability docs (051 Phase 2)`.
- [ ] 2.9 FF a main.

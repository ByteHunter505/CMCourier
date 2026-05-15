# 052 — Tasks

## Fase 1 — #3 timer frozen + #2 rates por-chunk

- [ ] 1.1 `data_provider.py`: `_batch_completed_monotonic`;
      `mark_batch_started` lo resetea; `mark_batch_complete` lo
      stampea; `snapshot` usa el end time frozen.
- [ ] 1.2 `chunks_tab.py` `render_chunks`: `MB/s` + `docs/s`
      por-chunk + TOTAL para la fase UPLOAD; guión cuando
      `upload_elapsed_s <= 0`.
- [ ] 1.3 Tests: `test_data_provider.py` elapsed-frozen +
      elapsed-ticks-mientras-corriendo.
- [ ] 1.4 Tests: `test_chunks_tab.py` upload-rate + guión en
      zero-elapsed.
- [ ] 1.5 mypy + ruff limpios en archivos tocados.
- [ ] 1.6 Commit
      `feat(tui): freeze run timer on completion + per-chunk throughput (052 Phase 1)`.

## Fase 2 — #4 drill-down por-chunk

- [ ] 2.1 `ports.py`: dataclass `DocDetail` + método abstracto
      `ITrackingStore.list_docs_for_batch`.
- [ ] 2.2 `sqlite.py`: `SQLiteTrackingStore.list_docs_for_batch`
      (SELECT filas per-doc bajo `_reader_lock`).
- [ ] 2.3 `staged.py`: propiedad pública
      `StagedPipeline.tracking_store`.
- [ ] 2.4 `data_provider.py`: arg `tracking_store` + método
      `docs_for_batch(batch_id)`.
- [ ] 2.5 `cli/app.py`: wirear `tracking_store=` al `TUIDataProvider`.
- [ ] 2.6 `tui/detail_tab.py` (nuevo): `render_detail` — header
      + tabla per-doc.
- [ ] 2.7 `tui/app.py`: TabPane `DETAIL`; bindings `[` / `]` /
      `d`; `_selected_chunk_idx`; `_refresh_panels` renderiza
      DETAIL.
- [ ] 2.8 Tests: test de integración de `list_docs_for_batch`.
- [ ] 2.9 Tests: delegación de `docs_for_batch`;
      renderer `test_detail_tab.py`; piloto `run_test()` para
      selección + panel DETAIL.
- [ ] 2.10 Suite completa unit + integration verde; mypy + ruff
      limpios.
- [ ] 2.11 Commit
      `feat(tracking,tui): per-chunk drill-down — DETAIL pane backed by the tracking store (052 Phase 2)`.

## Fase 3 — CHANGELOG 0.55.0 + bump de versión + docs + FF

- [ ] 3.1 `CHANGELOG.md [0.55.0]` — Added / Fixed.
- [ ] 3.2 `pyproject.toml` 0.54.0 → 0.55.0.
- [ ] 3.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 3.4 `cmcourier --version` reporta 0.55.0.
- [ ] 3.5 Tick en fila de features de `README.md`.
- [ ] 3.6 `docs/how-to/validation-checklist.md` §F.1 — cursor
      `[` / `]` + tab DETAIL + columnas de rate.
- [ ] 3.7 Suite completa + ruff + mypy limpios.
- [ ] 3.8 Commit
      `docs(052): CHANGELOG 0.55.0 + version bump + TUI drill-down docs (052 Phase 3)`.
- [ ] 3.9 FF a main.

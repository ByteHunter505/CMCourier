# 058 — Tasks

## Fase 1 — Persistir metadata de staged-file + DETAIL scrolleable + tests

- [x] 1.1 `domain/ports.py`: método abstracto
      `ITrackingStore.record_staged_file_metadata` (contrato
      de `test_ports.py` actualizado).
- [x] 1.2 `adapters/tracking/sqlite.py`: implementación de
      `SQLiteTrackingStore` — UPDATE vía el async writer.
- [x] 1.3 `orchestrators/staged.py`: `_s4_one` llama al
      método nuevo después de un assemble exitoso — afuera
      del guard `is_stage_done` así los runs de resume
      también back-fillean.
- [x] 1.4 `tui/app.py`: el TabPane DETAIL usa
      `VerticalScroll`; el CSS agrega
      `#detail_body { height: auto; padding: 0 1 }`.
- [x] 1.5 `tui/detail_tab.py`: `_MAX_ROWS = 2000`.
- [x] 1.6 Tests: `test_sqlite_tracking_store` — semántica del
      UPDATE + idempotencia.
- [x] 1.7 Tests: `test_staged_pipeline` — un run de pipeline
      deja `file_size_bytes > 0` (y `page_count`,
      `source_file_path`) en `migration_log`.
- [x] 1.8 Tests: `test_detail_tab` — 1500 filas renderizan en
      su totalidad, sin hint de truncamiento; 2100 filas
      todavía pegan el puntero CLI.
- [x] 1.9 Tests: `test_app` — `#detail_body.parent` es un
      `VerticalScroll`.
- [x] 1.10 Suite completa unit + integration verde (1224
      pasados); mypy + ruff limpios.
- [x] 1.11 Commit
      `fix(tui): persist S4 staged-file metadata + scrollable DETAIL pane (058 Phase 1)`.

## Fase 2 — CHANGELOG 0.61.0 + bump de versión + README + FF

- [x] 2.1 `CHANGELOG.md [0.61.0]` — Fixed.
- [x] 2.2 `pyproject.toml` 0.60.0 → 0.61.0.
- [x] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [x] 2.4 `cmcourier --version` reporta 0.61.0.
- [x] 2.5 Tick en fila de features de `README.md`.
- [x] 2.6 Suite completa + ruff + mypy limpios (verificado en
      Fase 1, 1224 pasados; la Fase 2 no toca código — solo
      docs/CHANGELOG/version).
- [x] 2.7 Commit
      `docs(058): CHANGELOG 0.61.0 + version bump (058 Phase 2)`.
- [ ] 2.8 FF a main.

# 041 — Tasks

## Fase 1: redirección de logs cuando la TUI está activa

- [ ] 1.1 `configure_logging(..., tui_active: bool = False)` —
      omitir el StreamHandler de stderr cuando es True.
- [ ] 1.2 `_tui_runner.py` llama `configure_logging(tui_active=True)`
      antes de lanzar Textual.
- [ ] 1.3 Cada comando de la CLI mantiene la llamada existente
      `configure_logging(tui_active=False)` para la rama
      `--no-tui`.
- [ ] 1.4 Tests unitarios: set de handlers bajo ambos modos.
- [ ] 1.5 Test de integración: stderr del run con TUI está vacío.
- [ ] 1.6 mypy + ruff limpios.
- [ ] 1.7 Commit
      `fix(observability,tui): silence stderr logging while TUI is active (041 Phase 1)`.

## Fase 2: progreso de MB + timer del chunk en el tab UPLOAD

- [ ] 2.1 Agregar 4 campos nuevos a `TUISnapshot`:
      current_chunk_bytes_uploaded / _bytes_total /
      _elapsed_s / _eta_s.
- [ ] 2.2 `TUIDataProvider` los trackea por cada evento
      ``stage_complete`` de S4/S5 (size_bytes) y un
      ``prep_started_at`` por-chunk.
- [ ] 2.3 `render_upload` cambia la barra de progreso de
      cantidad de docs a bytes; mantiene el conteo de docs como
      segunda línea.
- [ ] 2.4 Agregar línea "chunk elapsed / est remaining".
- [ ] 2.5 Tests de snapshot: renders al 0% / 40% / 100%.
- [ ] 2.6 mypy + ruff limpios.
- [ ] 2.7 Commit
      `feat(tui,observability): UPLOAD tab MB progress + chunk timer (041 Phase 2)`.

## Fase 3: desglose expandido del tab CHUNKS

- [ ] 3.1 Extender entradas por-chunk en
      ``TUIDataProvider.chunks_state`` con doc_count,
      total_bytes, prep_done/skipped/failed,
      prep_elapsed_s, upload_skipped, upload_elapsed_s.
- [ ] 3.2 `render_chunks` reescrita como tabla más ancha con fila
      TOTAL agregada.
- [ ] 3.3 Anchos de columna ajustados para terminales de 80 cols.
- [ ] 3.4 Chunks vacíos/QUEUED renderizan como ``—``.
- [ ] 3.5 Tests de snapshot: chunks multi-stage +
      all-DONE + estado vacío.
- [ ] 3.6 mypy + ruff limpios.
- [ ] 3.7 Commit
      `feat(tui,observability): CHUNKS tab expanded per-stage breakdown + totals (041 Phase 3)`.

## Fase 4: docs + CHANGELOG 0.44.0 + bump de versión + FF

- [ ] 4.1 `docs/how-to/local-staging-simulation.md` Step 6 —
      mencionar los nuevos campos de la TUI.
- [ ] 4.2 Entrada `CHANGELOG.md [0.44.0]`.
- [ ] 4.3 Tick en fila de features de `README.md`.
- [ ] 4.4 `pyproject.toml` 0.43.0 → 0.44.0.
- [ ] 4.5 Smoke: `csv-trigger-pipeline run --total 10` (TUI on)
      — sin filtración de stderr, MB mostrados, tabla CHUNKS
      poblada.
- [ ] 4.6 Suite completa + mypy + ruff limpios.
- [ ] 4.7 Commit
      `docs(041): TUI runbook + CHANGELOG 0.44.0 + version bump (041 Phase 4)`.
- [ ] 4.8 FF a main.

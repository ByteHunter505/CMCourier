# 042 — Tasks

## Fase 1 — filtro batch_id del handler de bandwidth

- [ ] 1.1 `_BandwidthHandler.__init__(sampler, *, batch_id)` — guardar
      `batch_id` en el handler.
- [ ] 1.2 `_BandwidthHandler.emit` — early-return cuando
      `record.batch_id != self._batch_id`.
- [ ] 1.3 `MetricsRecorder.start_batch` — pasar `batch_id` a
      `_BandwidthHandler(...)`.
- [ ] 1.4 Test unitario: emitir batch_id que no matchea, cumulative_bytes
      sin cambios.
- [ ] 1.5 Test unitario: emitir batch_id que matchea, cumulative_bytes
      avanza.
- [ ] 1.6 mypy + ruff limpios.
- [ ] 1.7 Commit
      `fix(observability): per-batch bandwidth handler filter (042 Phase 1)`.

## Fase 2 — contadores S5 en vivo propagados a la fila CHUNKS

- [ ] 2.1 `MetricsRecorder` — agregar contadores `_s5_done`, `_s5_failed`
      + sus `_lock`s + `record_upload_done()`,
      `record_upload_failed()`, `upload_done_count()`,
      `upload_failed_count()`.
- [ ] 2.2 `_stage_5_single` — en `outcome == "done"` /
      `"failed"`, llamar al método `rec.record_upload_*` que
      corresponde.
- [ ] 2.3 `_stage_5_dual` — mismo wiring que 2.2.
- [ ] 2.4 `data_provider._chunks_state_snapshot` — cuando
      `status == "UPLOAD"`, reemplazar `s5_done` / `s5_failed` con
      los valores en vivo del upload-active recorder.
- [ ] 2.5 Test unitario: thread safety de `upload_done_count`.
- [ ] 2.6 Test unitario: `render_chunks` muestra `s5_done` en vivo
      para una fila en UPLOAD impulsada por un snapshot sintético.
- [ ] 2.7 mypy + ruff limpios.
- [ ] 2.8 Commit
      `fix(tui,observability): live s5_done/failed in CHUNKS during UPLOAD (042 Phase 2)`.

## Fase 3 — slot separado de active recorder para UPLOAD

- [ ] 3.1 `MultiBatchOrchestrator` — agregar
      `_upload_active_recorder`, `_set_upload_active_recorder`, y
      callback público `upload_recorder()`.
- [ ] 3.2 `_upload_loop` — setear el upload-active recorder en la
      transición a UPLOAD; limpiar en la transición a DONE/FAILED.
- [ ] 3.3 `TUIDataProvider.__init__` — nuevo kwarg
      `upload_recorder_provider` + propiedad `_upload_metrics`.
- [ ] 3.4 `TUIDataProvider.snapshot` — rutear la derivación de
      `current_chunk_*` a través de `_upload_metrics`.
- [ ] 3.5 `cli/app.py` — wirear `upload_recorder_provider=
      orchestrator.upload_recorder` en la construcción del
      TUIDataProvider.
- [ ] 3.6 Test unitario: `upload_recorder()` inicial devuelve `None`.
- [ ] 3.7 Test unitario: con dos chunks solapados, `upload_recorder()`
      trackea el recorder del chunk en UPLOAD mientras el otro está
      en PREP.
- [ ] 3.8 mypy + ruff limpios.
- [ ] 3.9 Commit
      `fix(orchestrators,tui): separate upload-active recorder slot (042 Phase 3)`.

## Fase 4 — docs + CHANGELOG 0.45.0 + bump de versión + FF

- [ ] 4.1 Entrada `CHANGELOG.md [0.45.0]` — Fixed (3 bugs por id),
      Changed (firma del handler de bandwidth).
- [ ] 4.2 `pyproject.toml` 0.44.0 → 0.45.0.
- [ ] 4.3 `.venv/bin/pip install -e . --no-deps` — refrescar
      metadata del paquete.
- [ ] 4.4 `cmcourier --version` muestra `0.45.0`.
- [ ] 4.5 Tick en fila de features de `README.md`.
- [ ] 4.6 Re-correr `/tmp/verify_tui_041.py` contra staging; capturar
      frame a mitad de vuelo + final, confirmar que no hay bleed y
      que los contadores en vivo andan.
- [ ] 4.7 Suite completa + mypy + ruff limpios.
- [ ] 4.8 Commit
      `docs(042): CHANGELOG 0.45.0 + version bump (042 Phase 4)`.
- [ ] 4.9 FF a main.

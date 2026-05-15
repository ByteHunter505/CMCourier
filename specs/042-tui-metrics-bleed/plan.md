# 042 — Plan

Tres fases para el bugfix propiamente dicho (~2h) + una fase de
docs/release (~30min). Cada fase entrega un commit aislado para que
la superficie de bisect quede angosta si alguno de estos hace surface
de una regresión más adelante.

## Fase 1 — Filtro batch_id del handler de bandwidth (~30min)

### Archivos

- `src/cmcourier/observability/metrics.py`
  - `_BandwidthHandler.__init__` ahora toma un kwarg ``batch_id``
    requerido.
  - ``emit`` cortocircuita cuando ``record.batch_id != self._batch_id``.
    Esto matchea la forma de ``_SlowOpHandler`` de 025.
  - ``MetricsRecorder.start_batch`` construye el handler con el
    ``batch_id`` actual.

### Tests

- `tests/unit/observability/test_metrics.py` (o su equivalente a
  nivel módulo) gana:
  - ``test_bandwidth_handler_filters_by_batch_id`` — emitir un record
    con un ``batch_id`` distinto y assertear que ``cumulative_bytes``
    no se movió.
  - ``test_bandwidth_handler_accepts_matching_batch_id`` — emitir un
    record con el mismo ``batch_id`` y assertear que cumulative_bytes
    se movió.

### Commit

```
fix(observability): per-batch bandwidth handler filter (042 Phase 1)
```

## Fase 2 — Contadores S5 en vivo propagados a la fila CHUNKS (~45min)

### Archivos

- `src/cmcourier/observability/metrics.py`
  - Nuevos contadores thread-safe: ``_s5_done``, ``_s5_failed`` con
    setters ``record_upload_done()`` / ``record_upload_failed()``
    y getters ``upload_done_count()`` / ``upload_failed_count()``.
    Espeja el ``_s5_skipped`` / ``record_upload_skipped`` existente
    de 041 Fase 3.
- `src/cmcourier/orchestrators/staged.py`
  - En ``_stage_5_single`` y ``_stage_5_dual``: en las ramas
    ``outcome == "done"`` / ``"failed"``, también llamar a
    ``rec.record_upload_done()`` / ``rec.record_upload_failed()``.
    Los contadores locales del orchestrator se quedan (el contrato
    de tupla de retorno está sin cambios).
- `src/cmcourier/tui/data_provider.py`
  - ``_chunks_state_snapshot`` lee el upload recorder activo
    (ver Fase 3) y, cuando ``status == "UPLOAD"``, sobrescribe
    ``s5_done`` / ``s5_failed`` con los contadores en vivo del
    recorder. Para filas ``DONE`` / ``FAILED`` mantiene el valor
    congelado de ChunkState (sin cambios).

### Tests

- `tests/unit/observability/test_metrics.py`:
  - ``test_upload_done_count_thread_safe`` — 32 workers cada uno
    llama ``record_upload_done()`` 100×; assertear conteo final == 3200.
- `tests/unit/tui/test_chunks_tab.py`:
  - ``test_upload_row_shows_live_s5_done`` — snapshot sintético con
    un chunk en UPLOAD + campo ``s5_done`` no-cero; assertear que la
    fila renderizada muestra la celda ``done/skip/fail`` correcta.

### Commit

```
fix(tui,observability): live s5_done/failed in CHUNKS during UPLOAD (042 Phase 2)
```

## Fase 3 — Slot separado de active recorder para UPLOAD (~30min)

### Archivos

- `src/cmcourier/orchestrators/multi_batch.py`
  - Nuevo slot ``self._upload_active_recorder: MetricsRecorder | None``.
  - Nuevo helper ``_set_upload_active_recorder(rec | None)`` con lock.
  - Nuevo callback público ``upload_recorder()``.
  - ``_upload_loop`` setea el upload-active recorder cuando un chunk
    transiciona a UPLOAD; lo limpia (de vuelta a None) cuando el
    chunk transiciona a DONE/FAILED. La llamada
    ``_set_active_recorder(item.recorder)`` existente queda para la
    semántica del binding del tab PREP (sin cambios en ese lado).
- `src/cmcourier/tui/data_provider.py`
  - El constructor acepta un callable opcional
    ``upload_recorder_provider`` (espeja ``recorder_provider``).
  - Nueva propiedad privada ``_upload_metrics`` que devuelve el
    upload-active recorder si está seteado, sino hace fallback a
    ``self._metrics`` (el camino single-recorder existente).
  - Usar ``_upload_metrics`` para:
    - Fuente de ``current_chunk_bytes_uploaded``
      (``recorder.bandwidth.cumulative_bytes()``)
    - El override en vivo de ``s5_done`` / ``s5_failed`` de la Fase 2
    - El snapshot de stages S5 que consume ``render_upload``.
- `src/cmcourier/cli/app.py`
  - Pasar ``upload_recorder_provider=orchestrator.upload_recorder``
    a la construcción del ``TUIDataProvider``.

### Tests

- `tests/unit/orchestrators/test_multi_batch.py`:
  - ``test_upload_recorder_returns_none_outside_upload`` — estado
    inicial.
  - ``test_upload_recorder_tracks_chunk_in_upload`` — camino de
    solapamiento, assertear que ``upload_recorder()`` devuelve el
    recorder del chunk #0 mientras el chunk #1 está en PREP.

### Commit

```
fix(orchestrators,tui): separate upload-active recorder slot (042 Phase 3)
```

## Fase 4 — Docs + CHANGELOG 0.45.0 + bump de versión + FF (~30min)

### Archivos

- `CHANGELOG.md` — sección ``[0.45.0]``. Categorías: Fixed (los tres
  bugs por id), Changed (la firma del handler ahora toma batch_id —
  API interna, sin breakage visible al usuario), sin Added/Removed.
- `pyproject.toml` — 0.44.0 → 0.45.0.
- Tick en fila de features de `README.md`.

### Release dance (según CONTRIBUTING)

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.45.0
```

### Verificación

Re-correr el harness headless de TUI (``/tmp/verify_tui_041.py``)
y confirmar:

- El frame final ``S5 UPLOAD ... X.X MB / Y.Y MB`` tiene X ≤ Y (sin
  bleed).
- Frame a mitad de solapamiento: la fila CHUNKS del chunk #0 muestra
  ``UPLOAD d/s/f`` no-cero durante S5 (no clavado en 0/0/0).
- Frame a mitad de solapamiento: el bloque de percentiles S5 del tab
  UPLOAD refleja los datos del chunk #0 mientras el chunk #1 está
  en PREP (p50 > 0).

### Commit

```
docs(042): CHANGELOG 0.45.0 + version bump (042 Phase 4)
```

### FF a main.

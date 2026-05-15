# 052 — Plan

Tres fases (~2.5 h total).

## Fase 1 — #3 timer frozen + #2 rates por-chunk (~45 min)

### Archivos

- `src/cmcourier/tui/data_provider.py`
  - `__init__`: `self._batch_completed_monotonic: float | None = None`.
  - `mark_batch_started`: reset `_batch_completed_monotonic = None`.
  - `mark_batch_complete`: stamp `_batch_completed_monotonic =
    time.monotonic()`.
  - `snapshot`: `end = self._batch_completed_monotonic or
    time.monotonic()`; `elapsed = end - _batch_started_monotonic`.
- `src/cmcourier/tui/chunks_tab.py`
  - `render_chunks`: por chunk + fila TOTAL, computar y
    renderizar `MB/s` + `docs/s` para la fase UPLOAD desde
    `total_bytes`, `s5_done`, `upload_elapsed_s`. Nueva columna
    `RATE` (o extender la celda UPLOAD). Guión cuando
    `upload_elapsed_s <= 0`.

### Tests

- `tests/unit/tui/test_data_provider.py`:
  - `test_elapsed_frozen_after_complete` — dos snapshots después
    de `mark_batch_complete` devuelven `elapsed_s` idéntico.
  - `test_elapsed_ticks_while_running` — todavía avanza
    pre-complete.
- `tests/unit/tui/test_chunks_tab.py`:
  - `test_chunk_shows_upload_rate` — un chunk con bytes +
    elapsed muestra `MB/s` y `docs/s`.
  - `test_zero_elapsed_renders_dash` — `upload_elapsed_s == 0`
    → guión, sin `ZeroDivisionError`.

### Commit

```
feat(tui): freeze run timer on completion + per-chunk throughput (052 Phase 1)
```

## Fase 2 — #4 drill-down por-chunk (~1.25 h)

### Archivos

- `src/cmcourier/domain/ports.py`
  - `DocDetail` dataclass frozen: `txn_num`, `file_name`,
    `status`, `error_message`, `file_size_bytes`.
  - `ITrackingStore.list_docs_for_batch(batch_id) -> list[DocDetail]`
    (abstracto).
- `src/cmcourier/adapters/tracking/sqlite.py`
  - `SQLiteTrackingStore.list_docs_for_batch` — `SELECT` filas
    per-doc del batch bajo `_reader_lock`, mapear a `DocDetail`.
- `src/cmcourier/orchestrators/staged.py`
  - `StagedPipeline.tracking_store` — propiedad pública.
- `src/cmcourier/tui/data_provider.py`
  - `__init__`: arg `tracking_store`; método
    `docs_for_batch(batch_id)` delegando al store.
- `src/cmcourier/cli/app.py`
  - `_run_with_optional_tui`: pasar
    `tracking_store=pipeline.tracking_store` al
    `TUIDataProvider`.
- `src/cmcourier/tui/detail_tab.py` — nuevo:
  `render_detail(chunk_meta, docs)` — header + tabla per-doc.
- `src/cmcourier/tui/app.py`
  - `compose`: agregar `TabPane("DETAIL", id="detail")` con un
    `Static#detail_body`.
  - `BINDINGS`: `[` → `select_prev_chunk`, `]` →
    `select_next_chunk`, `d` → `show_detail`.
  - `self._selected_chunk_idx: int | None = None`; las dos
    acciones lo mueven/clampean contra el conteo de chunks en
    vivo.
  - `_refresh_panels`: renderizar el panel DETAIL — resolver el
    chunk seleccionado desde `snap.chunks_state`, llamar
    `self._provider.docs_for_batch(batch_id)`, pasarlo a
    `render_detail`. Sin selección → un prompt.

### Tests

- `tests/integration/.../test_sqlite*` (o un test nuevo):
  - `test_list_docs_for_batch_returns_per_doc_detail` — poblar
    `migration_log`, assertear la lista de `DocDetail` (status +
    `error_message` llevados).
- `tests/unit/tui/test_data_provider.py`:
  - `test_docs_for_batch_delegates_to_store`.
- `tests/unit/tui/test_detail_tab.py` — nuevo:
  - `render_detail` muestra txn_num / file_name / size / status
    / reason; casos de empty-docs y no-selection.
- `tests/unit/tui/` test piloto:
  - `test_detail_pane_selection` — piloto `run_test()`: `]`
    selecciona un chunk, el panel DETAIL renderiza sus docs.

### Commit

```
feat(tracking,tui): per-chunk drill-down — DETAIL pane backed by the tracking store (052 Phase 2)
```

## Fase 3 — CHANGELOG 0.55.0 + bump de versión + docs + FF (~30 min)

### Archivos

- `CHANGELOG.md` `[0.55.0]` — Added (MB/s + docs/s por-chunk;
  panel de drill-down DETAIL; `list_docs_for_batch`), Fixed (el
  timer del run nunca freezeaba — ahora frozen en completion).
- `pyproject.toml` 0.54.0 → 0.55.0.
- Tick en fila de features de `README.md`.
- `docs/how-to/validation-checklist.md` — §F.1 (TUI): documentar
  el cursor de chunk `[` / `]` + el tab DETAIL + las columnas
  de rate por-chunk.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.55.0
```

### Verify

Suite completa unit + integration + ruff + mypy. Sin Alfresco
en vivo — 052 es dashboard + una lectura del tracking-store;
completamente cubierto por la suite + un piloto `run_test()`.

### Commit

```
docs(052): CHANGELOG 0.55.0 + version bump + TUI drill-down docs (052 Phase 3)
```

### FF a main.

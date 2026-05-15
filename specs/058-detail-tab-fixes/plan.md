# 058 — Plan

Dos fases (~1.5 h total).

## Fase 1 — Persistir metadata de staged-file + DETAIL scrolleable + tests (~70 min)

### Archivos

- `src/cmcourier/domain/ports.py`
  - `ITrackingStore.record_staged_file_metadata(txn_num, batch_id, *,
    source_file_path, page_count, file_size_bytes) -> None` —
    nuevo método abstracto.

- `src/cmcourier/adapters/tracking/sqlite.py`
  - `SQLiteTrackingStore.record_staged_file_metadata` —
    `_enqueue` un `UPDATE migration_log SET source_file_path = ?,
    page_count = ?, file_size_bytes = ? WHERE rvabrep_txn_num = ?
    AND batch_id = ?`.

- `src/cmcourier/orchestrators/staged.py`
  - `_s4_one` — después de
    `staged = self._assembler.assemble(...)` y el bloque
    existente de `mark_stage_pending` / `mark_stage_done`,
    llamar
    `self._tracking_store.record_staged_file_metadata(
        txn, batch_id,
        source_file_path=str(staged.path),
        page_count=staged.page_count,
        file_size_bytes=staged.size_bytes,
    )`. Afuera del guard `if not is_stage_done` — los runs
    de resume también back-fillean.

- `src/cmcourier/tui/app.py`
  - `from textual.containers import Container, VerticalScroll`.
  - El `TabPane` DETAIL rinde
    `VerticalScroll(Static(id="detail_body"))` (sin
    `Container`, sin `classes="tab_body"` — ver CSS abajo).
  - DEFAULT_CSS agrega:
    ```
    #detail_body {
        height: auto;
        padding: 0 1;
    }
    ```
    La regla `Static.tab_body` se queda para PREP / UPLOAD /
    CHUNKS.

- `src/cmcourier/tui/detail_tab.py`
  - `_MAX_ROWS = 2000` (era `100`). Comentario de header
    actualizado.

### Tests

- `tests/integration/adapters/test_sqlite_tracking_store.py`
  - `test_record_staged_file_metadata_updates_existing_row` —
    arrancar un batch, marcar S1-pending con
    `file_size_bytes=None`, llamar al método nuevo con
    valores concretos, flush, quereyar la fila directo vía
    sqlite3, assertear que las tres columnas ahora tienen los
    valores pasados.
  - `test_record_staged_file_metadata_idempotent` — llamarlo
    dos veces con los mismos valores; la segunda llamada es
    un no-op (fila sin cambios).

- `tests/integration/pipeline/test_staged_pipeline.py`
  - `test_s4_persists_staged_file_metadata_to_migration_log`
    — correr el happy path de 1 doc, quereyar la fila de
    `migration_log`, assertear `file_size_bytes > 0`,
    `page_count > 0`, `source_file_path` termina con
    `.pdf`.

- `tests/unit/tui/test_detail_tab.py`
  - `test_renders_all_rows_when_under_max` — pasar 1500
    `DocDetail`s, assertear que cada `txn_num` aparece en el
    output y sin hint `… more`.
  - El test existente `test_truncates_large_chunk_with_cli_pointer`
    actualiza: pasaba 250 docs y esperaba truncamiento en 100.
    O subir el conteo arriba de 2000 para todavía pegar el
    truncamiento, o reescribirlo para assertear "sin
    truncamiento bajo 2000". Elegir el más simple — hacer
    que assertee que 250 docs todos renderizan sin hint de
    truncamiento (el caso real del operador).

- `tests/unit/tui/test_app.py` (o donde se testee la app de
  TUI)
  - `test_detail_pane_is_scrollable` — `async with
    app.run_test() as pilot`: `detail_body =
    app.query_one("#detail_body")`; assertear
    `isinstance(detail_body.parent, VerticalScroll)`. Si
    `test_app.py` no existe todavía, agregarlo.

### Verify

Suite completa unit + integration + ruff + mypy.

### Commit

```
fix(tui): persist S4 staged-file metadata + scrollable DETAIL pane (058 Phase 1)
```

## Fase 2 — CHANGELOG 0.61.0 + bump de versión + README + FF (~20 min)

### Archivos

- `CHANGELOG.md` `[0.61.0]` — entradas de Fixed para los dos
  bugs.
- `pyproject.toml` 0.60.0 → 0.61.0.
- Tick en fila de features de `README.md`.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.61.0
```

### Commit

```
docs(058): CHANGELOG 0.61.0 + version bump (058 Phase 2)
```

### FF a main.

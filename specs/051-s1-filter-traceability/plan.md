# 051 — Plan

Dos fases (~2 h total).

## Fase 1 — Pipeline + TUI: el outcome `filtered` end to end (~1.5 h)

### Archivos

- `src/cmcourier/services/indexing.py`
  - `_enrich_known_row`: fila con código de borrado →
    `raise RVABREPDeletedError` (con `shortname` / `system_id` de
    la fila) en vez de `return []`. Actualizar el docstring.
- `src/cmcourier/orchestrators/staged.py`
  - `_stage_s0_s1`: agregar `filtered = 0`; nueva rama
    `except RVABREPDeletedError` → `filtered += 1`, log INFO
    estructurado (`txn_num`/`shortname` +
    `reason="deleted_at_source"`), `continue` — NO llama
    `timer.mark_failed()`. Devolver
    `(items, skipped_cross_batch, filtered)`.
  - `run`: desempacar el nuevo retorno; `RunReport` gana
    `s1_filtered`.
  - `prep_chunk`: devuelve `(items, skipped, s1_done, s1_filtered,
    s2_failed, s3_failed, s4_failed)`.
  - `RunReport`: agregar `s1_filtered: int`.
- `src/cmcourier/orchestrators/multi_batch.py`
  - `MultiBatchRunReport`: agregar propiedad agregada `s1_filtered`.
  - `ChunkState`: agregar `prep_filtered: int = 0`.
  - `_prep_one_chunk`: desempacar `s1_filtered` de `prep_chunk`;
    setear `prep_filtered` en el update de chunk-state; pasarlo a
    `_PreparedChunk`.
  - `_upload_one_chunk`: pasar `s1_filtered` al `RunReport`
    emitido.
  - `_PreparedChunk`: agregar campo `s1_filtered`.
- `src/cmcourier/cli/app.py`
  - `_emit_outcome`: agregar `s1_filtered=N` a la línea de
    resumen headless.
- `src/cmcourier/tui/data_provider.py`
  - `_chunks_state_snapshot`: incluir `prep_filtered` en el dict.
- `src/cmcourier/tui/prep_tab.py`
  - `render_prep`: agregar una línea
    `FILTERED (S1, deleted at source)`. Tirar el conteo del
    snapshot — `TUISnapshot` gana `s1_filtered: int = 0`,
    poblado por el provider desde el active recorder / chunk
    state.
- `src/cmcourier/tui/chunks_tab.py`
  - `render_chunks`: `PREP d/s/f` → `PREP d/s/f/x`; fila TOTAL
    también.
- `src/cmcourier/tui/data_provider.py`
  - `TUISnapshot.s1_filtered`; el provider suma `prep_filtered`
    a través de chunk states (o lee del active recorder).

### Tests

- `tests/unit/services/test_indexing.py`:
  - `test_enrich_known_row_raises_on_delete_code` — fila con
    código de borrado → `RVABREPDeletedError`.
- `tests/integration/.../test_*` (staged pipeline):
  - `test_s0_s1_counts_deleted_row_as_filtered` — un
    `RvabrepRowTrigger` con código de borrado incrementa
    `filtered`, no `failed`/`done`.
  - `test_s1_outcome_conservation` — `s1_done + s1_filtered == N`.
  - `test_s1_filtered_logged_with_reason` — aserción de caplog
    sobre el log INFO + `reason="deleted_at_source"`.
- `tests/unit/orchestrators/test_multi_batch.py`:
  - `_FakePipeline.prep_chunk` actualizado al retorno de 7-tupla;
    `test_chunk_state_carries_prep_filtered`.
  - Test del agregado `MultiBatchRunReport.s1_filtered`.
- `tests/unit/tui/test_tabs.py` + `test_chunks_tab.py`:
  - `render_prep` muestra la línea FILTERED; `render_chunks`
    muestra `d/s/f/x`.

### Commit

```
feat(indexing,orchestrators,tui): first-class "filtered at S1" outcome (051 Phase 1)
```

## Fase 2 — CHANGELOG 0.54.0 + bump de versión + docs + FF (~30 min)

### Archivos

- `CHANGELOG.md` `[0.54.0]` — Fixed (filas RVABREP con código de
  borrado descartadas silenciosamente en S1), Changed
  (`RVABREPDeletedError` es un filtro no una falla para ambos
  caminos de trigger; los tipos de reporte ganan `s1_filtered`).
- `pyproject.toml` 0.53.0 → 0.54.0.
- Tick en fila de features de `README.md`.
- `docs/how-to/validation-checklist.md` — notar el conteo
  `s1_filtered` en el resumen del run + qué significa
  "filtrado en S1".

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.54.0
```

### Verify

Suite completa unit + integration + ruff + mypy. Sin run de
Alfresco en vivo — 051 es filtering a nivel S1, completamente
cubierto por la suite de tests. (Alfresco puede estar
wipeado/en cualquier estado; 051 no toca el camino CMIS.)

### Commit

```
docs(051): CHANGELOG 0.54.0 + version bump + filter-traceability docs (051 Phase 2)
```

### FF a main.

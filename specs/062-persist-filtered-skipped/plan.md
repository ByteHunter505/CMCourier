# 062 — Plan

Dos fases.

## Fase 1 — Persistencia + tests (~60 min)

### Archivos

- `src/cmcourier/domain/models.py`
  - `StageStatus`: agregar `S1_FILTERED = "S1_FILTERED"` y
    `S1_SKIPPED = "S1_SKIPPED"`.

- `src/cmcourier/domain/ports.py`
  - `ITrackingStore.mark_stage_terminal(txn_num: str,
    batch_id: str, stage: StageStatus,
    error_message: str) -> None` — nuevo abstracto. El
    docstring lo distingue de `mark_stage_failed` (sin bump
    de retry_count, acepta cualquier status terminal
    incluyendo los nuevos).

- `src/cmcourier/adapters/tracking/sqlite.py`
  - `_require_state` mantiene los validators existentes;
    `mark_stage_terminal` acepta cualquier estado cuyo
    sufijo esté en `{"FAILED", "FILTERED", "SKIPPED"}` y
    hace un `UPDATE migration_log SET status = ?,
    error_message = ?, completed_at = ? WHERE
    rvabrep_txn_num = ? AND batch_id = ?`. (Nota: SIN bump
    de retry_count.)
  - El helper validador acepta el set de sufijos nuevo.

- `src/cmcourier/orchestrators/staged.py`
  - En `_stage_s0_s1`:
    - **Camino filtered**: construir un `MigrationRecord`
      con `rvabrep_txn_num = f"FILTERED__{shortname}__{system_id}"`
      sintético, `rvabrep_file_name = ""`. Llamar
      `mark_stage_pending(record, S1_PENDING)` después
      `mark_stage_terminal(synthetic_txn, batch,
      S1_FILTERED, "deleted_at_source")`. El txn sintético
      asegura unicidad sobre `(txn, batch)`.
    - **Camino skipped cross-batch**: `doc.txn_num` real.
      Construir el record, `mark_stage_pending(record,
      S1_PENDING)`, `mark_stage_terminal(doc.txn_num, batch,
      S1_SKIPPED, "cross_batch_uploaded")`.
  - Los contadores existentes `filtered` /
    `skipped_cross_batch` se quedan — los totales de
    `RunReport` no cambian.
  - Actualizar las líneas 10-12 del docstring del módulo
    para reflejar el comportamiento nuevo ("los docs
    skipped ahora producen una fila `S1_SKIPPED`").

- `src/cmcourier/tui/detail_tab.py`
  - Sin cambios requeridos. `_human_size(0)` ya devuelve
    `"—"`, la columna `status` es suficientemente ancha
    para `S1_FILTERED` / `S1_SKIPPED` (12 chars).

### Tests

- `tests/unit/domain/test_ports.py` — agregar
  `mark_stage_terminal` al frozenset
  `ITrackingStore.__abstractmethods__`.

- `tests/integration/adapters/test_sqlite_tracking_store.py`
  — nueva clase `TestMarkStageTerminal062`:
  - `test_marks_filtered_with_reason`: mark_pending S1,
    después mark_stage_terminal(S1_FILTERED,
    "deleted_at_source"), assertear status + error_message
    + completed_at de la fila.
  - `test_marks_skipped_with_reason`: misma forma,
    S1_SKIPPED.
  - `test_does_not_bump_retry_count`: pre-setear
    retry_count=2, llamar mark_stage_terminal, assertear
    que retry_count se queda en 2 (a diferencia de
    mark_stage_failed).
  - `test_rejects_non_terminal_status`: llamarlo con
    `S1_DONE` levanta.

- `tests/integration/pipeline/test_staged_pipeline.py`:
  - El `TestS1FilteredOutcome051` existente (o donde viva
    el test de la spec 051) gana una aserción: después
    del run, quereyar el migration_log para
    `status = "S1_FILTERED"`, assertear que el txn_num
    sintético está ahí con el error_message correcto.
  - `TestCrossBatchSkip` (ya existe): el segundo run
    ahora escribe una fila por doc skipped con
    `status = "S1_SKIPPED"`. Aserción nueva.

### Verify

`pytest tests/unit tests/integration -q` — todo verde.

### Commit

```
feat(s1): persist filtered + cross-batch-skipped docs to migration_log (062 Phase 1)
```

## Fase 2 — CHANGELOG 0.64.0 + version + README + FF (~20 min)

### Archivos

- `CHANGELOG.md` `[0.64.0]` — Changed: los docs skipped
  cross-batch ahora producen una fila `S1_SKIPPED` (el
  contrato "silent skip" de la spec revertido
  intencionalmente para trazabilidad; mencionar implicancias
  de disco en re-runs repetidos). Added: filas
  `S1_FILTERED` para los docs delete-coded en la fuente.
- `pyproject.toml` 0.63.0 → 0.64.0.
- Tick en fila de features de `README.md`.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.64.0
```

### Commit

```
docs(062): CHANGELOG 0.64.0 + version bump (062 Phase 2)
```

### FF a main.

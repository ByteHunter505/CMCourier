# 062 — Persistir filtered + skipped cross-batch de S1 al migration_log

## Por qué

El operador inspeccionó el tab DETAIL durante un run de
staging y notó:

> "Cuando entro al detail no miro cuáles archivos fueron
> filtrados y por qué razón, tampoco miro los skip ni en el
> resumen ni en el detalle, los skip por idempotencia."

Las dos observaciones son correctas. Dos categorías de
outcomes de S1 son **contadas pero no persistidas**, así que
ni el tab DETAIL, ni `analyze batch`, ni
`cmcourier batch show` pueden responder "cuáles documentos
específicos cayeron en este bucket y por qué":

1. **Filtrado en S1 (spec 051)** — los triggers cuya fila
   RVABREP lleva un código de borrado levantan
   `RVABREPDeletedError`; el orchestrator hace
   `filtered += 1` + log INFO, sin fila en `migration_log`.
2. **Skipped cross-batch** — docs cuyo `txn_num` ya está
   `S5_DONE` en un batch anterior se *saltean silenciosamente
   — sin nueva fila en `migration_log`, solo un contador y
   una línea de log INFO*. `staged.py:10-12` documenta esto
   textualmente como una decisión deliberada.

El `RunReport` lleva los totales (`s1_filtered`,
`s1_skipped_cross_batch`); las identidades per-doc solo viven
en `app-*.log` (territorio de grep).

## Qué

### 1. Dos nuevos estados terminales de `StageStatus`

```python
class StageStatus(StrEnum):
    ...
    S1_FILTERED = "S1_FILTERED"   # delete-coded en la fuente (spec 051)
    S1_SKIPPED  = "S1_SKIPPED"    # ya S5_DONE en un batch anterior
```

Ambos son terminales — como `*_FAILED`, no progresan más.

### 2. `_stage_s0_s1` persiste cada caso

- **Filtered**: el `RVABREPDeletedError` no lleva un
  `txn_num` (dispara antes de que ninguna fila sea
  enriquecida). La fila persistida usa un **txn_num
  sintético** `FILTERED__{shortname}__{system_id}` así el
  índice único `(rvabrep_txn_num, batch_id)` se satisface y
  los re-runs colisionan limpiamente vía `INSERT OR IGNORE`.
  El `error_message` lleva `"deleted_at_source"` (y el
  `deleted_count` de la excepción).
- **Skipped cross-batch**: el `txn_num` real está disponible
  (el RVABREPDocument fue enriquecido). Persistir con
  `status = S1_SKIPPED`, `error_message = "cross_batch_uploaded"`.

Ambos pasan a través de:
- `mark_stage_pending(record, S1_PENDING)` —
  `INSERT OR IGNORE` aterriza la fila.
- nuevo
  `mark_stage_terminal(txn, batch, stage, error_message)` —
  `UPDATE` al estado terminal con la razón. Este método es
  distinto de `mark_stage_failed` porque NO debe bumpear
  `retry_count` (filtered/skipped no son fallas).

### 3. El tab DETAIL recibe los docs nuevos gratis

`list_docs_for_batch` ya hace `SELECT ... WHERE batch_id = ?`
ORDER BY txn_num — las filas nuevas simplemente aparecen.
Las columnas `status` y `reason` existentes de
`render_detail` las surface. El `_human_size(0)` ya
renderiza como "—" para la columna de size (los docs
filtered y skipped no tienen archivo staged). Cero cambios
en la lógica de renderizado de la TUI.

### 4. `analyze` + `cmcourier batch show` también los reciben gratis

Ambos ya leen filas de `migration_log` por `batch_id`. Los
estados nuevos aparecerán en los desgloses de status de
`analyze batch <id>` y en los listings de `batch show`. El
pivot `BatchDetails.stage_counts` los levanta.

## Fuera de alcance

- **Drops de `resume_out_of_scope`** (`staged.py:540-549`).
  Son una tercera categoría de "S1 no procesó este doc" —
  un run de resume scopeado al set de `txn_num` de un batch
  anterior rechaza triggers que producen docs nuevos. Fuera
  de alcance acá porque tiene una semántica distinta (filtro
  por política de resume, no por estado de data). Una spec
  futura podría persistirlos también si el operador lo pide.
- **Revertir el contrato "skip silently"** del docstring de
  la spec — cambiamos el comportamiento deliberadamente y
  actualizamos el docstring; no discutimos la intención
  original de §10 (evitar bloat de disco). El CHANGELOG
  explica el nuevo trade.
- **Un comando de retention / prune** para filas viejas de
  migration_log. Si el crecimiento de disco pasa a ser un
  issue podemos agregar
  `cmcourier tracking prune --older-than ...` por separado.
  Hoy el operador puede hacer
  `DELETE FROM migration_log WHERE batch_id < ?`
  manualmente.

## Criterios de aceptación

- `StageStatus.S1_FILTERED` y `StageStatus.S1_SKIPPED`
  existen.
- Un run de pipeline con una fila RVABREP delete-coded
  produce una fila en `migration_log` con
  `status=S1_FILTERED`, `error_message` conteniendo
  `"deleted_at_source"`, y un txn_num sintético. Un test lo
  assertea end-to-end vía el harness del pipeline.
- Un run de pipeline sobre un doc que ya está `S5_DONE` en
  un batch anterior produce una fila en el batch nuevo con
  `status=S1_SKIPPED`,
  `error_message="cross_batch_uploaded"`. Un test lo
  assertea.
- `mark_stage_terminal` existe en `ITrackingStore`,
  implementado en `SQLiteTrackingStore`. Tests para el
  método nuevo directamente.
- El validator `_require_state` en `sqlite.py` acepta
  `S1_FILTERED` y `S1_SKIPPED` para el método nuevo.
- `list_docs_for_batch` incluye los dos statuses nuevos —
  cubierto por los tests a nivel pipeline.
- El test de contrato de port de TUI (`test_ports.py`)
  lista `mark_stage_terminal` en
  `ITrackingStore.__abstractmethods__`.
- Suite completa unit + integration verde; mypy + ruff
  limpios.
- `CHANGELOG.md [0.64.0]` describe el trade (más filas en
  `migration_log` en re-runs, trazabilidad completa a
  cambio).
- `pyproject.toml` 0.63.0 → 0.64.0.

## Notas sobre estrategia de tests

El harness del pipeline ya ejercita ambos caminos vía el
fixture `rvabrep.csv` (`TESTUNMAPPED` no produce filtered
porque es un caso de S2; necesitamos una fila con un código
de borrado para impulsar el camino filtered). Extendemos el
test existente que impulsa el fixture de 6 docs: assertear
que el txn_num sintético de la fila DELETED aparece con
`S1_FILTERED`. Para el caso cross-batch, la clase existente
`TestCrossBatchSkip` corre los mismos triggers dos veces — el
segundo run ahora produce filas `S1_SKIPPED` sobre las que el
test puede assertear.

El writer del estado terminal se testea unitariamente
directamente en `test_sqlite_tracking_store.py` para los dos
statuses nuevos, incluyendo idempotencia (llamarlo dos veces
con la misma clave es un UPDATE no-op).

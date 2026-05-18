# 086 — `cmcourier sync` honra `tracking.as400_sync.columns`

## Por qué

Bug productivo descubierto activando el sync AS400. El operador
configuró overrides de columnas en el YAML (`finished_at_column:
SU_NOMBRE_REAL`) porque su tabla NIARVILOG no tiene los nombres
canónicos. `cmcourier batch run` los respetaba; `cmcourier sync
status` y `cmcourier sync resolve` los **ignoraban silenciosamente**
y usaban los defaults hardcodeados (FINREI, PMRREI, STSCOD…).

Síntoma reportado:

```
$ cmcourier sync status --config sample/config-prod-as400.yaml
AS400 error: NIARVILOG niarvilog_cleanup_stale failed:
('42S22', '[42S22] [IBM][System i Access ODBC Driver]
[DB2 for i5/OS]SQL0206 - Column or global variable FINREI not found.')
```

FINREI no existía en la tabla del banco. El operador ya había
puesto el override correcto en el YAML, pero el CLI lo descartaba.

## Causa raíz

Comparación lado a lado entre los dos paths del código:

### `wiring.py:226-236` — usado por `batch run` ✅

```python
as400_store = As400NiarvilogStore(
    connection=sync_cfg.connection,
    ...
    columns=_niarvilog_columns_from_schema(sync_cfg.columns),   # HONRA YAML
    ...
)
```

### `sync.py:_load_stores` — usado por `sync status` / `sync resolve` ❌

```python
as400 = As400NiarvilogStore(
    connection=sync_cfg.connection,
    ...
    # ❌ FALTA: columns=_niarvilog_columns_from_schema(sync_cfg.columns)
    ...
)
```

`As400NiarvilogStore.__init__` tiene `columns: NiarvilogColumns =
field(default_factory=NiarvilogColumns)`. Si no se pasa, usa los
defaults canónicos — exactamente el comportamiento equivocado para
operadores con tablas no-canónicas.

## Qué

### Cambios

1. **`sync.py:_load_stores`**: pasar
   `columns=_niarvilog_columns_from_schema(sync_cfg.columns)` al
   constructor — alinea con `wiring.py`.

2. **Import** del helper compartido `_niarvilog_columns_from_schema`
   desde `cmcourier.config.wiring`.

### Tests

* `tests/unit/cli/commands/test_sync_honors_columns_override.py`:
  construye un `As400SyncConfig` con `finished_at_column:
  "MY_FINISHED_COL"` + `status_column: "MY_STATUS_COL"`, monkey-patcha
  `load_config` / `load_secrets` / `As400NiarvilogStore`, verifica
  que `_load_stores` instancia el adapter con el `NiarvilogColumns`
  derivado del YAML (no con los defaults).

## Criterios de aceptación

1. `cmcourier sync status` contra un YAML con
   `columns.finished_at_column: NOMBRE_REAL` ejecuta el SQL contra
   `NOMBRE_REAL`, no contra `FINREI`.
2. Si el operador no define `columns:`, sigue funcionando con los
   defaults canónicos (backward-compat).
3. `pytest -m unit` pasa.

## Riesgos

* **Backward-compat: cero**. Pre-086 el CLI ignoraba el override;
  post-086 lo respeta. Operadores que NO tenían override en el YAML
  ven el mismo comportamiento (`NiarvilogColumns()` con defaults).
  Operadores que SÍ tenían override estaban rotos pre-086 — el fix
  los desbloquea.
* **No abarca el bug semántico** de `cleanup_stale_in_progress`
  usando `finished_at` (FINREI) cuando conceptualmente debería usar
  `started_at` (PMRREI) — las filas en `STSCOD='I'` no tienen
  `finished_at` por definición. Eso queda para una spec separada
  (087, posible).

## Notas

- El helper `_niarvilog_columns_from_schema` está prefijado con
  underscore por convención (módulo-privado), pero importarlo desde
  un módulo hermano de `cmcourier.config` está bien. Si se promueve
  a API pública en el futuro, basta sacar el underscore.
- Recordatorio operativo: los nombres en `columns:` son **case-sensitive**
  porque se interpolan literal en el SQL. DB2 normaliza ordinary
  identifiers a mayúsculas en runtime, pero conviene usar UPPERCASE
  por convención.

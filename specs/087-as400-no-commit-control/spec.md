# 087 — Adapter NIARVILOG conecta con `CommitMode=0` (sin commit control)

## Por qué

Bug productivo. El operador configuró el sync AS400 correctamente
(spec 086 fix de wiring) y obtuvo este error en `sync status`:

```
AS400 error: NIARVILOG niarvilog_cleanup_stale failed:
('HY000', '[HY000] [IBM][System i Access ODBC Driver]
[DB2 for i5/OS]SQL7008 - RVIMGLOG in LIBHJJ not valid for operation.
(-7008) (SQLExecDirect)')
```

## Causa raíz

El IBM i Access ODBC Driver abre la conexión, por default, con
**commitment control `*CHG`** (commit on change). Bajo `*CHG`, DB2
for i exige que las tablas tengan **journaling activo** para
ejecutar UPDATE/INSERT/DELETE. Las tablas no journaled (como la
NIARVILOG del operador en `LIBHJJ.RVIMGLOG`) revientan con
`SQL7008 - not valid for operation`.

El connection string pre-087 era:

```
DRIVER={IBM i Access ODBC Driver};
SYSTEM=...;
PORT=...;
DATABASE=...;
UID=...;
PWD=...;
```

Sin `CommitMode` explícito → el driver usa default `*CHG` → falla
en tablas no journaled.

## Por qué CMCourier no necesita commitment control

El adapter `As400NiarvilogStore` ejecuta cada operación como
**una sola sentencia atómica**:

| Operación | SQL |
|---|---|
| `try_claim` | `UPDATE … SET STSCOD='I' WHERE … AND STSCOD='N'` |
| `mark_uploaded` | `UPDATE … SET STSCOD='O', OBJIDN=? WHERE …` |
| `mark_failed` | `UPDATE … SET STSCOD='F', EERRMSG=? WHERE …` |
| `cleanup_stale_in_progress` | `UPDATE … SET STSCOD='N' WHERE STSCOD='I' AND …` |
| `_insert_new_claim` | `INSERT INTO …` |
| `read_state_by_txn` | `SELECT … FROM … WHERE TRNNUM=?` |

**Ninguna operación abarca múltiples sentencias dentro de una
transacción.** El claim atómico que evita race conditions con otros
procesos viene del predicado `WHERE STSCOD='N'` del UPDATE, NO de
un commit. El `conn.commit()` posterior es esencialmente
cosmético — sin commit control queda como no-op inofensivo y los
UPDATE/INSERT quedan persistidos al instante.

## Qué

### Cambios

1. **`As400NiarvilogStore._build_connection_string`**: agrega
   `CommitMode=0;` al string. `0` = `*NONE` en la convención del
   driver IBM i Access ODBC.

```python
return (
    f"DRIVER={{{self._cfg.driver}}};"
    f"SYSTEM={self._cfg.host};"
    f"PORT={self._cfg.port};"
    f"DATABASE={self._cfg.database};"
    f"UID={self._username};"
    f"PWD={self._password};"
    f"CommitMode=0;"        # ← agregado en 087
)
```

### Tests

* `tests/unit/adapters/tracking/test_niarvilog_connection_string.py`:
  verifica que el connection string contenga `CommitMode=0` y que
  los demás parámetros sigan ahí.

## Criterios de aceptación

1. Connection string siempre incluye `CommitMode=0`.
2. `sync status` ejecuta contra tabla NIARVILOG **no journaled** sin
   SQL7008.
3. `sync status` ejecuta contra tabla NIARVILOG **journaled** con
   comportamiento idéntico (sin commit control, pero las
   transacciones implícitas del driver siguen siendo atómicas
   por-sentencia).
4. `pytest -m unit` pasa.

## Riesgos

* **Backward-compat**: el cambio es estrictamente más permisivo. Las
  tablas journaled siguen funcionando (no se aprovecha el journal,
  pero tampoco se requiere). Las tablas no journaled — que pre-087
  rompían — ahora funcionan.
* **No se altera la atomicidad del claim**. El predicado
  `WHERE STSCOD='N'` del UPDATE es atómico a nivel DB2 row-locking
  independientemente del commitment control. Dos procesos haciendo
  claim simultáneo verán uno ganar (1 row affected) y el otro
  perder (0 rows affected).
* **`adapters/sources/as400.py` NO se toca en 087**. El RVABREP
  source es read-only (SELECT) y el operador no reportó SQL7008 ahí
  — funcionaba pre-087. Si surge una tabla source no journaled con
  SELECT bajo `*CHG`, se replica el fix análogo en otra spec.

## Notas

- Pareja con 086 (wiring fix del CLI sync). 086 dejó que el override
  de columnas llegara al adapter; 087 hace que el adapter pueda
  ejecutar contra cualquier tabla NIARVILOG (journaled o no).
- Si el operador quiere preservar commit control por algún motivo
  específico (ej. integración con un trigger DB2 que requiere
  transacción), se puede agregar en una spec futura como flag de
  config con default `*NONE`.

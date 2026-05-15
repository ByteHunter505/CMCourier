# 047 — Persistir cm_object_id en S5_DONE

## Por qué

El step §L.3 del checklist de validación ("GET a un doc por objectId,
sacando el OID de la tracking DB") se encontró no-funcional durante
la pasada de housekeeping: ``migration_log.cm_object_id`` es
``NULL`` para cada fila, incluso después de una subida exitosa.

Causa raíz — ``orchestrators/staged.py``:

```python
cm_object_id = self._uploader.upload(...)        # línea 895: CMIS devuelve el OID
...
self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S5_DONE)  # 929
item.cm_object_id = cm_object_id                 # 930: SOLO en memoria
```

La línea 930 asigna el OID en el ``_StageItem`` en memoria (donde
muere cuando el run termina). ``mark_stage_done`` — la llamada que
realmente escribe a SQLite — solo actualiza ``status`` y
``completed_at``:

```python
def mark_stage_done(self, txn_num, batch_id, stage):
    self._enqueue(
        "UPDATE migration_log SET status = ?, completed_at = ? "
        "WHERE rvabrep_txn_num = ? AND batch_id = ?",
        (stage.value, datetime.now().isoformat(), txn_num, batch_id),
    )
```

La columna ``cm_object_id`` YA EXISTE en el schema
(``sqlite.py:64``). ``mark_stage_pending`` la escribe — pero en
tiempo de S1_PENDING es ``None``, y nada nunca la back-fillea.

El camino de AS400 no se ve afectado — ``IdempotencyCoordinator.mark_uploaded``
SÍ pasa ``cm_object_id`` a ``As400NiarvilogStore`` que lo escribe a
``OBJIDN``. Es solo el ``migration_log`` SQLite el que pierde el
valor. Los operadores en el camino SQLite-only (el caso común de
staging + banco chico) no pueden responder "¿cuál es el objectId de
CMIS del doc X?" desde su tracking DB.

## Qué

### 1. ``ITrackingStore.mark_stage_done`` gana un ``cm_object_id`` opcional

```python
def mark_stage_done(
    self,
    txn_num: str,
    batch_id: str,
    stage: StageStatus,
    *,
    cm_object_id: str | None = None,
) -> None:
```

Keyword-only, default ``None``. Los callers de S1..S4 no cambian —
pasan nada, la columna queda intacta. El caller de S5 pasa el OID
real.

### 2. ``SQLiteTrackingStore.mark_stage_done`` escribe la columna cuando se la pasan

Cuando ``cm_object_id`` no es ``None``, el UPDATE también setea la
columna ``cm_object_id``:

```sql
UPDATE migration_log
SET status = ?, completed_at = ?, cm_object_id = ?
WHERE rvabrep_txn_num = ? AND batch_id = ?
```

Cuando ``cm_object_id`` es ``None`` el SQL es byte-idéntico al de
hoy (solo status + completed_at) — así que las transiciones S1..S4
y cualquier caller que pasa ``None`` se comportan exactamente como
pre-047.

### 3. ``IdempotencyCoordinator.mark_uploaded`` pasa el OID a SQLite

El coordinator ya recibe ``cm_object_id`` y lo reenvía al store de
AS400. Ahora también lo reenvía al ``mark_stage_done`` del store
SQLite así ambos backends llevan el valor.

### 4. El camino de S5 en ``staged.py`` pasa el OID

La rama non-coordinator en ``staged.py:929`` pasa a:

```python
self._tracking_store.mark_stage_done(
    txn, batch_id, StageStatus.S5_DONE, cm_object_id=cm_object_id
)
```

La asignación en memoria ``item.cm_object_id = cm_object_id`` se
queda (algún código de TUI / report puede leerla dentro del run) —
solo que ya no es el ÚNICO lugar donde aterriza el valor.

## Fuera de alcance

- Back-fillear ``cm_object_id`` para batches históricos subidos
  antes de 047. Esas filas quedan ``NULL``; el valor es recuperable
  desde Alfresco vía un children-walk si alguna vez se necesita.
- Agregar ``cm_object_id`` al output de CLI ``batch show`` /
  ``analyze``. La columna ahora se puebla; surfacearla en reportes
  del operador es un cambio separado, cosmético.
- La ventana de `race condition` del kill de 045 (CMIS 200 → commit
  de SQLite interrumpido). 047 no amplía ni angosta esa ventana —
  solo asegura que el valor esté en el UPDATE que ya ocurre.
- Migración de schema. La columna ya existe; nada de ALTER TABLE.

## Criterios de aceptación

- Test unitario: ``SQLiteTrackingStore.mark_stage_done`` con
  ``cm_object_id="cm-abc"`` resulta en una fila cuya columna
  ``cm_object_id`` lee ``"cm-abc"``.
- Test unitario: ``mark_stage_done`` SIN ``cm_object_id`` (el
  camino S1..S4) deja la columna intacta — verificado seteándola
  primero, después llamando a ``mark_stage_done`` sin el arg, y
  asserteando que el valor previo sobrevive.
- Test unitario: ``IdempotencyCoordinator.mark_uploaded`` reenvía
  ``cm_object_id`` a la llamada de ``mark_stage_done`` del store
  SQLite (assertion sobre mock).
- Re-verify en vivo: un run chico de staging (``--total 5``)
  seguido de una query a ``migration_log`` muestra
  ``cm_object_id`` poblado (no-NULL) para cada fila ``S5_DONE``.
- Entrada ``CHANGELOG.md [0.50.0]``.
- mypy + ruff limpios. Suite completa de unit + integration verde.

## Notas sobre estrategia de tests

Los tests del store SQLite ya ejercitan ``mark_stage_done`` contra
un archivo SQLite real en disco (Principio VI de la Constitución —
sin mockear la DB). Los extendemos con los dos casos de
``cm_object_id``. El test del coordinator usa el doble MagicMock de
SQLite existente y assertea el kwarg reenviado. El re-verify en
vivo es una query ``sqlite3`` de una línea después de un run de 5
docs — rápido, determinístico, y cierra el gap §L.3 end-to-end.

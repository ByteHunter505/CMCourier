# 047 — Plan

Dos fases (~1 h total).

## Fase 1 — Pasar cm_object_id a través de mark_stage_done (~40 min)

### Archivos

- `src/cmcourier/domain/ports.py`
  - ``ITrackingStore.mark_stage_done`` gana keyword-only
    ``cm_object_id: str | None = None``.
- `src/cmcourier/adapters/tracking/sqlite.py`
  - ``SQLiteTrackingStore.mark_stage_done`` construye el UPDATE con
    la columna ``cm_object_id`` solo cuando el arg no es None.
    El camino None queda byte-idéntico a pre-047.
- `src/cmcourier/services/idempotency.py`
  - ``IdempotencyCoordinator.mark_uploaded`` reenvía
    ``cm_object_id=cm_object_id`` a la llamada
    ``mark_stage_done`` de SQLite.
- `src/cmcourier/orchestrators/staged.py`
  - La llamada non-coordinator a S5_DONE pasa
    ``cm_object_id=cm_object_id``.

### Tests

- `tests/integration/adapters/test_sqlite_tracking_store.py`:
  - ``test_mark_stage_done_persists_cm_object_id`` — pasar el OID,
    leer la fila, assertear la columna.
  - ``test_mark_stage_done_without_oid_leaves_column`` — setear la
    columna vía ``mark_stage_pending`` con un record llevando un
    OID (o un done previo), después llamar a ``mark_stage_done``
    sin el arg, assertear que la columna sobrevive.
- `tests/unit/services/test_idempotency.py`:
  - actualizar la aserción existente de ``mark_uploaded`` para
    esperar el kwarg ``cm_object_id`` en la llamada reenviada de
    ``mark_stage_done``.
- `tests/unit/domain/test_ports.py`:
  - si assertea la firma de ``mark_stage_done``, actualizarla.

### Commit

```
fix(tracking): persist cm_object_id on S5_DONE transition (047 Phase 1)
```

## Fase 2 — Docs + CHANGELOG 0.50.0 + bump de versión + re-verify en vivo + FF (~20 min)

### Archivos

- `CHANGELOG.md` ``[0.50.0]`` — Fixed (cm_object_id nunca persistido
  al migration_log).
- `pyproject.toml` 0.49.0 → 0.50.0.
- Tick en fila de features de `README.md`.
- `docs/how-to/validation-checklist.md` §L.3 — sacar la nota
  "issue conocido: cm_object_id no persistido", restaurar la query
  de la tracking DB como camino primario.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.50.0
```

### Re-verify en vivo

```bash
# Run chico fresco contra staging.
bash scripts/staging/wipe-alfresco-docs.sh
rm -f sample/staging-tracking.db sample/staging-tracking.db-wal sample/staging-tracking.db-shm

CMIS_USERNAME=admin CMIS_PASSWORD=admin .venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml --total 5 --no-tui

# Chequeo §L.3 — el OID ahora debe ser legible desde la tracking DB.
.venv/bin/python -c "
import sqlite3
c = sqlite3.connect('sample/staging-tracking.db')
total = c.execute('SELECT COUNT(*) FROM migration_log WHERE status=\"S5_DONE\"').fetchone()[0]
withoid = c.execute('SELECT COUNT(*) FROM migration_log WHERE status=\"S5_DONE\" AND cm_object_id IS NOT NULL').fetchone()[0]
print(f'S5_DONE rows: {total}  with cm_object_id: {withoid}')
assert total > 0 and withoid == total, 'cm_object_id not fully populated'
print('PASS')
"
```

Aceptación: cada fila ``S5_DONE`` tiene un ``cm_object_id`` no-NULL.

### Commit

```
docs(047): CHANGELOG 0.50.0 + version bump + cm_object_id re-verify (047 Phase 2)
```

### FF a main.

# 047 — Plan

Two phases (~1 h total).

## Phase 1 — Thread cm_object_id through mark_stage_done (~40 min)

### Files

- `src/cmcourier/domain/ports.py`
  - ``ITrackingStore.mark_stage_done`` gains keyword-only
    ``cm_object_id: str | None = None``.
- `src/cmcourier/adapters/tracking/sqlite.py`
  - ``SQLiteTrackingStore.mark_stage_done`` builds the UPDATE with
    the ``cm_object_id`` column only when the arg is not None.
    None path stays byte-identical to pre-047.
- `src/cmcourier/services/idempotency.py`
  - ``IdempotencyCoordinator.mark_uploaded`` forwards
    ``cm_object_id=cm_object_id`` into the SQLite
    ``mark_stage_done`` call.
- `src/cmcourier/orchestrators/staged.py`
  - The non-coordinator S5_DONE call passes
    ``cm_object_id=cm_object_id``.

### Tests

- `tests/integration/adapters/test_sqlite_tracking_store.py`:
  - ``test_mark_stage_done_persists_cm_object_id`` — pass the OID,
    read the row, assert the column.
  - ``test_mark_stage_done_without_oid_leaves_column`` — set the
    column via ``mark_stage_pending`` with a record carrying an
    OID (or a prior done), then call ``mark_stage_done`` without
    the arg, assert the column survives.
- `tests/unit/services/test_idempotency.py`:
  - update the existing ``mark_uploaded`` assertion to expect the
    ``cm_object_id`` kwarg on the forwarded ``mark_stage_done``
    call.
- `tests/unit/domain/test_ports.py`:
  - if it asserts the ``mark_stage_done`` signature, update it.

### Commit

```
fix(tracking): persist cm_object_id on S5_DONE transition (047 Phase 1)
```

## Phase 2 — Docs + CHANGELOG 0.50.0 + version bump + live re-verify + FF (~20 min)

### Files

- `CHANGELOG.md` ``[0.50.0]`` — Fixed (cm_object_id never
  persisted to migration_log).
- `pyproject.toml` 0.49.0 → 0.50.0.
- `README.md` feature row tick.
- `docs/how-to/validation-checklist.md` §L.3 — drop the "known
  issue: cm_object_id not persisted" note, restore the
  tracking-DB query as the primary path.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.50.0
```

### Live re-verify

```bash
# Small fresh run against staging.
bash scripts/staging/wipe-alfresco-docs.sh
rm -f sample/staging-tracking.db sample/staging-tracking.db-wal sample/staging-tracking.db-shm

CMIS_USERNAME=admin CMIS_PASSWORD=admin .venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml --total 5 --no-tui

# §L.3 check — the OID must now be readable from the tracking DB.
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

Acceptance: every ``S5_DONE`` row has a non-NULL ``cm_object_id``.

### Commit

```
docs(047): CHANGELOG 0.50.0 + version bump + cm_object_id re-verify (047 Phase 2)
```

### FF to main.

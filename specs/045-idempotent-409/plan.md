# 045 — Plan

Dos fases (~1h total).

## Fase 1 — Recuperación de 409 en CmisUploader (~30 min)

### Archivos

- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - Nuevo método privado
    ``_lookup_existing_object_id(folder_url, name) -> str | None``
    que hace GET a ``{folder_url}?cmisselector=children&maxItems=…``,
    encuentra la entrada con ``cmis:name`` matcheando, devuelve su
    ``cmis:objectId`` (o ``None``).
  - El bloque ``except CMISClientError`` de ``upload(...)``
    extendido: cuando ``exc.status_code == 409``, emitir el evento
    ``s5_upload_409_recovery_attempt``, correr el lookup, emitir
    ``s5_upload_409_recovered`` (o ``..._failed``), después o
    devolver el id recuperado o re-raisear.

### Tests

- `tests/unit/adapters/upload/test_cmis_uploader.py` (o donde vivan
  los tests del uploader):
  - ``test_upload_409_recovered_returns_existing_object_id`` —
    mockear POST 409 + GET children devolviendo el doc; assertear
    que upload() devuelve el id recuperado sin levantar.
  - ``test_upload_409_not_recovered_reraises`` — mockear POST 409 +
    GET children devolviendo vacío; assertear que upload() levanta
    ``CMISClientError`` con status_code=409.
  - ``test_upload_200_does_not_call_lookup`` — mockear POST 200; el
    endpoint de lookup no está registrado así que cualquier llamada
    levantaría; esto confirma que el lookup solo se invoca en 409.

### Commit

```
fix(uploader): idempotent 409 recovery — lookup existing object on conflict (045 Phase 1)
```

## Fase 2 — docs + CHANGELOG 0.48.0 + bump de versión + re-verify en vivo + FF (~30 min)

### Archivos

- `CHANGELOG.md` ``[0.48.0]`` — Fixed (idempotencia de `race condition`
  del kill), Added (helper de lookup + nuevos eventos estructurados).
- `pyproject.toml` 0.47.0 → 0.48.0.
- Tick en fila de features de `README.md`.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.48.0
```

### Re-verificación en vivo

```bash
# Mismo escenario que 044 cerró para la detección de resume.
bash scripts/staging/wipe-alfresco-docs.sh
rm -f sample/staging-tracking.db sample/staging-tracking.db-wal sample/staging-tracking.db-shm

# Run 1 — arrancar + kill a mitad de S5
CMIS_USERNAME=admin CMIS_PASSWORD=admin \
.venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml \
  --total 50 --batches-in-flight 1 --no-tui &
# esperar por ~25 S5_DONE, kill -9 al python

# Capturar batch_id
batch_id=$(.venv/bin/python -c "
import sqlite3; print(sqlite3.connect('sample/staging-tracking.db').execute(
    'SELECT DISTINCT batch_id FROM migration_log'
).fetchone()[0]
")

# Run 2 — resume; pre-045 se esperan ~4 s5_failed; post-045 se esperan 0
CMIS_USERNAME=admin CMIS_PASSWORD=admin \
.venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml \
  --batch-id "$batch_id" --resume --no-tui
```

Aceptación:

- El Run 2 reporta ``s5_failed=0``.
- ``rg s5_upload_409_recovered sample/logs/network-2026-05-13.jsonl |
  wc -l`` ≥ 1 (al menos una recuperación ocurrió).
- Conteo de docs de Alfresco == txns distintos en el batch.

### Commit

```
docs(045): CHANGELOG 0.48.0 + version bump + 409 idempotency live re-verify (045 Phase 2)
```

### FF a main.

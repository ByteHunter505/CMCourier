# 044 — Plan

Tres fases (~1.5 h total).

## Fase 1 — Reescritura del algoritmo de ``_apply_resume`` (~45 min)

### Archivos

- `src/cmcourier/cli/app.py`
  - Re-ordenar ``_apply_resume`` a: validar inputs → chequear
    override explícito de ``--from-stage`` → auto-detectar (gap +
    FAILED/PENDING) → exit "clean".
  - Lógica de auto-detección: looping stages 1..5, en cada stage
    chequear FAILED/PENDING primero (resuelve a N) después chequear
    N<5 Y conteo DONE > 0 (resuelve a N+1).

### Tests

- `tests/unit/cli/test_app.py` (o nuevo
  `tests/unit/cli/test_resume.py` si los tests de app.py no
  existen):
  - ``test_apply_resume_failed_pending_takes_priority`` — tanto
    FAILED en S3 como DONE en S4: resuelve a 3.
  - ``test_apply_resume_stage_gap_detected`` — S4_DONE=543,
    S5_DONE=281: resuelve a 5.
  - ``test_apply_resume_truly_clean`` — solo filas S5_DONE:
    exit 0 con mensaje "Nothing to resume".
  - ``test_apply_resume_explicit_from_stage_beats_clean`` — batch
    clean + ``explicit_from_stage=5``: devuelve 5 sin exit
    "clean".
  - ``test_apply_resume_unknown_batch`` — batch_id desconocido:
    exit 1 con "Batch not found".

### Commit

```
fix(cli): resume detects S{N}_DONE→S{N+1} stage gaps + honors explicit --from-stage (044 Phase 1)
```

## Fase 2 — ``--batch-id`` siempre pasado (~15 min)

### Archivos

- `src/cmcourier/cli/app.py`
  - Descartar el condicional ``if resume_flag else None`` en la
    asignación de ``resume_batch_id`` (línea 711 en 0.46.0).
  - Documentar la nueva semántica en el comentario inline: "cualquier
    ``--batch-id`` que el operador pase es el batch_id sobre el cual
    el run opera; el orchestrator valida existencia."

### Tests

- `tests/integration/cli/test_pipeline_kinds.py` (o donde vivan los
  tests de integración de CLI):
  - ``test_batch_id_flag_passed_without_resume`` — correr con
    ``--batch-id X --from-stage 1`` en una DB fresca: tiene éxito
    y el batch nuevo queda guardado bajo ``X`` en migration_log.

### Commit

```
fix(cli): --batch-id always threads to the orchestrator (044 Phase 2)
```

## Fase 3 — Docs + CHANGELOG 0.47.0 + bump de versión + re-verify en vivo + FF (~30 min)

### Archivos

- `CHANGELOG.md` ``[0.47.0]`` — Fixed (los tres bugs de resume por
  id), Changed (orden del algoritmo de ``_apply_resume`` +
  semántica de ``--batch-id``).
- `pyproject.toml` 0.46.0 → 0.47.0.
- Tick en fila de features de `README.md`.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.47.0
```

### Re-verificación en vivo (replicar el escenario de staging §H.1)

```bash
# Setup
bash scripts/staging/wipe-alfresco-docs.sh
rm -f sample/staging-tracking.db sample/staging-tracking.db-wal sample/staging-tracking.db-shm

# Run 1 — arrancar + kill a mitad de S5
CMIS_USERNAME=admin CMIS_PASSWORD=admin \
.venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml \
  --total 50 --batches-in-flight 1 --no-tui &
# esperar hasta que la tracking DB tenga ~20-30 filas S5_DONE, después kill -9

# Capturar batch_id desde migration_log
batch_id=$(.venv/bin/python -c "
import sqlite3
print(sqlite3.connect('sample/staging-tracking.db').execute(
    'SELECT DISTINCT batch_id FROM migration_log'
).fetchone()[0]
")

# Run 2 — resume
CMIS_USERNAME=admin CMIS_PASSWORD=admin \
.venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml \
  --batch-id "$batch_id" --resume --no-tui
```

Aceptación:

- El Run 2 NO debe imprimir "Nothing to resume".
- El Run 2 debe reportar ``s5_done > 0`` matcheando el trabajo
  restante.
- Final ``alfresco_total_docs == distinct_txns_in_batch`` (dentro de
  la ventana de race de 4-10 docs diferida a la spec de follow-up).

### Commit

```
docs(044): CHANGELOG 0.47.0 + version bump + resume live re-verify (044 Phase 3)
```

### FF a main.

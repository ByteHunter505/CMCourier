# 048 — Plan

Tres fases (~2.5 h total).

## Fase 1 — Schema + wiring + borrar As400TriggerStrategy (~1 h)

### Archivos

- `src/cmcourier/config/schema.py`
  - Nuevos modelos ``CsvRvabrepSource`` / ``As400RvabrepSource`` +
    ``RvabrepSourceUnion`` discriminada por ``kind``.
  - Renombrar ``IndexingSourceConfig`` → ``IndexingConfig``;
    reemplazar su campo ``csv_path: FilePath`` con
    ``source: RvabrepSourceUnion``.
  - Remover ``As400TriggerConfig`` del ``TriggerConfigUnion``. El
    config loader ahora rechaza ``trigger.kind: as400`` con un
    error de discriminated-union; agregamos un chequeo explícito
    más amigable en el loader que apunta a ``indexing.source``.
  - ``As400ConnectionConfig`` se queda (compartido con el sync de
    NIARVILOG).
- `src/cmcourier/config/wiring.py`
  - Nuevo ``_build_rvabrep_source(indexing_cfg, secrets) -> IDataSource``
    despachando por ``indexing_cfg.source.kind``.
  - ``build_pipeline`` lo llama una vez; el resultado alimenta
    tanto ``IndexingService`` como ``_build_trigger_strategy``.
  - ``_build_trigger_strategy``: descartar la rama de
    ``As400TriggerConfig``. ``RvabrepTriggerConfig`` y
    ``LocalScanTriggerConfig`` siguen usando el ``rvabrep_src``
    compartido (ahora posiblemente AS400).
  - Descartar el import de ``As400TriggerStrategy``.
- `src/cmcourier/services/triggers/as400.py` — **borrado**.
- `src/cmcourier/services/triggers/__init__.py` — descartar el
  export de ``As400TriggerStrategy``.
- `src/cmcourier/services/__init__.py` — ídem.
- `src/cmcourier/cli/app.py` — si el subcomando
  as400-trigger-pipeline existe como su propia entrada de CLI,
  doblarlo: el comando ``as400-trigger-pipeline run`` se remueve
  (o se aliasea a ``rvabrep-pipeline``). Confirmar durante la
  implementación.

### Tests

- `tests/unit/config/test_loader.py`:
  - ``test_indexing_source_csv_variant`` — carga, construye un
    ``CsvRvabrepSource``.
  - ``test_indexing_source_as400_variant`` — carga, construye un
    ``As400RvabrepSource`` con la query.
  - ``test_trigger_kind_as400_rejected`` — ``trigger.kind: as400``
    levanta ``ConfigurationError`` mencionando ``indexing.source``.
- `tests/integration/config/test_wiring.py`:
  - ``test_build_rvabrep_source_csv`` — devuelve ``TabularDataSource``.
  - ``test_build_rvabrep_source_as400`` — devuelve
    ``As400DataSource`` (fake a nivel driver, sin servidor en
    vivo).
- Borrar los casos de `tests/.../test_*` que apuntan a
  ``As400TriggerStrategy`` directamente; el camino del SQL as400
  ahora está cubierto por los tests del modo query de
  ``As400DataSource`` en ``test_as400.py``.

### Commit

```
feat(config,wiring): pluggable RVABREP source (CSV ↔ AS400); drop as400 trigger kind (048 Phase 1)
```

## Fase 2 — Migrar todos los configs + fixtures + tests (~1 h)

### Archivos

- `sample/config-staging.yaml`,
  `sample/config-staging-rvabrep.yaml`,
  `sample/config-staging-rvabrep-heavy-nolanes.yaml`,
  `sample/config-staging-rvabrep-heavy-lanes.yaml`,
  `sample/config-staging-localscan.yaml`,
  `sample/config-staging-singledoc.yaml`
  - ``indexing:\n  csv_path: X`` →
    ``indexing:\n  source:\n    kind: csv\n    csv_path: X``.
- ~17 archivos de test de integración que construyen YAML inline
  (helpers ``_common_blocks`` / ``_write_*_yaml``): mismo
  transform. Una pasada con script de ``python`` maneja el
  patrón uniforme; los rezagados se arreglan a mano.
- `tests/unit/config/test_loader.py` — cualquier fixture YAML con
  la forma vieja.
- Borrar el `sample/config-staging-rvabrep.yaml` separado
  ``config-staging-as400.yaml`` si existe (no se observó —
  confirmar).

### Tests

- Suite completa unit + integration verde después de la
  migración. Sin tests nuevos acá — la Fase 1 agregó la
  cobertura; la Fase 2 es mecánica.

### Commit

```
test(config): migrate all configs + fixtures to indexing.source shape (048 Phase 2)
```

## Fase 3 — Docs + CHANGELOG 0.51.0 + bump de versión + re-verify en vivo + FF (~30 min)

### Archivos

- `CHANGELOG.md` ``[0.51.0]`` — Added (fuente RVABREP pluggable),
  Changed (``indexing.csv_path`` → ``indexing.source``; kind de
  trigger ``as400`` removido), Removed
  (``As400TriggerStrategy``, ``As400TriggerConfig``).
- `pyproject.toml` 0.50.0 → 0.51.0.
- Tick en fila de features de `README.md`.
- `docs/how-to/validation-checklist.md` — §0.3 tabla de config +
  §E.3 (la sección "as400-trigger") actualizada: §E.3 pasa a ser
  "run del pipeline rvabrep con ``indexing.source.kind: as400``".
- `docs/how-to/local-staging-simulation.md` — si muestra un
  snippet de ``indexing.csv_path``, migrarlo.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.51.0
```

### Re-verify en vivo (variante CSV — el gate de regresión)

```bash
bash scripts/staging/wipe-alfresco-docs.sh
rm -f sample/staging-tracking.db sample/staging-tracking.db-wal sample/staging-tracking.db-shm

CMIS_USERNAME=admin CMIS_PASSWORD=admin .venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml --total 5 --no-tui
```

Aceptación: misma forma que el verify de 047 — 5 triggers, 5
docs, ``s5_done=5 s5_failed=0``, ``cm_object_id`` poblado. El
config migrado se comporta byte-idéntico a pre-048.

### Commit

```
docs(048): CHANGELOG 0.51.0 + version bump + indexing.source migration verify (048 Phase 3)
```

### FF a main.

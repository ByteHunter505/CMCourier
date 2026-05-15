# 048 — Tasks

## Fase 1 — Schema + wiring + borrar As400TriggerStrategy

- [ ] 1.1 Union discriminada ``CsvRvabrepSource`` / ``As400RvabrepSource``
      + ``RvabrepSourceUnion`` en ``schema.py``.
- [ ] 1.2 Renombrar ``IndexingSourceConfig`` → ``IndexingConfig``;
      campo ``csv_path`` → ``source: RvabrepSourceUnion``.
- [ ] 1.3 Remover ``As400TriggerConfig`` del ``TriggerConfigUnion``;
      agregar un error amigable del loader para
      ``trigger.kind: as400``.
- [ ] 1.4 ``wiring.py``: ``_build_rvabrep_source(indexing_cfg,
      secrets)`` despachando csv/as400.
- [ ] 1.5 ``build_pipeline`` construye la fuente una vez, alimenta
      ``IndexingService`` + ``_build_trigger_strategy``.
- [ ] 1.6 ``_build_trigger_strategy``: descartar la rama de
      ``As400TriggerConfig`` + el import.
- [ ] 1.7 Borrar ``services/triggers/as400.py``; descartar exports
      de ``services/triggers/__init__.py`` +
      ``services/__init__.py``.
- [ ] 1.8 ``cli/app.py``: confirmar + remover/aliasear el comando
      CLI ``as400-trigger-pipeline``.
- [ ] 1.9 Tests unitarios: variantes csv / as400 del loader +
      rechazo de ``trigger.kind: as400``.
- [ ] 1.10 Tests de integración: ``_build_rvabrep_source`` csv +
      as400.
- [ ] 1.11 Borrar tests apuntados a ``As400TriggerStrategy``.
- [ ] 1.12 mypy + ruff limpios.
- [ ] 1.13 Commit
      ``feat(config,wiring): pluggable RVABREP source (CSV ↔ AS400); drop as400 trigger kind (048 Phase 1)``.

## Fase 2 — Migrar todos los configs + fixtures + tests

- [ ] 2.1 Migrar los 6 configs ``sample/config-staging*.yaml`` a
      ``indexing.source``.
- [ ] 2.2 Migrar el YAML inline de los ~17 archivos de tests de
      integración (pasada scripteada para el patrón uniforme +
      hand-fix de rezagados).
- [ ] 2.3 Migrar el fixture YAML de
      ``tests/unit/config/test_loader.py``.
- [ ] 2.4 Suite completa unit + integration verde.
- [ ] 2.5 ruff + mypy limpios.
- [ ] 2.6 Commit
      ``test(config): migrate all configs + fixtures to indexing.source shape (048 Phase 2)``.

## Fase 3 — docs + CHANGELOG 0.51.0 + bump de versión + re-verify en vivo + FF

- [ ] 3.1 ``CHANGELOG.md [0.51.0]`` — Added / Changed / Removed.
- [ ] 3.2 ``pyproject.toml`` 0.50.0 → 0.51.0.
- [ ] 3.3 ``.venv/bin/pip install -e . --no-deps``.
- [ ] 3.4 ``cmcourier --version`` reporta 0.51.0.
- [ ] 3.5 Tick en fila de features de ``README.md``.
- [ ] 3.6 ``docs/how-to/validation-checklist.md`` §0.3 + §E.3
      actualizados para la nueva forma de la fuente.
- [ ] 3.7 ``docs/how-to/local-staging-simulation.md`` — migrar
      cualquier snippet de ``indexing.csv_path``.
- [ ] 3.8 Re-verify en vivo: run de 5 docs con
      ``config-staging-rvabrep.yaml``, misma forma que el verify
      de 047.
- [ ] 3.9 Suite completa + ruff + mypy limpios.
- [ ] 3.10 Commit
      ``docs(048): CHANGELOG 0.51.0 + version bump + indexing.source migration verify (048 Phase 3)``.
- [ ] 3.11 FF a main.

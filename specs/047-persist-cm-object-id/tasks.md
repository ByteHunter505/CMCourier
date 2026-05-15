# 047 — Tasks

## Fase 1 — Pasar cm_object_id a través de mark_stage_done

- [ ] 1.1 ``ITrackingStore.mark_stage_done`` — agregar keyword-only
      ``cm_object_id: str | None = None``.
- [ ] 1.2 ``SQLiteTrackingStore.mark_stage_done`` — incluir la
      columna ``cm_object_id`` en el UPDATE solo cuando el arg no
      es None; camino None sin cambios.
- [ ] 1.3 ``IdempotencyCoordinator.mark_uploaded`` — reenviar
      ``cm_object_id`` a la llamada ``mark_stage_done`` de SQLite.
- [ ] 1.4 La llamada non-coordinator de S5_DONE en ``staged.py`` pasa
      ``cm_object_id=cm_object_id``.
- [ ] 1.5 Test de integración: ``mark_stage_done`` con OID persiste
      la columna.
- [ ] 1.6 Test de integración: ``mark_stage_done`` sin OID deja
      la columna.
- [ ] 1.7 Test unitario: el coordinator reenvía el kwarg.
- [ ] 1.8 Actualizar cualquier test que assertee la firma en
      ``test_ports.py`` / ``test_idempotency.py``.
- [ ] 1.9 mypy + ruff limpios. Suite completa verde.
- [ ] 1.10 Commit
      ``fix(tracking): persist cm_object_id on S5_DONE transition (047 Phase 1)``.

## Fase 2 — docs + CHANGELOG 0.50.0 + bump de versión + re-verify en vivo + FF

- [ ] 2.1 ``CHANGELOG.md [0.50.0]`` — Fixed (cm_object_id nunca
      persistido).
- [ ] 2.2 ``pyproject.toml`` 0.49.0 → 0.50.0.
- [ ] 2.3 ``.venv/bin/pip install -e . --no-deps``.
- [ ] 2.4 ``cmcourier --version`` reporta 0.50.0.
- [ ] 2.5 Tick en fila de features de ``README.md``.
- [ ] 2.6 ``docs/how-to/validation-checklist.md`` §L.3 — sacar la
      nota de known-issue, restaurar el camino de query a la
      tracking DB.
- [ ] 2.7 Re-verify en vivo: run de 5 docs → cada fila S5_DONE tiene
      ``cm_object_id`` no-NULL.
- [ ] 2.8 Suite completa unit + integration verde; ruff + mypy limpios.
- [ ] 2.9 Commit
      ``docs(047): CHANGELOG 0.50.0 + version bump + cm_object_id re-verify (047 Phase 2)``.
- [ ] 2.10 FF a main.

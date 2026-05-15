# 044 — Tasks

## Fase 1 — reescritura del algoritmo de _apply_resume

- [ ] 1.1 Re-ordenar ``_apply_resume`` según la spec: validar inputs →
      ``--from-stage`` explícito honrado → auto-detectar → clean.
- [ ] 1.2 Agregar detección de gap: para cada stage N<5, si
      ``stage_counts[S{N}][DONE] > 0`` Y ningún stage anterior tiene
      FAILED/PENDING, resolved = N+1.
- [ ] 1.3 Test unitario: FAILED en S3 + DONE en S4 → resuelve a 3.
- [ ] 1.4 Test unitario: S4_DONE=543, S5_DONE=281 → resuelve a 5.
- [ ] 1.5 Test unitario: solo S5_DONE → "Nothing to resume" + exit 0.
- [ ] 1.6 Test unitario: batch clean + explicit_from_stage=5 →
      devuelve 5 (sin early exit).
- [ ] 1.7 Test unitario: batch_id desconocido → exit 1 + "Batch not found".
- [ ] 1.8 mypy + ruff limpios.
- [ ] 1.9 Commit
      ``fix(cli): resume detects S{N}_DONE→S{N+1} stage gaps + honors explicit --from-stage (044 Phase 1)``.

## Fase 2 — --batch-id siempre pasado

- [ ] 2.1 Descartar el condicional ``if resume_flag else None`` en la
      asignación de ``resume_batch_id``.
- [ ] 2.2 Actualizar el comentario inline que documenta la nueva
      semántica.
- [ ] 2.3 Test de integración: ``--batch-id X`` (sin ``--resume``)
      corre y usa X como el batch_id literal.
- [ ] 2.4 mypy + ruff limpios.
- [ ] 2.5 Commit
      ``fix(cli): --batch-id always threads to the orchestrator (044 Phase 2)``.

## Fase 3 — docs + CHANGELOG 0.47.0 + bump de versión + re-verify en vivo + FF

- [ ] 3.1 ``CHANGELOG.md [0.47.0]`` Fixed (3 bugs por id) + Changed
      (algoritmo + semántica).
- [ ] 3.2 ``pyproject.toml`` 0.46.0 → 0.47.0.
- [ ] 3.3 ``.venv/bin/pip install -e . --no-deps`` — refrescar
      metadata.
- [ ] 3.4 ``cmcourier --version`` reporta 0.47.0.
- [ ] 3.5 Tick en fila de features de ``README.md``.
- [ ] 3.6 Re-verify en vivo contra staging: kill-mid-S5 + resume.
- [ ] 3.7 Suite unitaria completa + ruff + mypy limpios.
- [ ] 3.8 Commit
      ``docs(044): CHANGELOG 0.47.0 + version bump + resume live re-verify (044 Phase 3)``.
- [ ] 3.9 FF a main.

# 071 — Tasks

Branch: `feat/071-spanish-comments-no-rebirth`.

## Fase 1 — Quitar REBIRTH

- [ ] T1. Listar archivos con `REBIRTH` en código, specs, CHANGELOG, README, docs/
- [ ] T2. Por archivo, reemplazar / quitar las menciones
- [ ] T3. `rg -i "rebirth" .` → cero hits
- [ ] T4. Verificación: `pytest -q`, `ruff check`, `mypy`
- [ ] T5. Commit `refactor: remove REBIRTH references (071 Phase 1)`

## Fase 2 — Traducir orchestrators + adapters (yo)

- [ ] T6. Traducir 5 archivos en `orchestrators/`
- [ ] T7. Traducir ~12 archivos en `adapters/`
- [ ] T8. Verificar `ruff` + `mypy` + spot-check
- [ ] T9. Commit `refactor: translate orchestrators + adapters to Spanish (071 Phase 2)`

## Fase 3 — Sub-agentes: services/domain/config/cli/tui/observability

- [ ] T10. Spawn 6 sub-agentes en paralelo
- [ ] T11. Recolectar resultados
- [ ] T12. Verificar `ruff` + `mypy`
- [ ] T13. Commit por módulo o consolidado

## Fase 4 — Sub-agentes: tests/

- [ ] T14. Spawn 2 sub-agentes (unit + integration)
- [ ] T15. Verificar `pytest -q` corre verde
- [ ] T16. Commit `refactor: translate tests to Spanish (071 Phase 4)`

## Fase 5 — Sub-agente: specs + CHANGELOG + README

- [ ] T17. Spawn sub-agente con las tres tareas
- [ ] T18. Commit `docs: translate specs + CHANGELOG + README to Spanish (071 Phase 5)`

## Fase 6 — Verificación + release

- [ ] T19. `rg -i "rebirth" .` → cero
- [ ] T20. Pytest completo verde
- [ ] T21. ruff + mypy limpios
- [ ] T22. CHANGELOG `[0.73.0]`
- [ ] T23. pyproject 0.72.0 → 0.73.0
- [ ] T24. `pip install -e . --no-deps` + version verify
- [ ] T25. README feature row tick
- [ ] T26. Commit + FF a main

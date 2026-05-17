# 078 — Tasks

## Fase 1 — Spec

- [x] 1.1 spec.md
- [x] 1.2 plan.md
- [x] 1.3 tasks.md

## Fase 2 — Implementación

- [ ] 2.1 Agregar `render_bar_chart` a `src/cmcourier/tui/chart.py`.
- [ ] 2.2 Importar `render_bar_chart` en `src/cmcourier/tui/upload_tab.py`.
- [ ] 2.3 Reemplazar el bloque del sparkline por el bar chart en `upload_tab.py`.

## Fase 3 — Tests

- [ ] 3.1 `tests/unit/tui/test_chart_bar.py` con 7 tests.
- [ ] 3.2 Tests existentes de `upload_tab` (si los hay) siguen pasando.
- [ ] 3.3 `pytest -m unit` sin regresiones.

## Fase 4 — CHANGELOG + bump

- [ ] 4.1 CHANGELOG entry `[0.80.0]`.
- [ ] 4.2 pyproject.toml `0.79.0` → `0.80.0`.
- [ ] 4.3 `pip install -e . --no-deps`.

## Fase 5 — Commits + push

- [ ] 5.1 5 commits phased.
- [ ] 5.2 `git push origin main`.

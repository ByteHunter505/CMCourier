# 079 — Tasks

- [x] 1.1 spec.md
- [x] 1.2 plan.md
- [x] 1.3 tasks.md

## Fase 2 — Implementación

- [ ] 2.1 Crear `src/cmcourier/observability/network_info.py` con `detect_link_speed_mbps`.
- [ ] 2.2 Modificar `chart.py`: barras pegadas + Y axis labels.
- [ ] 2.3 Modificar `data_provider.py`: cachear ceiling con prioridad config → NIC → auto-scale.
- [ ] 2.4 Modificar `upload_tab.py`: alinear el footer con el nuevo width.

## Fase 3 — Tests

- [ ] 3.1 `tests/unit/observability/test_network_info.py`.
- [ ] 3.2 `tests/unit/tui/test_chart_bar_y_axis.py`.
- [ ] 3.3 `pytest -m unit` sin regresiones.

## Fase 4 — CHANGELOG + bump

- [ ] 4.1 CHANGELOG `[0.81.0]`.
- [ ] 4.2 pyproject.toml `0.80.0` → `0.81.0`.
- [ ] 4.3 `pip install -e . --no-deps`.

## Fase 5 — Commits + push

- [ ] 5.1 6 commits phased.
- [ ] 5.2 `git push origin main`.

# 036 — Tareas

## Fase 1: esquema + LaneSplitter

- [ ] 1.1 Modelo pydantic `HeavyLightLanesConfig` + anidado en
      `ProcessingConfig.heavy_light_lanes` con `default-factory`.
      Tests: valores por defecto + bordes de los validadores.
- [ ] 1.2 `services/lane_splitter.py`: función pura `split()`,
      dataclass `LaneAssignment`.
- [ ] 1.3 `tests/unit/services/test_lane_splitter.py`: `batch`
      pequeño, bimodal, todos pequeños, todos grandes, preservación
      del orden.
- [ ] 1.4 Suite completa en verde; `mypy` + `ruff` limpios.
- [ ] 1.5 Commit `feat(config,services): HeavyLightLanesConfig + LaneSplitter (036 Phase 1)`.

## Fase 2: LaneController + S5 con pool dual

- [ ] 2.1 `services/lane_controller.py`: dos `ResizableSemaphore`,
      `thread` daemon de `rebalance`, `set_total_budget`,
      `acquire`/`release`, eventos estructurados de log de
      `rebalance`.
- [ ] 2.2 Tests unitarios (`test_lane_controller.py`): asignación,
      preservación del ratio bajo `AIMD`, migración disparada por
      drenado con `clock` mockeado, eventos de log de `rebalance`.
- [ ] 2.3 `StagedPipeline.__init__`: construir `LaneController`
      cuando `heavy_light_lanes.enabled`. Mantener el camino de
      pool único cuando está apagado.
- [ ] 2.4 `_stage_5`: cuando el modo dual está activo Y el
      `splitter` dice "no es único `lane`", despachar por `lane`;
      de lo contrario, camino legado.
- [ ] 2.5 `on_workers_change` de `AIMD` reenvía a
      `LaneController.set_total_budget` cuando el modo dual está
      activo.
- [ ] 2.6 `tests/integration/pipeline/test_dual_lane_s5.py`:
      `batch` bimodal `happy-path` + regresión con `enabled=False`.
- [ ] 2.7 Suite completa en verde; `mypy` + `ruff` limpios.
- [ ] 2.8 Commit `feat(pipeline): LaneController + dual-lane S5 (AIMD-coupled) (036 Phase 2)`.

## Fase 3: sub-paneles duales de TUI

- [ ] 3.1 `tui/data_provider.py`: exponer `LaneSnapshot`
      (heavy/light) cuando el controlador está presente.
- [ ] 3.2 El widget UPLOAD renderiza sub-paneles HEAVY/LIGHT
      cuando el modo dual está activo; de lo contrario, panel
      único legado.
- [ ] 3.3 Evento de `rebalance` → notificación de TUI vía
      `notify` de Textual.
- [ ] 3.4 `tests/integration/tui/test_dual_lane_panels.py`:
      `snapshot` de ambos modos.
- [ ] 3.5 Suite completa en verde.
- [ ] 3.6 Commit `feat(tui): dual heavy/light UPLOAD sub-panels + rebalance notifications (036 Phase 3)`.

## Fase 4: prueba de throughput + property test de ancho de banda + docs + FF

- [ ] 4.1 `tests/integration/pipeline/test_dual_lane_throughput.py`:
      `batch` sintético bimodal, uploader `mock` de 50 ms/MB,
      `dual_time ≤ single_time * 0.7`. `@pytest.mark.slow` si es
      inestable.
- [ ] 4.2 `tests/property/test_bandwidth_dual_lane.py`: hypothesis
      sobre `batches` bimodales aleatorios; el limitador de ancho
      de banda se mantiene.
- [ ] 4.3 `docs/how-to/heavy-light-lanes.md`: guía del operador.
- [ ] 4.4 `CHANGELOG.md` `[0.37.0]`, tilde del README, POST-MVP §1
      marcado como SHIPPED.
- [ ] 4.5 Suite completa en verde; `mypy` + `ruff` limpios.
- [ ] 4.6 Commit `docs(036): heavy/light lanes how-to + CHANGELOG 0.37.0 + POST-MVP §1 SHIPPED (036 Phase 4)`.
- [ ] 4.7 Merge FF a `main`; eliminar la rama.

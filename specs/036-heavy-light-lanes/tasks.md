# 036 — Tasks

## Phase 1: schema + LaneSplitter

- [ ] 1.1 `HeavyLightLanesConfig` pydantic model + nested in
      `ProcessingConfig.heavy_light_lanes` with default-factory.
      Tests: defaults + validator boundaries.
- [ ] 1.2 `services/lane_splitter.py`: `split()` pure function,
      `LaneAssignment` dataclass.
- [ ] 1.3 `tests/unit/services/test_lane_splitter.py`: small batch,
      bimodal, all small, all large, order preservation.
- [ ] 1.4 Full suite green; mypy + ruff clean.
- [ ] 1.5 Commit `feat(config,services): HeavyLightLanesConfig + LaneSplitter (036 Phase 1)`.

## Phase 2: LaneController + dual-pool S5

- [ ] 2.1 `services/lane_controller.py`: two `ResizableSemaphore`s,
      rebalance daemon thread, `set_total_budget`,
      `acquire`/`release`, structured rebalance log events.
- [ ] 2.2 Unit tests (`test_lane_controller.py`): allocation, AIMD
      ratio preservation, drain-driven migration with mocked clock,
      rebalance log events.
- [ ] 2.3 `StagedPipeline.__init__`: build `LaneController` when
      `heavy_light_lanes.enabled`. Keep single-pool path when off.
- [ ] 2.4 `_stage_5`: when dual mode active AND splitter says
      not-single-lane, dispatch by lane; otherwise legacy path.
- [ ] 2.5 AIMD `on_workers_change` forwards to
      `LaneController.set_total_budget` when dual mode is on.
- [ ] 2.6 `tests/integration/pipeline/test_dual_lane_s5.py`: bimodal
      batch happy-path + regression with `enabled=False`.
- [ ] 2.7 Full suite green; mypy + ruff clean.
- [ ] 2.8 Commit `feat(pipeline): LaneController + dual-lane S5 (AIMD-coupled) (036 Phase 2)`.

## Phase 3: TUI dual sub-panels

- [ ] 3.1 `tui/data_provider.py`: surface `LaneSnapshot`
      (heavy/light) when controller is present.
- [ ] 3.2 UPLOAD widget renders HEAVY/LIGHT sub-panels when dual
      mode active; legacy single panel otherwise.
- [ ] 3.3 Rebalance event → TUI notification via Textual `notify`.
- [ ] 3.4 `tests/integration/tui/test_dual_lane_panels.py`: snapshot
      both modes.
- [ ] 3.5 Full suite green.
- [ ] 3.6 Commit `feat(tui): dual heavy/light UPLOAD sub-panels + rebalance notifications (036 Phase 3)`.

## Phase 4: throughput proof + bandwidth property test + docs + FF

- [ ] 4.1 `tests/integration/pipeline/test_dual_lane_throughput.py`:
      bimodal synthetic batch, 50 ms/MB mock uploader,
      `dual_time ≤ single_time * 0.7`. `@pytest.mark.slow` if flaky.
- [ ] 4.2 `tests/property/test_bandwidth_dual_lane.py`: hypothesis
      over random bimodal batches; bandwidth limiter holds.
- [ ] 4.3 `docs/how-to/heavy-light-lanes.md`: operator guide.
- [ ] 4.4 `CHANGELOG.md` `[0.37.0]`, README tick, POST-MVP §1 mark
      SHIPPED.
- [ ] 4.5 Full suite green; mypy + ruff clean.
- [ ] 4.6 Commit `docs(036): heavy/light lanes how-to + CHANGELOG 0.37.0 + POST-MVP §1 SHIPPED (036 Phase 4)`.
- [ ] 4.7 FF merge to `main`; delete branch.

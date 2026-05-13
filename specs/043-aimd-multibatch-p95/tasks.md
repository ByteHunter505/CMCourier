# 043 — Tasks

## Phase 1 — AutoTuneController.set_p95_provider

- [ ] 1.1 ``set_p95_provider(provider)`` public method on
      ``AutoTuneController``. Atomic attribute swap; no thread
      restart.
- [ ] 1.2 ``_tick`` reads ``self._p95_provider`` through the
      attribute so a swap takes effect immediately on the next tick.
- [ ] 1.3 Unit test: swap mid-life, next tick observes the new
      provider's return value.
- [ ] 1.4 mypy + ruff clean.
- [ ] 1.5 Commit
      ``feat(services): AutoTuneController.set_p95_provider swap hook (043 Phase 1)``.

## Phase 2 — multi-batch wires the upload-recorder p95 source

- [ ] 2.1 ``MultiBatchOrchestrator._upload_p95_observer()`` reads
      from ``self.upload_recorder()`` and returns
      ``current_stage_p95("S5")`` or ``0.0``.
- [ ] 2.2 ``_run_overlapped._upload_loop`` calls
      ``controller.set_p95_provider(self._upload_p95_observer)``
      before ``controller.start()``.
- [ ] 2.3 Unit test: with a fake ``p95_provider`` set on a mocked
      controller, the orchestrator overrides it on overlap start.
- [ ] 2.4 mypy + ruff clean.
- [ ] 2.5 Commit
      ``fix(orchestrators): multi-batch AIMD reads p95 from upload-active recorder (043 Phase 2)``.

## Phase 3 — docs + CHANGELOG 0.46.0 + version bump + verify + FF

- [ ] 3.1 ``CHANGELOG.md [0.46.0]`` entry — Fixed (AIMD p95 read
      path), Changed (set_p95_provider added).
- [ ] 3.2 ``pyproject.toml`` 0.45.0 → 0.46.0.
- [ ] 3.3 ``pip install -e . --no-deps`` — refresh metadata.
- [ ] 3.4 ``cmcourier --version`` reports 0.46.0.
- [ ] 3.5 ``README.md`` feature row tick.
- [ ] 3.6 Re-run §F.4 (``--total 200 --batches-in-flight 2``).
- [ ] 3.7 Grep ``auto_tune_decision`` events; assert at least one
      has ``p95_observed_ms > 0``.
- [ ] 3.8 Full unit suite + ruff + mypy clean.
- [ ] 3.9 Commit
      ``docs(043): CHANGELOG 0.46.0 + version bump + AIMD live re-verify (043 Phase 3)``.
- [ ] 3.10 FF to main.

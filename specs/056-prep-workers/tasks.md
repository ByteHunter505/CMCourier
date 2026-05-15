# 056 — Tasks

## Phase 1 — prep_workers config + parallelize S2/S3/S4 + tests

- [x] 1.1 `config/schema.py`: `ProcessingConfig.prep_workers: int =
      Field(default=1, ge=1)`.
- [x] 1.2 `staged.py`: `__init__` takes `prep_workers: int = 1`,
      stores `self._prep_workers`.
- [x] 1.3 `staged.py`: extract `_s2_one` / `_s3_one` / `_s4_one`
      per-item helpers returning `tuple[_StageItem | None, bool]`
      (survivor, counted-failure) — domain exceptions caught inside.
- [x] 1.4 `staged.py`: `_run_prep_stage(items, worker)` dispatch —
      serial when `prep_workers == 1`, `ThreadPoolExecutor` +
      `pool.map` (order-preserving) when `> 1`.
- [x] 1.5 `staged.py`: `_stage_s2` / `_stage_s3` / `_stage_s4` become
      thin wrappers over `_run_prep_stage`.
- [x] 1.6 Wiring layer (`config/wiring.py`) passes
      `config.processing.prep_workers` to `StagedPipeline(...)`.
- [x] 1.7 Tests: default=1 + reject `<1` (`test_schema.py`); the
      6-doc fixture run is byte-identical serial vs 4-thread —
      parametrized over `prep_workers ∈ {1, 4}`, asserting the same
      per-stage failure counts (S2/S3/S4 each fail one) + S5_DONE=3,
      which proves ordering + no double-counting.
- [x] 1.8 Full unit + integration suite green (1212 passed); mypy +
      ruff clean.
- [x] 1.9 Commit
      `feat(prep): configurable prep_workers — parallelize S2/S3/S4 on a fixed thread pool (056 Phase 1)`.

## Phase 2 — CHANGELOG 0.59.0 + version bump + docs + FF

- [ ] 2.1 `CHANGELOG.md [0.59.0]` — Added.
- [ ] 2.2 `pyproject.toml` 0.58.0 → 0.59.0.
- [ ] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 2.4 `cmcourier --version` reports 0.59.0.
- [ ] 2.5 `README.md` feature row tick.
- [ ] 2.6 `docs/samples/config-reference.yaml` documents
      `processing.prep_workers`.
- [ ] 2.7 Full suite + ruff + mypy clean.
- [ ] 2.8 Commit
      `docs(056): CHANGELOG 0.59.0 + version bump + prep_workers config docs (056 Phase 2)`.
- [ ] 2.9 FF to main.

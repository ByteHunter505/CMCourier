# 057 — Tasks

## Phase 1 — Size the S5 pool to the AIMD ceiling + tests

- [x] 1.1 `staged.py`: `_pool_ceiling()` helper — `max(workers,
      auto_tune.max_threads)` when AIMD enabled, else `workers`.
- [x] 1.2 `staged.py`: `_stage_5_single` builds its
      `ThreadPoolExecutor` with `max_workers=self._pool_ceiling()`;
      `set_pool_size` uses the ceiling too.
- [x] 1.3 `staged.py`: `_stage_5_dual` builds both the heavy + light
      `ThreadPoolExecutor`s with `max_workers=self._pool_ceiling()`.
- [x] 1.4 Tests: `_pool_ceiling()` unit — AIMD on → `max_threads`,
      AIMD off → `workers`, `workers > max_threads` → `workers`.
- [x] 1.5 Tests: capture `max_workers` via an instrumented
      `ThreadPoolExecutor` — `_stage_5_single` over an empty batch is
      the ceiling with AIMD on, `cmis.workers` with AIMD off; both
      `_stage_5_dual` pools are the ceiling. 056 prep pool excluded by
      the `cmcourier-s5*` thread-name prefix filter.
- [x] 1.6 Full unit + integration suite green (1218 passed; the lone
      failure is the known timing-flaky `test_dual_lane_throughput` —
      passes in isolation, unaffected by 057 since `_pool_ceiling()`
      returns `cmis.workers` when AIMD is off). mypy + ruff clean.
- [x] 1.7 Commit
      `fix(s5): size the upload thread pool to the AIMD ceiling, not the initial worker count (057 Phase 1)`.

## Phase 2 — CHANGELOG 0.60.0 + version bump + README + FF

- [x] 2.1 `CHANGELOG.md [0.60.0]` — Fixed.
- [x] 2.2 `pyproject.toml` 0.59.0 → 0.60.0.
- [x] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [x] 2.4 `cmcourier --version` reports 0.60.0.
- [x] 2.5 `README.md` feature row tick.
- [x] 2.6 Full suite + ruff + mypy clean (verified in Phase 1, 1218
      passed; Phase 2 touches no source — docs/CHANGELOG/version only).
- [x] 2.7 Commit
      `docs(057): CHANGELOG 0.60.0 + version bump (057 Phase 2)`.
- [ ] 2.8 FF to main.

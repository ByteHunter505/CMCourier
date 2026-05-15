# 057 — Tasks

## Phase 1 — Size the S5 pool to the AIMD ceiling + tests

- [ ] 1.1 `staged.py`: `_pool_ceiling()` helper — `max(workers,
      auto_tune.max_threads)` when AIMD enabled, else `workers`.
- [ ] 1.2 `staged.py`: `_stage_5_single` builds its
      `ThreadPoolExecutor` with `max_workers=self._pool_ceiling()`;
      `set_pool_size` uses the ceiling too.
- [ ] 1.3 `staged.py`: `_stage_5_dual` builds both the heavy + light
      `ThreadPoolExecutor`s with `max_workers=self._pool_ceiling()`.
- [ ] 1.4 Tests: `_pool_ceiling()` unit — AIMD on → `max_threads`,
      AIMD off → `workers`, `workers > max_threads` → `workers`.
- [ ] 1.5 Tests: capture `max_workers` on a real run — S5 single pool
      is the ceiling with AIMD on, `cmis.workers` with AIMD off; both
      dual pools are the ceiling. Prep (056) pools excluded by
      thread-name prefix.
- [ ] 1.6 Full unit + integration suite green; mypy + ruff clean.
- [ ] 1.7 Commit
      `fix(s5): size the upload thread pool to the AIMD ceiling, not the initial worker count (057 Phase 1)`.

## Phase 2 — CHANGELOG 0.60.0 + version bump + README + FF

- [ ] 2.1 `CHANGELOG.md [0.60.0]` — Fixed.
- [ ] 2.2 `pyproject.toml` 0.59.0 → 0.60.0.
- [ ] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 2.4 `cmcourier --version` reports 0.60.0.
- [ ] 2.5 `README.md` feature row tick.
- [ ] 2.6 Full suite + ruff + mypy clean.
- [ ] 2.7 Commit
      `docs(057): CHANGELOG 0.60.0 + version bump (057 Phase 2)`.
- [ ] 2.8 FF to main.

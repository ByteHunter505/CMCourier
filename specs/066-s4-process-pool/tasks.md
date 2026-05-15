# 066 — Tasks

Branch: `feat/066-s4-process-pool`.

## Phase 1

- [ ] T1. `config/schema.py` — add `s4_use_processes: bool = True` and
      `s4_max_processes: int | None = None` to `ProcessingConfig`
- [ ] T2. New `adapters/assembly/pool.py` with module-level
      `_pool_init`, `_pool_assemble`, and `build_s4_process_pool`
- [ ] T3. `orchestrators/staged.py` — `StagedPipeline.__init__` accepts
      `s4_process_pool: ProcessPoolExecutor | None`; `_s4_one`
      dispatches via pool when present
- [ ] T4. `config/wiring.py` — construct the pool when configured,
      pass to pipeline, register shutdown via atexit
- [ ] T5. Tests:
  - config schema defaults + ge=1 validation
  - pool helpers picklable + import-stable
  - `_s4_one` dispatches to pool when present
  - `_s4_one` falls back to direct call when pool is None
  - integration streaming run with `s4_use_processes=true`
- [ ] T6. Run full unit + integration suite green
- [ ] T7. ruff + mypy clean
- [ ] T8. Commit:
  - `feat(assembly): S4 in ProcessPoolExecutor for real CPU-bound parallelism (066 Phase 1)`

## Phase 2

- [ ] T9. CHANGELOG `[0.68.0]`
- [ ] T10. pyproject 0.67.0 → 0.68.0
- [ ] T11. `pip install -e . --no-deps` + version verify
- [ ] T12. README feature row tick
- [ ] T13. Commit `docs(066): CHANGELOG 0.68.0 + version bump (066 Phase 2)`
- [ ] T14. FF to main

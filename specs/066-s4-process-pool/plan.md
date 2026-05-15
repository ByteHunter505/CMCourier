# 066 — Plan

Two phases.

## Phase 1 — pool module + pipeline wiring + tests

### Files

- `src/cmcourier/config/schema.py`
  - `ProcessingConfig.s4_use_processes: bool = True`
  - `ProcessingConfig.s4_max_processes: int | None = None` (with
    `Field(default=None, ge=1)`)

- `src/cmcourier/adapters/assembly/pool.py` (new)
  - Module-level `_worker_assembler` global
  - `_pool_init(config: AssemblerConfig) -> None`
  - `_pool_assemble(document: RVABREPDocument) -> StagedFile`
  - `build_s4_process_pool(config: AssemblerConfig, max_workers: int | None) -> ProcessPoolExecutor`

- `src/cmcourier/orchestrators/staged.py`
  - `StagedPipeline.__init__` accepts `s4_process_pool: ProcessPoolExecutor | None = None`
  - `_s4_one`: when pool present, `staged = self._s4_process_pool.submit(_pool_assemble, item.document).result()`
  - The `_s4_one` keeps the StageTimer wrapper, so the latency is
    still recorded on the recorder.

- `src/cmcourier/config/wiring.py`
  - When `cfg.processing.s4_use_processes`: construct the pool via
    `build_s4_process_pool(...)` and pass it to `StagedPipeline`.
  - The pool's `shutdown(wait=True)` needs a lifecycle hook — for
    Phase 1, the wiring layer registers it via `atexit` (simplest).
    A follow-up can move it to a pipeline `close()` method.

### Tests

- `tests/unit/config/test_schema.py`
  - `processing.s4_use_processes` defaults to True
  - `processing.s4_max_processes` defaults to None, rejects 0

- `tests/unit/adapters/assembly/test_pool.py` (new)
  - `_pool_init` then `_pool_assemble` works end-to-end (run in the
    same process — just verifies the helpers are correct)
  - `_pool_assemble` is importable + picklable

- `tests/integration/pipeline/test_streaming_pipeline.py`
  - `test_streaming_with_s4_process_pool` — small fixture with the
    pool enabled, asserts same `s5_done` count as without

- `tests/unit/orchestrators/test_staged_pool_ceiling.py` (or new file)
  - `_s4_one` dispatches via pool when pool is provided
  - `_s4_one` falls back to direct assembly when pool is None

### Verify

`pytest tests/unit tests/integration -q`. ruff + mypy clean.

### Commit

```
feat(assembly): S4 in ProcessPoolExecutor for real CPU-bound parallelism (066 Phase 1)
```

## Phase 2 — release

- CHANGELOG `[0.68.0]`
- pyproject 0.67.0 → 0.68.0
- `.venv/bin/pip install -e . --no-deps` + version verify
- README feature row tick
- FF to main

Commit: `docs(066): CHANGELOG 0.68.0 + version bump + s4-pool docs (066 Phase 2)`.

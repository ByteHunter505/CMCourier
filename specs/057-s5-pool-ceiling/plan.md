# 057 — Plan

Two phases (~1 h total). One source file, surgical.

## Phase 1 — Size the S5 pool to the AIMD ceiling + tests (~40 min)

### Files

- `src/cmcourier/orchestrators/staged.py`
  - New helper `_pool_ceiling(self) -> int`:
    ```python
    if self._auto_tune_cfg is not None and self._auto_tune_cfg.enabled:
        return max(self._workers, self._auto_tune_cfg.max_threads)
    return self._workers
    ```
  - `_stage_5_single` — `ThreadPoolExecutor(max_workers=self._pool_ceiling(), ...)`;
    `self._pool_stats.set_pool_size(self._pool_ceiling())` (was
    `self._workers`).
  - `_stage_5_dual` — both `heavy_pool` and `light_pool`
    `ThreadPoolExecutor(max_workers=self._pool_ceiling(), ...)`. The
    `LaneController` already owns the per-lane caps + AIMD budget
    resize — no change there.
  - No other call sites: `grep` confirms `ThreadPoolExecutor` in
    `staged.py` appears in `_run_prep_stage` (056 — prep, unrelated),
    `_stage_5_single`, `_stage_5_dual`.

### Tests

- `tests/unit/orchestrators/` (or wherever `StagedPipeline` unit tests
  live) — `test_pool_ceiling`:
  - AIMD enabled, `max_threads=16`, `cmis.workers=4` → `16`.
  - AIMD disabled → `cmis.workers`.
  - `cmis.workers=20`, `max_threads=8` → `20` (the `max(...)` guard).
  Build a minimal `StagedPipeline` (fakes/stubs for collaborators) or
  test via a thin construction; if a builder fixture exists, reuse it.

- `tests/integration/pipeline/test_s5_worker_pool.py` —
  `TestS5PoolCeiling057`:
  - `test_single_pool_sized_to_ceiling_when_auto_tune_enabled` —
    patch `cmcourier.orchestrators.staged.ThreadPoolExecutor` with a
    recording wrapper that captures `max_workers` then delegates to
    the real class; run a real CLI pipeline (the existing
    `_write_yaml` / `_stub_cmis` harness) with AIMD enabled
    (`max_threads=16`, `workers=4`); assert the recorded `max_workers`
    for an `s5`-prefixed pool is `16`.
  - `test_single_pool_uses_workers_when_auto_tune_disabled` — same
    capture, AIMD omitted; assert `max_workers == 4`.
  - `test_dual_pools_sized_to_ceiling` — a dual-lane config
    (`heavy_light_lanes.enabled: true`) + a batch that splits; assert
    both the `-heavy` and `-light` pools recorded `max_workers ==
    ceiling`. If triggering a real lane split in the CLI harness is
    heavy, fall back to asserting `_stage_5_dual` constructs the pools
    at the ceiling via the same capture wrapper driven directly.
  - Distinguish prep pools (056, `thread_name_prefix="cmcourier-prep"`)
    from S5 pools (`"cmcourier-s5*"`) in the capture wrapper so the
    056 prep pool does not pollute the assertion.

### Verify

Full unit + integration suite + ruff + mypy.

### Commit

```
fix(s5): size the upload thread pool to the AIMD ceiling, not the initial worker count (057 Phase 1)
```

## Phase 2 — CHANGELOG 0.60.0 + version bump + README + FF (~20 min)

### Files

- `CHANGELOG.md` `[0.60.0]` — Fixed (the S5 `ThreadPoolExecutor` was
  sized to `cmis.workers`, so the AIMD-resized `ResizableSemaphore`
  could never exceed the initial worker count — `pool_in_use` capped
  at `cmis.workers` while the TUI's capacity climbed; the auto-tune
  knob was disconnected from the engine since 025/043).
- `pyproject.toml` 0.59.0 → 0.60.0.
- `README.md` feature row tick.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.60.0
```

### Commit

```
docs(057): CHANGELOG 0.60.0 + version bump (057 Phase 2)
```

### FF to main.

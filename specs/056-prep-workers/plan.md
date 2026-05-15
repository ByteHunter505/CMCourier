# 056 — Plan

Two phases (~1.5 h total).

## Phase 1 — `prep_workers` config + parallelize S2/S3/S4 + tests (~70 min)

### Files

- `src/cmcourier/config/schema.py`
  - `ProcessingConfig` — add `prep_workers: int = Field(default=1, ge=1)`.

- `src/cmcourier/orchestrators/staged.py`
  - `__init__` — add `prep_workers: int = 1`; store
    `self._prep_workers = max(1, int(prep_workers))`.
  - Extract the per-item body of each stage into a helper that
    **catches its own domain exceptions** and returns
    `tuple[_StageItem | None, bool]` = `(survivor_or_None, counted_failure)`:
    - `_s2_one(item, batch_id, rec)` — mapping lookup.
    - `_s3_one(item, batch_id, rec)` — cache try_get / metadata resolve / cache put.
    - `_s4_one(item, batch_id, rec)` — assemble.
  - New shared dispatch helper
    `_run_prep_stage(items, worker) -> tuple[list[_StageItem], int]`:
    - `self._prep_workers == 1` → `results = [worker(i) for i in items]`
      (serial — byte-identical to the current loop).
    - else → `with ThreadPoolExecutor(max_workers=self._prep_workers,
      thread_name_prefix="cmcourier-prep") as pool:
      results = list(pool.map(worker, items))` (`pool.map` preserves
      input order).
    - `survivors = [s for s, _ in results if s is not None]`;
      `failed = sum(1 for _, c in results if c)`.
  - `_stage_s2` / `_stage_s3` / `_stage_s4` — become thin wrappers:
    build the `worker` (a `functools.partial` or local closure binding
    `batch_id` + `rec`) and call `_run_prep_stage`.
  - The S0/S1 path (`_stage_s0_s1`) is untouched.

- The wiring layer that constructs `StagedPipeline` — pass
  `prep_workers=config.processing.prep_workers`. (Locate via
  `grep -rn "StagedPipeline(" src/cmcourier/` — likely `cli/app.py` or
  a builder module; update every construction site.)

### Tests — `tests/` (the staged-pipeline test module)

- `test_prep_workers_defaults_to_one` — `ProcessingConfig()` →
  `prep_workers == 1`; `prep_workers=0` raises `ValidationError`.
- `test_prep_stage_serial_path_when_one_worker` — `prep_workers=1`
  over a known multi-item batch → survivors + `failed` exactly as the
  pre-056 serial loop.
- `test_prep_stage_parallel_preserves_order` — `prep_workers=4` over a
  multi-item batch → `survivors` in **input order**, all present.
- `test_prep_stage_parallel_failure_counting` — a batch with one
  domain-failing item → dropped from survivors, `failed == 1`, under
  both `prep_workers=1` and `prep_workers=4`.
- `test_prep_stage_parallel_resume_already_done` — a failing item that
  is already `S*_DONE` from a prior run → dropped, **not** counted in
  `failed` (the resume edge case the `bool` in the helper return
  preserves).
- If a `StagedPipeline` builder/fixture exists in the test suite,
  thread `prep_workers` through it.

### Verify

Full unit + integration suite + ruff + mypy.

### Commit

```
feat(prep): configurable prep_workers — parallelize S2/S3/S4 on a fixed thread pool (056 Phase 1)
```

## Phase 2 — CHANGELOG 0.59.0 + version bump + docs + FF (~20 min)

### Files

- `CHANGELOG.md` `[0.59.0]` — Added (`processing.prep_workers` — a
  fixed-size thread pool for S2/S3/S4; S4 assembly was fully serial;
  default `1` keeps current behaviour; S0/S1 stay serial by design).
- `pyproject.toml` 0.58.0 → 0.59.0.
- `README.md` feature row tick.
- `docs/samples/config-reference.yaml` — document
  `processing.prep_workers` with the default and the "S0/S1 stay
  serial" note.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.59.0
```

### Commit

```
docs(056): CHANGELOG 0.59.0 + version bump + prep_workers config docs (056 Phase 2)
```

### FF to main.

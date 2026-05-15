# 068 — Plan

Single-phase. Code change in 2 files + tests.

## Phase 1 — implementation + tests

### `src/cmcourier/config/schema.py`

- Add `growth_factor`, `halve_factor`, `halve_threshold_ratio`
  fields to `AutoTuneConfig` with the documented defaults +
  validation ranges.

### `src/cmcourier/services/auto_tune.py`

- `decide()`:
  * Replace hardcoded `upper = 1.2 * target_p95_ms` with
    `upper = config.halve_threshold_ratio * config.target_p95_ms`.
  * Replace `new_workers = max(current // 2, min_threads)` with
    `max(min_threads, ceil(current * config.halve_factor))`.
  * Replace `new_workers = min(current + 1, max_threads)` with
    `min(max(current + 1, ceil(current * config.growth_factor)),
    max_threads)`.
  * Change action label from `"+1"` to `"+N"`.

### Tests

- `tests/unit/services/test_auto_tune.py`
  - Update existing tests that assert `action == "+1"` to expect
    `"+N"`. Verify the new step size is correct.
  - New test: `test_grow_uses_growth_factor` — current=10,
    growth_factor=1.25 → new=13 (ceil).
  - New test: `test_halve_uses_halve_factor` — current=50,
    halve_factor=0.75 → new=38 (ceil).
  - New test: `test_halve_threshold_ratio_honored` — p95=40s,
    target=30s, ratio=1.2 → halve; ratio=1.5 → noop.
  - New test: `test_grow_floor_plus_one` — current=2,
    growth_factor=1.25 → new=3 (`+1` floor).

- `tests/unit/config/test_schema.py`
  - growth_factor defaults to 1.25, rejects <1.0 and >4.0
  - halve_factor defaults to 0.75, rejects <=0 and >1.0
  - halve_threshold_ratio defaults to 1.5, rejects <=1.0

### Verify

`pytest tests/unit tests/integration -q` green. ruff + mypy clean.

### Commit

```
feat(auto-tune): aggressive growth + soft halve + tolerant threshold (068 Phase 1)
```

## Phase 2 — release

- CHANGELOG `[0.70.0]`
- pyproject 0.69.0 → 0.70.0
- `pip install -e . --no-deps` + version verify
- README feature row tick (one bullet)
- FF to main

Commit: `docs(068): CHANGELOG 0.70.0 + version bump (068 Phase 2)`.

# 069 — Plan

Single-phase. All changes in `metrics.py` + tests.

## Phase 1 — implementation + tests

### `src/cmcourier/observability/metrics.py`

- `_BandwidthSampler.record_upload`: new signature
  `(size_bytes: int, *, started_at: float, completed_at: float)`.
  Distribute bytes uniformly over second-buckets overlapping the
  interval.
- `_BandwidthHandler.emit`: derive `started_at` from
  `record.created - record.duration_ms / 1000`. Defensive fallback
  to credit at completion when `duration_ms` is zero or missing.

### Tests

- `tests/unit/observability/test_metrics.py` (or a new file for
  the sampler if not present)
  - **Distribution sanity**: a 30 MB upload from t=10.0 to t=13.0
    (3 s exact) lands 10 MB in each of buckets {10, 11, 12}.
  - **Fractional interval**: 30 MB from t=10.5 to t=13.5 distributes
    5 MB to {10}, 10 MB to {11}, 10 MB to {12}, 5 MB to {13}.
  - **Same-second upload**: 1 MB from t=10.0 to t=10.5 (sub-second)
    lands entirely in bucket {10}.
  - **Cumulative preserved**: 3 uploads totaling 60 MB always
    yields `cumulative_bytes == 60_000_000`.
  - **Peak reflects sustained**: 30 MB over 3 s ⇒ `peak_mbps`
    ≤ 10 MB/s, not 30.
- `tests/unit/observability/test_metrics_handler.py` (if present
  — otherwise inline in metrics tests)
  - **Handler reads duration_ms**: a `cmis_upload` log record with
    `duration_ms=3000`, `record.created=13.0`, `size_bytes=30M`
    drives the sampler with `started_at=10.0` → 10 MB/bucket
    over {10, 11, 12}.
  - **Handler falls back to completion when duration missing**:
    record without `duration_ms` credits all bytes at completion
    (pre-069 shape, defensive only).

### Verify

`pytest tests/unit tests/integration -q` green. ruff + mypy clean.

### Commit

```
fix(metrics): distribute bandwidth bytes over real transmission window (069 Phase 1)
```

## Phase 2 — release

- CHANGELOG `[0.71.0]`
- pyproject 0.70.0 → 0.71.0
- `pip install -e . --no-deps` + version verify
- README feature row tick
- FF to main

Commit: `docs(069): CHANGELOG 0.71.0 + version bump (069 Phase 2)`.

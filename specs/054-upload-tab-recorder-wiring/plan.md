# 054 — Plan

Two phases (~1 h total). One source file, surgical.

## Phase 1 — Fix the wiring + regression tests (~40 min)

### Files

- `src/cmcourier/tui/data_provider.py`
  - **`snapshot()`** — four fields move from `self._metrics` to
    `self._upload_metrics`:
    - `bandwidth_current_mbps`
    - `bandwidth_peak_mbps`
    - `bandwidth_series`
    - `slow_ops_all`
    `self._upload_metrics` already falls back to `self._metrics` when
    no `upload_recorder_provider` is wired — single-batch unchanged.
    Leave `auto_tune_observed_p95_ms` as-is (it reads
    `current_stage_p95` and 043 wires the AIMD p95 separately — out of
    scope here; the S5 percentile *block* is already overridden via
    `_upload_recorder_provider` higher up in `snapshot()`).
  - **`_current_chunk_progress`** — replace the `prep_started_monotonic`
    branch. Resolve `elapsed_s` from the active chunk's `status`:
    - `UPLOAD` → `max(0.0, time.monotonic() − upload_started_monotonic)`
    - `DONE` → `float(upload_elapsed_s)`
    - `PREP` / unknown → `0.0`
    - `active is None` (single-batch) → unchanged: `global_elapsed_s`
    `bytes_total` resolution (from `total_bytes`) is unchanged.
    `avg_mbps` / `eta_s` derivation is unchanged — they just consume
    the corrected `elapsed_s`.

### Tests — `tests/unit/tui/test_data_provider.py`

Add a helper that builds the provider with **two distinct recorders**
(a `recorder_provider` returning a PREP recorder, an
`upload_recorder_provider` returning an UPLOAD recorder) plus a
`chunks_provider`.

- `test_bandwidth_reads_upload_recorder_not_prep` — UPLOAD recorder
  fed an upload event, PREP recorder left empty → snapshot's
  `bandwidth_current_mbps` / `bandwidth_peak_mbps` non-zero,
  `bandwidth_series` non-empty.
- `test_slow_ops_read_upload_recorder_not_prep` — slow `cmis_upload`
  routed through the UPLOAD recorder's network logger → it appears in
  `slow_ops_all`; the PREP recorder stays empty.
- `test_current_chunk_elapsed_measures_from_upload_start` — chunk in
  status `UPLOAD` with `prep_started_monotonic` far in the past and
  `upload_started_monotonic` recent → `current_chunk_elapsed_s` is the
  small (upload) gap, not the large (prep) one.
- `test_current_chunk_elapsed_done_uses_frozen_upload_elapsed` — chunk
  in `DONE` → `current_chunk_elapsed_s == upload_elapsed_s`.
- `test_current_chunk_elapsed_prep_is_zero` — chunk in `PREP` →
  `current_chunk_elapsed_s == 0.0`.
- `test_current_chunk_avg_mbps_uses_upload_window` — bytes uploaded /
  upload elapsed, not / prep+upload elapsed.

The existing single-batch tests (`_make_provider` without
`upload_recorder_provider`) are the regression gate — they must stay
green untouched.

### Verify

Full unit + integration suite + ruff + mypy.

### Commit

```
fix(tui): UPLOAD-tab reads the upload recorder for bandwidth/slow-ops + per-chunk timer measures from S5 start (054 Phase 1)
```

## Phase 2 — CHANGELOG 0.57.0 + version bump + README + FF (~20 min)

### Files

- `CHANGELOG.md` `[0.57.0]` — Fixed (UPLOAD tab showed 0 bandwidth /
  blank sparkline / no slow ops on N=2 runs because four snapshot
  fields read the PREP recorder instead of the UPLOAD recorder; the
  per-chunk timer counted from PREP start instead of S5 start).
- `pyproject.toml` 0.56.0 → 0.57.0.
- `README.md` feature row tick.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.57.0
```

### Commit

```
docs(054): CHANGELOG 0.57.0 + version bump (054 Phase 2)
```

### FF to main.

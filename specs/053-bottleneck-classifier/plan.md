# 053 — Plan

Two phases (~1.75 h total).

## Phase 1 — Stage-aware classifier + time-window log association (~1.25 h)

### Files

- `src/cmcourier/services/analyze.py`
  - **`classify_bottleneck`** — rewrite. Lead with `stage_summary`:
    - `_stage_dominance(stage_summary) -> (stage, share)` helper —
      sum each stage's `sum_ms`, find the dominant stage + its share
      of the total.
    - New constant `_STAGE_DOMINANCE = 0.45`.
    - New `_STAGE_TO_CLASS` map: `S5 → upload-bound` (outside),
      `S4 → assembly-bound`, `S3 → metadata-bound`,
      `S2 → mapping-bound`, `S1 → indexing-bound`,
      `S0 → trigger-bound` (all inside).
    - When a stage dominates → classify by stage; `confidence` =
      share; `reasons` lead with the stage verdict (name, share,
      p50/p95, inside/outside).
    - System-metrics signals become **appended reasons**, not the
      verdict: `worker-saturated` → a symptom reason;
      cpu/mem/disk-bound → corroborating reasons. They only become
      the *classification* when no stage dominates.
    - `under-utilized` only when no dominant stage AND no system
      signal.
    - Drop the dead `# noqa: ARG001` on `stage_summary`; keep the
      `cmis_max_bandwidth_mbps` / `pool_capacity` params (still bound
      at aggregation time, used by the system path).
  - **`LogReader.read_batch`** — read the batch-tagged
    `metrics-*.jsonl` first; derive the window
    `[ts − elapsed_s, ts]` from the `batch_summary`; pass it to
    `_read_windowed("network-*.jsonl", window, ts_field="ts")` and
    `_read_windowed("system-*.jsonl", window, ts_field="ts_iso")`.
  - New `_read_windowed(glob, window, *, ts_field)` — replaces the
    `batch_id`-equality filter for the network/system tiers; parse
    each record's ISO timestamp, keep those inside the window.
    `_read_filtered` (by `batch_id`) stays for the `pipeline` tier.
  - When the batch has no `batch_summary` (window underivable) the
    network/system tiers come back empty — graceful, never raises.

### Tests

- `tests/unit/services/test_analyze.py` (or wherever the analyzer
  tests live):
  - `test_classify_upload_bound_from_stage_dominance` — the 95-doc
    run shape (S5 `sum_ms` ≫ rest) → `upload-bound`, reason names S5
    + "outside the program". **Named regression test** for the
    "under-utilized" bug.
  - `test_classify_assembly_bound` — S4-dominant → `assembly-bound`
    ("inside").
  - `test_classify_under_utilized_when_balanced` — no dominant
    stage, no system signal → `under-utilized`.
  - `test_worker_saturation_is_a_reason_not_the_verdict` — system
    data with saturation + an S5-dominant stage breakdown →
    `upload-bound`, with worker-saturation as a reason line.
  - `test_network_bound_surfaces_with_zero_bandwidth_cap` — S5
    dominance + `cmis_max_bandwidth_mbps == 0` → still `upload-bound`
    (the old regression is gone).
  - `LogReader`: `test_network_records_associated_by_time_window` —
    JSONL fixtures with `ts` straddling the window; assert only the
    in-window records land in `network_summary`. Same for `system`
    via `ts_iso`.

### Commit

```
feat(analyze): stage-aware bottleneck classifier + time-window log association (053 Phase 1)
```

## Phase 2 — CHANGELOG 0.56.0 + version bump + docs + FF (~30 min)

### Files

- `CHANGELOG.md` `[0.56.0]` — Fixed (classifier ignored the stage
  breakdown and reported "under-utilized" on an upload-bound run;
  network/system records were never associated with the batch),
  Changed (classification is stage-led; system metrics refine
  rather than gate; `upload-bound` / `assembly-bound` / … name
  whether the bottleneck is inside or outside the program).
- `pyproject.toml` 0.55.0 → 0.56.0.
- `README.md` feature row tick.
- `docs/how-to/log-analysis.md` (or the analyze how-to) — document
  the new stage-led classification + the inside/outside-the-program
  labels + the time-window association caveat for overlapped runs.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.56.0
```

### Verify

Full unit + integration suite + ruff + mypy. `classify_bottleneck`
is a pure function; `LogReader` is fixture-tested — no live Alfresco
needed. Optionally re-run `analyze batch` on an existing batch's
logs and eyeball that it now names the dominant stage.

### Commit

```
docs(053): CHANGELOG 0.56.0 + version bump + bottleneck-classifier docs (053 Phase 2)
```

### FF to main.

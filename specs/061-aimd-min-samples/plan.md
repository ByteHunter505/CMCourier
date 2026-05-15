# 061 — Plan

Three phases. Phase 1 carries the engineering; 2 and 3 are config + release.

## Phase 1 — AIMD min_samples guard + provider tuple + tests (~40 min)

### Files

- `src/cmcourier/config/schema.py`
  - `AutoTuneConfig.min_samples: int = Field(default=20, ge=1)`.

- `src/cmcourier/services/auto_tune.py`
  - `decide(...)` gains `sample_count: int` keyword. Before the band
    comparison: if `sample_count < config.min_samples`, return
    `Decision(action="insufficient_data", workers=current_workers,
    timeout_s=current_timeout_s)`.
  - `Decision.action` doc-comment updated to include the new value.
  - `AutoTuneController.__init__` — `p95_provider: Callable[[],
    tuple[float, int]]`.
  - `set_p95_provider` — same signature update.
  - `_tick` — unpack `(p95, count) = self._p95_provider()`; pass
    `sample_count=count` to `decide`. Treat `"insufficient_data"`
    like `"warmup"`: do not update `last_decision`, do not call the
    resize/timeout callbacks (workers / timeout stay the same).

- `src/cmcourier/observability/metrics.py`
  - `MetricsRecorder.current_stage_p95_with_count(stage: str) -> tuple[float, int]`
    — reads `summary()` once, returns `(p95_ms, count)`. The existing
    `current_stage_p95` stays (TUI + analyzer call it).

- `src/cmcourier/orchestrators/staged.py`
  - `_build_auto_tune_controller` — change the `p95_provider` lambda
    to `lambda: self._metrics.current_stage_p95_with_count("S5")`.

- `src/cmcourier/orchestrators/multi_batch.py`
  - `_upload_p95_observer(self) -> tuple[float, int]` — returns
    `(0.0, 0)` when no upload-active recorder; otherwise reads
    `rec.current_stage_p95_with_count("S5")`.

### Tests

- `tests/unit/services/test_auto_tune.py`
  - Update every existing `decide(...)` call site to pass
    `sample_count=100` (well above default 20 — preserves the old
    assertions).
  - New: `test_insufficient_data_when_below_min_samples` — `decide(
    config(min_samples=20), observed_p95_ms=12000.0, sample_count=5,
    current_workers=6, current_timeout_s=300.0)` →
    `action == "insufficient_data"`, `workers == 6` (unchanged).
  - New: `test_min_samples_guard_off_when_count_meets_floor` —
    same call with `sample_count=20` → `action == "halve"`.
  - New: `test_controller_unpacks_tuple_provider` — controller
    constructed with a `lambda: (12000.0, 5)` provider; `_tick(60.1)`
    leaves `last_decision is None` (insufficient_data is gated, same
    as warmup).
  - Update `test_swap_takes_effect_on_next_tick` etc. to use the tuple
    provider.

- `tests/unit/config/test_schema.py`
  - `AutoTuneConfig().min_samples == 20` (default).
  - `AutoTuneConfig(min_samples=0)` raises `ValidationError`.

- `tests/unit/observability/test_metrics.py` (or wherever the recorder
  tests live)
  - `current_stage_p95_with_count("S5")` on empty stage → `(0.0, 0)`.
  - After recording 3 samples (100, 200, 300) → `(300.0, 3)`.

### Verify

`pytest tests/unit -q` first (fast feedback), then full suite + ruff +
mypy.

### Commit

```
feat(auto-tune): min_samples guard prevents halve on outlier-with-few-samples (061 Phase 1)
```

## Phase 2 — Staging YAMLs (~10 min)

### Files

- `sample/config-staging-rvabrep.yaml`
- `sample/config-staging-rvabrep-mega-heavy.yaml`
- `sample/config-staging-rvabrep-frequent-heavy-lanes.yaml`

Add under `cmis.auto_tune`:

```yaml
    # 061: don't act on fewer than min_samples uploads — protects against
    # the nearest-rank p95 being dominated by a single cold-connection
    # outlier in the first chunk (which used to trigger a spurious halve).
    min_samples: 20
```

### Verify

`.venv/bin/python -c "import yaml; from cmcourier.config.schema import CmisConfigModel; ..."` for each YAML — parses cleanly, `min_samples == 20`.

### Commit

```
config(staging): add auto_tune.min_samples to all three staging YAMLs (061 Phase 2)
```

## Phase 3 — CHANGELOG 0.63.0 + version + README + config-ref + FF (~15 min)

### Files

- `CHANGELOG.md` `[0.63.0]` — Fixed (AIMD halved on outlier-with-few-
  samples in the first chunk because nearest-rank p95 is dominated by
  a single big sample when N is small; added `min_samples` guard).
- `pyproject.toml` 0.62.0 → 0.63.0.
- `README.md` feature row tick.
- `docs/samples/config-reference.yaml` documents
  `cmis.auto_tune.min_samples`.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.63.0
```

### Commit

```
docs(061): CHANGELOG 0.63.0 + version bump + min_samples docs (061 Phase 3)
```

### FF to main.

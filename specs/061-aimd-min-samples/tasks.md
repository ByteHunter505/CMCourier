# 061 — Tasks

## Phase 1 — AIMD min_samples guard + provider tuple + tests

- [ ] 1.1 `schema.py`: `AutoTuneConfig.min_samples: int = Field(default=20, ge=1)`.
- [ ] 1.2 `auto_tune.py`: `decide(...)` gains `sample_count` keyword;
      short-circuits with `action="insufficient_data"` when below floor.
- [ ] 1.3 `auto_tune.py`: provider signature →
      `Callable[[], tuple[float, int]]`; `_tick` unpacks.
- [ ] 1.4 `auto_tune.py`: `_tick` treats `insufficient_data` like
      `warmup` (no `last_decision` update, no callbacks).
- [ ] 1.5 `metrics.py`: `MetricsRecorder.current_stage_p95_with_count`
      returns `(p95_ms, count)`.
- [ ] 1.6 `staged.py`: AIMD `p95_provider` lambda uses the tuple API.
- [ ] 1.7 `multi_batch.py`: `_upload_p95_observer` returns tuple.
- [ ] 1.8 Tests: `decide` with `sample_count < min` → insufficient_data;
      with `sample_count >= min` → real action (regression).
- [ ] 1.9 Tests: existing `decide` call sites pass `sample_count=100`.
- [ ] 1.10 Tests: `current_stage_p95_with_count` for empty + populated.
- [ ] 1.11 Tests: `AutoTuneConfig.min_samples` default + validator.
- [ ] 1.12 Full unit + integration suite green; ruff + mypy clean.
- [ ] 1.13 Commit
      `feat(auto-tune): min_samples guard prevents halve on outlier-with-few-samples (061 Phase 1)`.

## Phase 2 — Staging YAMLs

- [ ] 2.1 `sample/config-staging-rvabrep.yaml` — `min_samples: 20`.
- [ ] 2.2 `sample/config-staging-rvabrep-mega-heavy.yaml` — same.
- [ ] 2.3 `sample/config-staging-rvabrep-frequent-heavy-lanes.yaml` — same.
- [ ] 2.4 Schema-parse each YAML to confirm.
- [ ] 2.5 Commit
      `config(staging): add auto_tune.min_samples to all three staging YAMLs (061 Phase 2)`.

## Phase 3 — CHANGELOG 0.63.0 + version + README + config-ref + FF

- [ ] 3.1 `CHANGELOG.md [0.63.0]` — Fixed.
- [ ] 3.2 `pyproject.toml` 0.62.0 → 0.63.0.
- [ ] 3.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 3.4 `cmcourier --version` reports 0.63.0.
- [ ] 3.5 `README.md` feature row tick.
- [ ] 3.6 `docs/samples/config-reference.yaml` documents `min_samples`.
- [ ] 3.7 Full suite + ruff + mypy clean.
- [ ] 3.8 Commit
      `docs(061): CHANGELOG 0.63.0 + version bump + min_samples docs (061 Phase 3)`.
- [ ] 3.9 FF to main.

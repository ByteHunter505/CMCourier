# 053 — Tasks

## Phase 1 — Stage-aware classifier + time-window log association

- [ ] 1.1 `analyze.py`: `_stage_dominance(stage_summary)` helper +
      `_STAGE_DOMINANCE` constant + `_STAGE_TO_CLASS` map.
- [ ] 1.2 `analyze.py`: rewrite `classify_bottleneck` — stage
      breakdown PRIMARY; system metrics become appended reasons;
      `worker-saturated` is a symptom reason, not the verdict;
      `under-utilized` only when nothing dominates.
- [ ] 1.3 `analyze.py`: `_read_windowed(glob, window, *, ts_field)`;
      `read_batch` derives the batch window from the `batch_summary`
      and uses it for the network (`ts`) + system (`ts_iso`) tiers.
- [ ] 1.4 Tests: `classify_bottleneck` — upload-bound regression
      (95-doc shape), assembly-bound, under-utilized-when-balanced,
      worker-saturation-is-a-reason, network-bound-with-zero-cap.
- [ ] 1.5 Tests: `LogReader` time-window association for network
      (`ts`) + system (`ts_iso`).
- [ ] 1.6 Full unit + integration suite green; mypy + ruff clean.
- [ ] 1.7 Commit
      `feat(analyze): stage-aware bottleneck classifier + time-window log association (053 Phase 1)`.

## Phase 2 — CHANGELOG 0.56.0 + version bump + docs + FF

- [ ] 2.1 `CHANGELOG.md [0.56.0]` — Fixed / Changed.
- [ ] 2.2 `pyproject.toml` 0.55.0 → 0.56.0.
- [ ] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 2.4 `cmcourier --version` reports 0.56.0.
- [ ] 2.5 `README.md` feature row tick.
- [ ] 2.6 `docs/how-to/log-analysis.md` — stage-led classification +
      inside/outside-the-program labels + time-window caveat.
- [ ] 2.7 Full suite + ruff + mypy clean.
- [ ] 2.8 Commit
      `docs(053): CHANGELOG 0.56.0 + version bump + bottleneck-classifier docs (053 Phase 2)`.
- [ ] 2.9 FF to main.

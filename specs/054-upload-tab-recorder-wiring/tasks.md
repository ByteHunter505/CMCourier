# 054 — Tasks

## Phase 1 — Fix the wiring + regression tests

- [ ] 1.1 `data_provider.py` `snapshot()`: `bandwidth_current_mbps`,
      `bandwidth_peak_mbps`, `bandwidth_series`, `slow_ops_all` read
      from `self._upload_metrics`.
- [ ] 1.2 `data_provider.py` `_current_chunk_progress`: resolve
      `elapsed_s` by active-chunk status — UPLOAD → from
      `upload_started_monotonic`; DONE → frozen `upload_elapsed_s`;
      PREP → 0.0; no active chunk → `global_elapsed_s` (unchanged).
- [ ] 1.3 Tests: bandwidth + slow-ops read the UPLOAD recorder, not
      PREP — provider wired with two divergent recorders.
- [ ] 1.4 Tests: per-chunk timer — UPLOAD measures from S5 start,
      DONE uses frozen `upload_elapsed_s`, PREP is 0.0; avg_mbps uses
      the upload window.
- [ ] 1.5 Full unit + integration suite green; mypy + ruff clean.
- [ ] 1.6 Commit
      `fix(tui): UPLOAD-tab reads the upload recorder for bandwidth/slow-ops + per-chunk timer measures from S5 start (054 Phase 1)`.

## Phase 2 — CHANGELOG 0.57.0 + version bump + README + FF

- [ ] 2.1 `CHANGELOG.md [0.57.0]` — Fixed.
- [ ] 2.2 `pyproject.toml` 0.56.0 → 0.57.0.
- [ ] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 2.4 `cmcourier --version` reports 0.57.0.
- [ ] 2.5 `README.md` feature row tick.
- [ ] 2.6 Full suite + ruff + mypy clean.
- [ ] 2.7 Commit
      `docs(054): CHANGELOG 0.57.0 + version bump (054 Phase 2)`.
- [ ] 2.8 FF to main.

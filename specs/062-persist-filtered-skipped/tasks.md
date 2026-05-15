# 062 — Tasks

## Phase 1 — Persist + tests

- [x] 1.1 `domain/models.py`: `StageStatus.S1_FILTERED` and
      `S1_SKIPPED`.
- [x] 1.2 `domain/ports.py`: `ITrackingStore.mark_stage_terminal`
      abstract method.
- [x] 1.3 `adapters/tracking/sqlite.py`: `mark_stage_terminal` impl
      (UPDATE status + error_message + completed_at, NO retry bump);
      validator accepts FAILED/FILTERED/SKIPPED suffixes.
- [x] 1.4 `orchestrators/staged.py`: `_stage_s0_s1` persists filtered
      (synthetic txn_num) + skipped cross-batch via `mark_stage_pending`
      + `mark_stage_terminal`.
- [x] 1.5 `orchestrators/staged.py`: update module docstring lines 10-12.
- [x] 1.6 Tests: `test_ports.py` adds `mark_stage_terminal` to the
      abstract methods set.
- [x] 1.7 Tests: `test_sqlite_tracking_store.py` —
      mark_stage_terminal happy paths (FILTERED + SKIPPED), retry not
      bumped, rejects non-terminal stage.
- [x] 1.8 Tests: `test_staged_pipeline.py` filtered run → `S1_FILTERED`
      row with synthetic txn + reason.
- [x] 1.9 Tests: `TestCrossBatchSkip` second run → `S1_SKIPPED` rows
      with reason.
- [x] 1.10 Full unit + integration suite green; mypy + ruff clean.
- [x] 1.11 Commit
      `feat(s1): persist filtered + cross-batch-skipped docs to migration_log (062 Phase 1)`.

## Phase 2 — CHANGELOG 0.64.0 + version + README + FF

- [x] 2.1 `CHANGELOG.md [0.64.0]` — Changed (cross-batch skip)
      + Added (filtered rows).
- [x] 2.2 `pyproject.toml` 0.63.0 → 0.64.0.
- [x] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [x] 2.4 `cmcourier --version` reports 0.64.0.
- [x] 2.5 `README.md` feature row tick.
- [x] 2.6 Full suite + ruff + mypy clean.
- [x] 2.7 Commit
      `docs(062): CHANGELOG 0.64.0 + version bump (062 Phase 2)`.
- [x] 2.8 FF to main.

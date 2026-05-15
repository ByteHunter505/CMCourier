# 062 — Plan

Two phases.

## Phase 1 — Persist + tests (~60 min)

### Files

- `src/cmcourier/domain/models.py`
  - `StageStatus`: add `S1_FILTERED = "S1_FILTERED"` and `S1_SKIPPED =
    "S1_SKIPPED"`.

- `src/cmcourier/domain/ports.py`
  - `ITrackingStore.mark_stage_terminal(txn_num: str, batch_id: str,
    stage: StageStatus, error_message: str) -> None` — new abstract.
    Docstring distinguishes from `mark_stage_failed` (no retry_count
    bump, accepts any terminal status including the new ones).

- `src/cmcourier/adapters/tracking/sqlite.py`
  - `_require_state` keeps existing validators; `mark_stage_terminal`
    accepts any state whose suffix is in `{"FAILED", "FILTERED",
    "SKIPPED"}` and does an `UPDATE migration_log SET status = ?,
    error_message = ?, completed_at = ? WHERE rvabrep_txn_num = ? AND
    batch_id = ?`. (Note: NO retry_count bump.)
  - Validator helper accepts the new suffix set.

- `src/cmcourier/orchestrators/staged.py`
  - In `_stage_s0_s1`:
    - **Filtered path**: build a `MigrationRecord` with synthetic
      `rvabrep_txn_num = f"FILTERED__{shortname}__{system_id}"`,
      `rvabrep_file_name = ""`. Call `mark_stage_pending(record,
      S1_PENDING)` then `mark_stage_terminal(synthetic_txn, batch,
      S1_FILTERED, "deleted_at_source")`. The synthetic txn ensures
      uniqueness on `(txn, batch)`.
    - **Skipped cross-batch path**: real `doc.txn_num`. Build the
      record, `mark_stage_pending(record, S1_PENDING)`,
      `mark_stage_terminal(doc.txn_num, batch, S1_SKIPPED,
      "cross_batch_uploaded")`.
  - The existing `filtered` / `skipped_cross_batch` counters stay —
    the `RunReport` totals don't change.
  - Update the module docstring lines 10-12 to reflect the new
    behaviour ("skipped docs now produce a `S1_SKIPPED` row").

- `src/cmcourier/tui/detail_tab.py`
  - No change required. `_human_size(0)` already returns `"—"`, the
    `status` column is wide enough for `S1_FILTERED` / `S1_SKIPPED`
    (12 chars).

### Tests

- `tests/unit/domain/test_ports.py` — add `mark_stage_terminal` to the
  `ITrackingStore.__abstractmethods__` frozenset.

- `tests/integration/adapters/test_sqlite_tracking_store.py` — new
  `TestMarkStageTerminal062` class:
  - `test_marks_filtered_with_reason`: mark_pending S1, then
    mark_stage_terminal(S1_FILTERED, "deleted_at_source"), assert the
    row's status + error_message + completed_at.
  - `test_marks_skipped_with_reason`: same shape, S1_SKIPPED.
  - `test_does_not_bump_retry_count`: pre-set retry_count=2, call
    mark_stage_terminal, assert retry_count stays 2 (unlike
    mark_stage_failed).
  - `test_rejects_non_terminal_status`: calling with `S1_DONE` raises.

- `tests/integration/pipeline/test_staged_pipeline.py`:
  - The existing `TestS1FilteredOutcome051` (or wherever the spec 051
    test lives) gains an assertion: after the run, query the
    migration_log for `status = "S1_FILTERED"`, assert the synthetic
    txn_num is there with the right error_message.
  - `TestCrossBatchSkip` (already exists): the second run now writes
    a row per skipped doc with `status = "S1_SKIPPED"`. New assertion.

### Verify

`pytest tests/unit tests/integration -q` — all green.

### Commit

```
feat(s1): persist filtered + cross-batch-skipped docs to migration_log (062 Phase 1)
```

## Phase 2 — CHANGELOG 0.64.0 + version + README + FF (~20 min)

### Files

- `CHANGELOG.md` `[0.64.0]` — Changed: cross-batch skipped docs now
  produce a `S1_SKIPPED` row (REBIRTH §10's "silent skip" contract
  intentionally reversed for traceability; mention disk implications
  on repeated re-runs). Added: `S1_FILTERED` rows for delete-coded
  source docs.
- `pyproject.toml` 0.63.0 → 0.64.0.
- `README.md` feature row tick.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.64.0
```

### Commit

```
docs(062): CHANGELOG 0.64.0 + version bump (062 Phase 2)
```

### FF to main.

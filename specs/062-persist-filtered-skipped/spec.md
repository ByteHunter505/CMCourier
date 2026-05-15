# 062 — Persist S1 filtered + cross-batch skipped to migration_log

## Why

The operator inspected the DETAIL tab during a staging run and noticed:

> "Cuando entro al detail no miro cuáles archivos fueron filtrados y por
> qué razón, tampoco miro los skip ni en el resumen ni en el detalle,
> los skip por idempotencia."

Both observations are correct. Two categories of S1 outcomes are
**counted but not persisted**, so neither the DETAIL tab nor
`analyze batch` nor `cmcourier batch show` can answer "which specific
documents fell into this bucket and why":

1. **Filtered at S1 (spec 051)** — triggers whose RVABREP row carries
   a delete code raise `RVABREPDeletedError`; the orchestrator does
   `filtered += 1` + INFO log, no row in `migration_log`.
2. **Cross-batch skipped** — docs whose `txn_num` is
   already `S5_DONE` in a prior batch are *skipped silently — no new
   `migration_log` row, just a counter and an INFO log line*.
   `staged.py:10-12` documents this textually as a deliberate
   decision.

The `RunReport` carries the totals (`s1_filtered`,
`s1_skipped_cross_batch`); the per-doc identities only live in
`app-*.log` (grep territory).

## What

### 1. Two new `StageStatus` terminal states

```python
class StageStatus(StrEnum):
    ...
    S1_FILTERED = "S1_FILTERED"   # delete-coded at source (spec 051)
    S1_SKIPPED  = "S1_SKIPPED"    # already S5_DONE in a prior batch
```

Both are terminal — like `*_FAILED`, they don't progress further.

### 2. `_stage_s0_s1` persists each case

- **Filtered**: the `RVABREPDeletedError` doesn't carry a `txn_num`
  (it fires before any row is enriched). The persisted row uses a
  **synthetic txn_num** `FILTERED__{shortname}__{system_id}` so the
  unique index `(rvabrep_txn_num, batch_id)` is satisfied and re-runs
  collide cleanly via `INSERT OR IGNORE`. The `error_message` carries
  `"deleted_at_source"` (and the `deleted_count` from the exception).
- **Skipped cross-batch**: real `txn_num` is available (the
  RVABREPDocument was enriched). Persist with `status =
  S1_SKIPPED`, `error_message = "cross_batch_uploaded"`.

Both go through:
- `mark_stage_pending(record, S1_PENDING)` — `INSERT OR IGNORE` lands
  the row.
- new `mark_stage_terminal(txn, batch, stage, error_message)` —
  `UPDATE` to the terminal state with the reason. This method is
  distinct from `mark_stage_failed` because it must NOT bump
  `retry_count` (filtered/skipped aren't failures).

### 3. The DETAIL tab gets the new docs for free

`list_docs_for_batch` already does `SELECT ... WHERE batch_id = ?`
ORDER BY txn_num — the new rows just appear. `render_detail`'s
existing `status` and `reason` columns surface them. The
`_human_size(0)` already renders as "—" for the size column (filtered
and skipped docs don't have a staged file). Zero changes to the TUI
rendering logic.

### 4. `analyze` + `cmcourier batch show` get them for free too

Both already read `migration_log` rows by `batch_id`. The new statuses
will appear in `analyze batch <id>` status breakdowns and in
`batch show` listings. The `BatchDetails.stage_counts` pivot picks
them up.

## Out of scope

- **`resume_out_of_scope`** drops (`staged.py:540-549`). These are a
  third category of "S1 didn't process this doc" — a resume run
  scoped to a prior batch's `txn_num` set rejects triggers that
  produce new docs. Out of scope here because it has a different
  semantic (filter by resume policy, not by data state). A future
  spec could persist these too if the operator asks.
- **Reverting the spec's "skip silently" contract** at the docstring
  level — we change the behaviour deliberately and update the
  docstring; we don't argue with §10's original intent (avoid disk
  bloat). The CHANGELOG explains the new trade.
- **A retention / prune command** for old migration_log rows. If disk
  growth becomes an issue we can add `cmcourier tracking prune
  --older-than ...` separately. Today the operator can `DELETE FROM
  migration_log WHERE batch_id < ?` manually.

## Acceptance criteria

- `StageStatus.S1_FILTERED` and `StageStatus.S1_SKIPPED` exist.
- A pipeline run with a delete-coded RVABREP row produces a row in
  `migration_log` with `status=S1_FILTERED`, `error_message`
  containing `"deleted_at_source"`, and a synthetic txn_num. A test
  asserts it end-to-end via the pipeline harness.
- A pipeline run on a doc that is already `S5_DONE` in a prior batch
  produces a row in the new batch with `status=S1_SKIPPED`,
  `error_message="cross_batch_uploaded"`. A test asserts it.
- `mark_stage_terminal` exists on `ITrackingStore`, implemented in
  `SQLiteTrackingStore`. Tests for the new method directly.
- The `_require_state` validator in `sqlite.py` accepts `S1_FILTERED`
  and `S1_SKIPPED` for the new method.
- `list_docs_for_batch` includes both new statuses — covered by the
  pipeline-level tests.
- TUI port contract test (`test_ports.py`) lists `mark_stage_terminal`
  in `ITrackingStore.__abstractmethods__`.
- Full unit + integration suite green; mypy + ruff clean.
- `CHANGELOG.md [0.64.0]` describes the trade (more rows in
  `migration_log` on re-runs, full traceability in return).
- `pyproject.toml` 0.63.0 → 0.64.0.

## Notes on test strategy

The pipeline harness already exercises both paths via the `rvabrep.csv`
fixture (`TESTUNMAPPED` doesn't produce filtered because it's an S2
case; we need a row with a delete code to drive the filtered path).
We extend the existing test that drives the 6-doc fixture: assert the
DELETED row's synthetic txn_num appears with `S1_FILTERED`. For the
cross-batch case, the existing `TestCrossBatchSkip` class runs the
same triggers twice — the second run now produces `S1_SKIPPED` rows
the test can assert on.

The terminal-state writer is unit-tested directly in
`test_sqlite_tracking_store.py` for both new statuses, including
idempotency (calling twice with the same key is a no-op UPDATE).

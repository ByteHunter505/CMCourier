# 044 — Plan

Three phases (~1.5 h total).

## Phase 1 — ``_apply_resume`` algorithm rewrite (~45 min)

### Files

- `src/cmcourier/cli/app.py`
  - Re-order ``_apply_resume`` to: validate inputs → check
    explicit ``--from-stage`` override → auto-detect (gap +
    FAILED/PENDING) → "clean" exit.
  - Auto-detect logic: loop stages 1..5, on each stage check
    FAILED/PENDING first (resolve to N) then check N<5 AND
    DONE count > 0 (resolve to N+1).

### Tests

- `tests/unit/cli/test_app.py` (or new
  `tests/unit/cli/test_resume.py` if app.py tests don't exist):
  - ``test_apply_resume_failed_pending_takes_priority`` — both
    FAILED in S3 and DONE in S4: resolves to 3.
  - ``test_apply_resume_stage_gap_detected`` — S4_DONE=543,
    S5_DONE=281: resolves to 5.
  - ``test_apply_resume_truly_clean`` — only S5_DONE rows:
    exits 0 with "Nothing to resume" message.
  - ``test_apply_resume_explicit_from_stage_beats_clean`` — clean
    batch + ``explicit_from_stage=5``: returns 5 without
    "clean" exit.
  - ``test_apply_resume_unknown_batch`` — unknown batch_id:
    exits 1 with "Batch not found".

### Commit

```
fix(cli): resume detects S{N}_DONE→S{N+1} stage gaps + honors explicit --from-stage (044 Phase 1)
```

## Phase 2 — ``--batch-id`` always threaded (~15 min)

### Files

- `src/cmcourier/cli/app.py`
  - Drop the ``if resume_flag else None`` conditional in the
    ``resume_batch_id`` assignment (line 711 in 0.46.0).
  - Document the new semantic in the inline comment: "any
    ``--batch-id`` the operator passes is the batch_id the run
    operates on; the orchestrator validates existence."

### Tests

- `tests/integration/cli/test_pipeline_kinds.py` (or wherever
  the CLI integration tests live):
  - ``test_batch_id_flag_passed_without_resume`` — run with
    ``--batch-id X --from-stage 1`` on a fresh DB: succeeds and
    the new batch is stored under ``X`` in migration_log.

### Commit

```
fix(cli): --batch-id always threads to the orchestrator (044 Phase 2)
```

## Phase 3 — Docs + CHANGELOG 0.47.0 + version bump + live re-verify + FF (~30 min)

### Files

- `CHANGELOG.md` ``[0.47.0]`` — Fixed (the three resume bugs by
  id), Changed (``_apply_resume`` algorithm order +
  ``--batch-id`` semantic).
- `pyproject.toml` 0.46.0 → 0.47.0.
- `README.md` feature row tick.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.47.0
```

### Live re-verification (replicate §H.1 staging scenario)

```bash
# Setup
bash scripts/staging/wipe-alfresco-docs.sh
rm -f sample/staging-tracking.db sample/staging-tracking.db-wal sample/staging-tracking.db-shm

# Run 1 — start + kill mid-S5
CMIS_USERNAME=admin CMIS_PASSWORD=admin \
.venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml \
  --total 50 --batches-in-flight 1 --no-tui &
# wait until tracking DB has ~20-30 S5_DONE rows, then kill -9

# Capture batch_id from migration_log
batch_id=$(.venv/bin/python -c "
import sqlite3
print(sqlite3.connect('sample/staging-tracking.db').execute(
    'SELECT DISTINCT batch_id FROM migration_log'
).fetchone()[0]
")

# Run 2 — resume
CMIS_USERNAME=admin CMIS_PASSWORD=admin \
.venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml \
  --batch-id "$batch_id" --resume --no-tui
```

Acceptance:

- Run 2 must NOT print "Nothing to resume".
- Run 2 must report ``s5_done > 0`` matching the remaining work.
- Final ``alfresco_total_docs == distinct_txns_in_batch`` (within
  the 4-10 doc race-window deferred to follow-up spec).

### Commit

```
docs(044): CHANGELOG 0.47.0 + version bump + resume live re-verify (044 Phase 3)
```

### FF to main.

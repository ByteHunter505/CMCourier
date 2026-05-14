# 045 — Plan

Two phases (~1h total).

## Phase 1 — 409 recovery in CmisUploader (~30 min)

### Files

- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - New private method
    ``_lookup_existing_object_id(folder_url, name) -> str | None``
    that GETs ``{folder_url}?cmisselector=children&maxItems=…``,
    finds the entry with matching ``cmis:name``, returns its
    ``cmis:objectId`` (or ``None``).
  - ``upload(...)`` ``except CMISClientError`` block extended: when
    ``exc.status_code == 409``, emit the
    ``s5_upload_409_recovery_attempt`` event, run the lookup,
    emit ``s5_upload_409_recovered`` (or ``..._failed``), then
    either return the recovered id or re-raise.

### Tests

- `tests/unit/adapters/upload/test_cmis_uploader.py` (or wherever
  the uploader tests live):
  - ``test_upload_409_recovered_returns_existing_object_id`` —
    mock POST 409 + GET children returning the doc; assert
    upload() returns the recovered id without raising.
  - ``test_upload_409_not_recovered_reraises`` — mock POST 409 +
    GET children returning empty; assert upload() raises
    ``CMISClientError`` with status_code=409.
  - ``test_upload_200_does_not_call_lookup`` — mock POST 200; the
    lookup endpoint is unregistered so any call would raise; this
    confirms the lookup is only invoked on 409.

### Commit

```
fix(uploader): idempotent 409 recovery — lookup existing object on conflict (045 Phase 1)
```

## Phase 2 — docs + CHANGELOG 0.48.0 + version bump + live re-verify + FF (~30 min)

### Files

- `CHANGELOG.md` ``[0.48.0]`` — Fixed (kill-race idempotency),
  Added (lookup helper + new structured events).
- `pyproject.toml` 0.47.0 → 0.48.0.
- `README.md` feature row tick.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.48.0
```

### Live re-verification

```bash
# Same scenario that 044 closed for resume detection.
bash scripts/staging/wipe-alfresco-docs.sh
rm -f sample/staging-tracking.db sample/staging-tracking.db-wal sample/staging-tracking.db-shm

# Run 1 — start + kill mid-S5
CMIS_USERNAME=admin CMIS_PASSWORD=admin \
.venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml \
  --total 50 --batches-in-flight 1 --no-tui &
# wait for ~25 S5_DONE, kill -9 the python

# Capture batch_id
batch_id=$(.venv/bin/python -c "
import sqlite3; print(sqlite3.connect('sample/staging-tracking.db').execute(
    'SELECT DISTINCT batch_id FROM migration_log'
).fetchone()[0]
")

# Run 2 — resume; pre-045 expected ~4 s5_failed; post-045 expected 0
CMIS_USERNAME=admin CMIS_PASSWORD=admin \
.venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml \
  --batch-id "$batch_id" --resume --no-tui
```

Acceptance:

- Run 2 reports ``s5_failed=0``.
- ``rg s5_upload_409_recovered sample/logs/network-2026-05-13.jsonl |
  wc -l`` ≥ 1 (at least one recovery happened).
- Alfresco doc count == distinct txns in batch.

### Commit

```
docs(045): CHANGELOG 0.48.0 + version bump + 409 idempotency live re-verify (045 Phase 2)
```

### FF to main.

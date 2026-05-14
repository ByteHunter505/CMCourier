# 045 — Idempotent S5 document upload on 409 conflict

## Why

The §H.1 live verification of 0.47.0 closed the resume detection
gap, but exposed a residual issue from the same kill-race: 4 docs
landed in Alfresco from run 1 successfully (200 OK from CMIS) but
``kill -9`` interrupted the pipeline BEFORE the SQLite
``mark_stage_done(txn, batch_id, S5_DONE)`` commit could persist.
On resume, those 4 docs look "still pending S5" to the migration
log; the orchestrator retries the upload; Alfresco's ``cmis:name``
uniqueness constraint rejects with HTTP 409 → those 4 retries land
as ``S5_FAILED`` in the migration log even though the docs are
already in CMIS.

The folder-creation path in ``CmisUploader`` already implements
this idempotent-409 pattern (REBIRTH §8.3 / the docstring at line
11): if a folder POST returns 409 because the folder already
exists, the uploader proceeds with the cached id instead of
failing. The document POST path has no such handling — 045 brings
it parity with folders.

## What

### 1. ``CmisUploader._lookup_existing_object_id(folder_url, name)``

New private helper. Lists the folder children via
``cmisselector=children`` and returns the ``cmis:objectId`` of the
child whose ``cmis:name`` matches ``name``. Returns ``None`` if
not found. Honors the same retry / timeout / metrics path as the
existing GET helpers in the uploader.

We use the children-walk (not ``cmisselector=query``) because
Alfresco's Solr indexing has a lag of seconds-to-minutes and is
unreliable as a freshness oracle (we observed this during 040 / 041
verifications — fresh uploads were invisible to SQL queries for
the first ~30 s). The children endpoint reflects the canonical
folder state immediately.

### 2. ``upload(...)`` catches 409 and attempts recovery

After the multipart POST raises ``CMISClientError`` with
``status_code == 409``, the upload path:

1. Logs a structured ``s5_upload_409_recovery_attempt`` event so
   the operator can audit the recovery decisions in
   metrics.jsonl.
2. Calls ``_lookup_existing_object_id(folder_url, document_name)``.
3. If the lookup returns a non-None ``cmis:objectId``:
   - Emit ``s5_upload_409_recovered`` (success, recovered).
   - Return that objectId from ``upload(...)`` as if the upload
     had succeeded — the orchestrator will mark S5_DONE normally.
4. If the lookup returns ``None`` (true 409 — not a kill-race
   duplicate, e.g. permission constraint with a different
   ``cmis:name`` collision):
   - Emit ``s5_upload_409_recovery_failed``.
   - Re-raise the original ``CMISClientError`` so the failure path
     continues unchanged.

### 3. New StageOutcome distinction (deferred)

The upload-side outcome enum currently is ``"done" | "failed" |
"skipped"``. We considered adding ``"recovered"`` so the CHUNKS
tab can show recovery distinctly from a fresh upload — but every
downstream metric/counter treats "done" identically to a normal
success and the bookkeeping cost of a new outcome dwarfs the
visibility value at this scale. Recovered uploads count as
``done`` in the tally; the structured
``s5_upload_409_recovered`` event provides per-doc auditability.

## Out of scope

- 409 retry on folder creation. That path was already idempotent
  pre-045 (REBIRTH §8.3).
- Verifying the recovered doc's content/properties match what we
  intended to upload. The uniqueness contract is ``cmis:name``;
  if a different doc legitimately shares that name (e.g. operator
  uploaded outside the pipeline), the recovery returns its id and
  the migration log marks it S5_DONE for our txn. This is the
  "trust the cmis:name uniqueness scheme" contract — documented
  in the operator runbook.
- Asynchronous bulk reconciliation. A periodic job that scans the
  migration_log for "not S5_DONE" rows and checks CMIS folder
  contents could close the entire class of mid-flight commit
  losses — out of scope for 045 but a sensible follow-up if more
  kill-race scenarios surface.

## Acceptance criteria

- Unit test: ``upload(...)`` with a mocked 409 response from the
  POST AND a mocked successful lookup returns the existing
  objectId (no exception).
- Unit test: ``upload(...)`` with a 409 response AND a lookup that
  returns ``None`` re-raises ``CMISClientError`` with the original
  status_code.
- Unit test: ``upload(...)`` with a 200 response on first attempt
  never calls the lookup helper (no behavior change on the happy
  path).
- Live re-verify of §H.1 staging scenario (kill mid-S5 + resume):
  final ``s5_failed == 0`` and Alfresco doc count == distinct txns
  in the batch.
- ``CHANGELOG.md [0.48.0]`` entry.
- mypy + ruff clean.

## Notes on test strategy

The unit tests stub the ``requests.Session`` via ``responses``
library (same approach as the existing CMIS uploader tests) so we
can assert specific URL → status mappings deterministically. The
lookup helper is exercised directly with its own unit case for
the "found" / "not found" / "transport error" branches.

# 044 — Robust resume after kill -9 mid-S5

## Why

Live §H.1 verification against the testserver Alfresco caught three
related bugs that compound to make the documented resume flow
non-functional after a real crash:

1. **Resume "is clean" false-positive.** ``_apply_resume`` in
   ``cli/app.py:842-850`` only looks for ``FAILED`` or ``PENDING``
   rows in ``stage_counts`` to decide if resume is needed. After
   ``kill -9`` mid-S5, docs that S4 finished but S5 never picked up
   stay at status ``S4_DONE`` — neither failed nor pending. The
   loop walks S1..S5, sees no FAILED/PENDING, and reports
   *"Nothing to resume — batch is clean"* even though
   ``S4_DONE`` count is 543 and ``S5_DONE`` count is only 281.
   The operator loses the second half of their batch silently.

2. **``--batch-id`` flag silently dropped without ``--resume``.**
   ``cli/app.py:711`` only forwards the user's ``--batch-id`` to
   the orchestrator when ``--resume`` is also passed
   (``resume_batch_id = pipeline_kwargs.get("batch_id") if
   resume_flag else None``). The operator escape hatch
   ``--batch-id X --from-stage 5`` (intended for "replay this
   stage of this batch") fails with the cryptic
   ``ValueError("from_stage > 1 requires batch_id")`` because
   the validation sees ``batch_id=None`` even though the user
   passed it.

3. **``_apply_resume`` exits before honoring ``--from-stage``.**
   When ``--resume`` is set alongside ``--from-stage N``, the
   "is clean" early-exit short-circuits the explicit override
   path. Composed with bugs #1 and #2 this means: there's
   **no CLI combination** that recovers the 543 stuck docs
   without manual SQL.

This is one bug class — the resume model assumed full coverage of
in-flight state via FAILED/PENDING markers, but with a worker pool
sized smaller than the batch, most queued-for-S5 docs sit at
``S4_DONE`` with no marker that they need S5.

## What

### 1. Resume detects S{N}_DONE stage gaps (bug #1)

``_apply_resume`` gains a per-stage continuation check: for each
stage ``N`` in 1..4, if ``stage_counts[S{N}][DONE] > 0`` AND no
earlier stage has FAILED/PENDING work, the resolved ``from_stage``
is ``N+1``. The existing FAILED/PENDING check stays first (those
are higher priority — they need the same-stage retry path).

After this fix: a batch with 543 docs at ``S4_DONE`` + 281 at
``S5_DONE`` resolves to ``from_stage=5``, runs S5 on the missing
543 docs, and skips the 281 already-uploaded ones (via the existing
``is_stage_done`` per-doc short-circuit in ``_stage_s5``).

### 2. ``--batch-id`` always threads to the orchestrator (bug #2)

``cli/app.py`` drops the conditional ``if resume_flag else None`` —
the user's ``--batch-id`` is forwarded unconditionally. The
orchestrator already accepts ``resume_batch_id`` semantically as
"the batch_id this run should operate on" — passing it when the
user named one is just honoring the operator's intent.

This makes ``--batch-id X --from-stage 5`` work as documented
without requiring ``--resume``. With ``--resume`` it keeps the same
auto-detection behavior.

### 3. ``--from-stage`` beats "is clean" exit (bug #3)

When ``--from-stage`` is explicit (``!= 1``) AND ``--resume`` is
set, the explicit value wins regardless of whether
``_apply_resume`` would otherwise have exited as "clean". The
order in ``_apply_resume`` flips: explicit-wins check happens
BEFORE the "is clean" exit. The new order is:

1. Validate ``--batch-id`` is present.
2. Load batch details from store.
3. If ``--from-stage > 1`` was passed: honor it (log INFO), return.
4. Auto-detect resolved stage from gap analysis.
5. If detection yields a stage: log INFO, return.
6. Else (truly clean): print "Nothing to resume" and exit 0.

## Out of scope

- The kill-race window between an S5 HTTP 200 and the SQLite
  ``mark_stage_done`` commit. That race leaves docs in Alfresco but
  not in the migration_log; on resume, the same doc tries to upload
  again and Alfresco returns 409. The fix (idempotent 409 handling
  in ``CmisUploader``) is a separate concern with its own design
  surface — deferred to a follow-up spec.
- Reverting the ``--batch-id`` semantics for the "operator wants to
  name a new batch" use case. Today an unrecognized batch_id is
  rejected at ``store.get_batch_details(...)`` — we keep that error
  path. The fix only affects the case where the batch_id refers to
  an existing batch.
- ``--resume`` + N=2 multi-batch overlap. The orchestrator already
  routes ``resume_batch_id`` through ``_run_single`` regardless of
  the requested N, so the fix lands once for all paths.

## Acceptance criteria

- A unit test for ``_apply_resume`` asserts that a batch with
  ``stage_counts={S4: {DONE: 543}, S5: {DONE: 281}}`` resolves to
  ``from_stage=5`` (not "is clean").
- A unit test asserts that ``stage_counts={S5: {DONE: 824}}``
  still resolves to "clean" (no false positives on truly complete
  batches).
- A unit test asserts ``--batch-id X --from-stage 5`` (no
  ``--resume``) produces a ``RunReport`` against the named batch
  without raising ``ValueError``.
- A unit test asserts ``--resume --batch-id X --from-stage 5``
  honors the explicit ``5`` and does NOT exit early as "clean"
  even when no FAILED/PENDING rows exist.
- A live re-run of §H.1 against staging:
  - Run 1: ``--total 50``, kill after ~25 S5_DONE rows.
  - Run 2: ``--resume --batch-id <captured>`` — must NOT print
    "is clean" and must upload the remaining docs to Alfresco.
  - Final Alfresco doc count must match total distinct txns from
    the batch (modulo the deferred 409 race for ~4-10 docs).
- ``CHANGELOG.md [0.47.0]`` entry.
- mypy + ruff clean.

## Notes on test strategy

The unit tests exercise ``_apply_resume`` directly with a fake
``SQLiteTrackingStore.get_batch_details`` return — that lets us
cover the four code paths (FAILED/PENDING priority, S{N}_DONE gap,
explicit override, truly clean) without orchestrating a real run.
The live re-run reproduces the original §H.1 staging scenario end
to end.

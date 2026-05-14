# 047 — Persist cm_object_id on S5_DONE

## Why

The §L.3 step of the validation checklist ("GET a doc by objectId,
pulling the OID from the tracking DB") was found non-functional
during the housekeeping pass: ``migration_log.cm_object_id`` is
``NULL`` for every row, even after a successful upload.

Root cause — ``orchestrators/staged.py``:

```python
cm_object_id = self._uploader.upload(...)        # line 895: CMIS returns the OID
...
self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S5_DONE)  # 929
item.cm_object_id = cm_object_id                 # 930: in-memory ONLY
```

Line 930 assigns the OID onto the in-memory ``_StageItem`` (where it
dies when the run ends). ``mark_stage_done`` — the call that
actually writes to SQLite — only updates ``status`` and
``completed_at``:

```python
def mark_stage_done(self, txn_num, batch_id, stage):
    self._enqueue(
        "UPDATE migration_log SET status = ?, completed_at = ? "
        "WHERE rvabrep_txn_num = ? AND batch_id = ?",
        (stage.value, datetime.now().isoformat(), txn_num, batch_id),
    )
```

The ``cm_object_id`` column already EXISTS in the schema
(``sqlite.py:64``). ``mark_stage_pending`` writes it — but at
S1_PENDING time it's ``None``, and nothing ever back-fills it.

The AS400 path is unaffected — ``IdempotencyCoordinator.mark_uploaded``
DOES pass ``cm_object_id`` through to ``As400NiarvilogStore`` which
writes it to ``OBJIDN``. It's only the SQLite ``migration_log`` that
loses the value. Operators on the SQLite-only path (the common
staging + small-bank case) can't answer "what's the CMIS objectId
of doc X?" from their tracking DB.

## What

### 1. ``ITrackingStore.mark_stage_done`` gains an optional ``cm_object_id``

```python
def mark_stage_done(
    self,
    txn_num: str,
    batch_id: str,
    stage: StageStatus,
    *,
    cm_object_id: str | None = None,
) -> None:
```

Keyword-only, defaults to ``None``. S1..S4 callers don't change —
they pass nothing, the column stays untouched. The S5 caller
passes the real OID.

### 2. ``SQLiteTrackingStore.mark_stage_done`` writes the column when given

When ``cm_object_id`` is not ``None``, the UPDATE also sets the
``cm_object_id`` column:

```sql
UPDATE migration_log
SET status = ?, completed_at = ?, cm_object_id = ?
WHERE rvabrep_txn_num = ? AND batch_id = ?
```

When ``cm_object_id`` is ``None`` the SQL is byte-identical to
today (status + completed_at only) — so S1..S4 transitions and any
``None``-passing caller behave exactly as pre-047.

### 3. ``IdempotencyCoordinator.mark_uploaded`` threads the OID to SQLite

The coordinator already receives ``cm_object_id`` and forwards it
to the AS400 store. It now also forwards it to the SQLite store's
``mark_stage_done`` so both backends carry the value.

### 4. ``staged.py`` S5 path passes the OID

The non-coordinator branch at ``staged.py:929`` becomes:

```python
self._tracking_store.mark_stage_done(
    txn, batch_id, StageStatus.S5_DONE, cm_object_id=cm_object_id
)
```

The ``item.cm_object_id = cm_object_id`` in-memory assignment stays
(some TUI / report code may read it within the run) — it's just no
longer the ONLY place the value lands.

## Out of scope

- Back-filling ``cm_object_id`` for historical batches uploaded
  before 047. Those rows stay ``NULL``; the value is recoverable
  from Alfresco via a children-walk if ever needed.
- Adding ``cm_object_id`` to the ``batch show`` / ``analyze`` CLI
  output. The column is now populated; surfacing it in operator
  reports is a separate, cosmetic change.
- The 045 kill-race window (CMIS 200 → SQLite commit interrupted).
  047 doesn't widen or narrow that window — it only ensures the
  value is in the UPDATE that already happens.
- Schema migration. The column already exists; no ALTER TABLE.

## Acceptance criteria

- Unit test: ``SQLiteTrackingStore.mark_stage_done`` with
  ``cm_object_id="cm-abc"`` results in a row whose ``cm_object_id``
  column reads ``"cm-abc"``.
- Unit test: ``mark_stage_done`` WITHOUT ``cm_object_id`` (the
  S1..S4 path) leaves the column untouched — verified by setting
  it first, then calling ``mark_stage_done`` without the arg, and
  asserting the prior value survives.
- Unit test: ``IdempotencyCoordinator.mark_uploaded`` forwards
  ``cm_object_id`` into the SQLite store's ``mark_stage_done``
  call (mock assertion).
- Live re-verify: a small staging run (``--total 5``) followed by
  a query of ``migration_log`` shows ``cm_object_id`` populated
  (non-NULL) for every ``S5_DONE`` row.
- ``CHANGELOG.md [0.50.0]`` entry.
- mypy + ruff clean. Full unit + integration suite green.

## Notes on test strategy

The SQLite store tests already exercise ``mark_stage_done`` against
a real on-disk SQLite file (Constitution Principle VI — no mocking
the DB). We extend those with the two ``cm_object_id`` cases. The
coordinator test uses the existing ``MagicMock`` SQLite double and
asserts the forwarded kwarg. The live re-verify is a one-line
``sqlite3`` query after a 5-doc run — fast, deterministic, and
closes the §L.3 gap end-to-end.

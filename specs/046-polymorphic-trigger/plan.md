# 046 — Plan

Four phases (~3-4 h total). The phases ship in an order that
keeps the test suite green at each step.

## Phase 1 — Define the Trigger hierarchy (~45 min)

### Files

- `src/cmcourier/domain/models.py`
  - New abstract ``Trigger`` base + ``ClientTrigger`` /
    ``RvabrepRowTrigger`` / ``LocalScanTrigger`` subtypes.
  - Each subtype implements ``audit_row()`` returning
    ``{shortname, cif, system_id}`` with the appropriate
    projection.
  - Backward-compat: keep ``TriggerRecord`` as a public name
    pointing at ``ClientTrigger`` so every existing import keeps
    working without churn.

### Tests

- ``tests/unit/domain/test_trigger.py`` (new):
  - ``ClientTrigger.audit_row`` returns the literal fields.
  - ``RvabrepRowTrigger.audit_row`` projects from RVABREP column
    names via the existing ``RvabrepColumnsConfig``.
  - ``LocalScanTrigger.audit_row`` projects from its captured row.
  - ``TriggerRecord is ClientTrigger`` asserts the alias.

### Commit

```
feat(domain): polymorphic Trigger hierarchy (046 Phase 1)
```

## Phase 2 — S0 strategies emit the right subtype (~1 h)

### Files

- `src/cmcourier/services/triggers/direct_rvabrep.py`
  - Drop the ``(shortname, system_id)`` dedup. Yield one
    ``RvabrepRowTrigger(row=row)`` per non-deleted row.
  - The class docstring updates to reflect "one trigger per
    RVABREP row" (no longer "one per client").
- `src/cmcourier/services/triggers/local_scan.py`
  - Replace the ``TriggerRecord`` yield with
    ``LocalScanTrigger(file_path=entry, row=row)``. The
    multi-match branch (rare RVABREP filename collisions) yields
    one trigger per matched row.
- `src/cmcourier/services/triggers/as400.py`
  - Same shape change as direct_rvabrep — yield
    ``RvabrepRowTrigger(row=row)`` for each SQL row.
- `src/cmcourier/services/triggers/csv.py`
  - No code change. Keeps yielding ``ClientTrigger``
    (== ``TriggerRecord``).
- `src/cmcourier/services/triggers/single_doc.py`
  - No code change. Keeps yielding ``ClientTrigger``.

### Tests

- ``tests/unit/services/triggers/`` files for each strategy get
  their assertions updated to check the new subtype:
  - direct_rvabrep: ``isinstance(t, RvabrepRowTrigger)`` and
    ``t.row[...] == expected``.
  - local_scan: ``isinstance(t, LocalScanTrigger)`` and
    ``t.file_path == expected``.
  - as400: ``isinstance(t, RvabrepRowTrigger)``.

### Commit

```
feat(services): per-pipeline trigger subtypes in S0 strategies (046 Phase 2)
```

## Phase 3 — S1 polymorphic enrichment + CIF helper (~1 h)

### Files

- `src/cmcourier/services/indexing.py`
  - New public method ``enrich(trigger: Trigger) ->
    list[RVABREPDocument]`` that dispatches on subtype:
    - ``ClientTrigger`` → existing ``find_documents`` path.
    - ``RvabrepRowTrigger`` → ``[self._row_to_document(row)]``,
      reusing the existing internal ``_classify`` helper that
      builds the dataclass from a raw row.
    - ``LocalScanTrigger`` → same as the row case.
  - ``find_documents`` and ``find_documents_batch`` stay
    intact for the client path. We don't change their
    signatures.
- `src/cmcourier/services/metadata.py`
  - New module-level helper ``_trigger_cif(trigger) -> str |
    None`` that returns the CIF from whichever attribute the
    trigger carries (``ClientTrigger.cif`` or
    ``X.row[col_cif]``). The resolver's CIF self-healing path
    uses this instead of ``trigger.cif`` directly.
- `src/cmcourier/orchestrators/staged.py`
  - Replace the single ``self._indexing_service.find_documents(t)``
    call in the S1 stage with ``self._indexing_service.enrich(t)``.
  - ``_build_record`` calls ``trigger.audit_row()`` to fill the
    three trigger_* columns; no more direct attribute access.

### Tests

- ``tests/unit/services/test_indexing.py``:
  - ``test_enrich_client_trigger_uses_find_documents`` —
    happy-path delegation.
  - ``test_enrich_rvabrep_row_trigger_skips_data_source`` —
    pass a MagicMock IDataSource that fails on any call; assert
    ``enrich`` returns exactly one document.
  - ``test_enrich_local_scan_trigger_returns_single_doc`` —
    same MagicMock guard; assert one document per trigger
    regardless of how many docs the client has.
- ``tests/unit/services/test_metadata.py``:
  - ``test_trigger_cif_helper`` parametrized over all three
    subtypes, with and without the CIF present.
- ``tests/unit/orchestrators/test_staged.py``: existing tests
  that build a ``TriggerRecord`` and walk the pipeline keep
  passing (they're csv-shaped — they hit the
  ``ClientTrigger`` path).

### Commit

```
feat(services,orchestrators): S1 polymorphic enrich + CIF helper (046 Phase 3)
```

## Phase 4 — Docs + CHANGELOG 0.49.0 + version bump + live re-verify §E.4 + FF (~30 min)

### Files

- `CHANGELOG.md` ``[0.49.0]`` — Added (Trigger hierarchy),
  Changed (local-scan + rvabrep-direct upload set semantics —
  **operationally visible**), Fixed (the §E.4 "over-broad
  expansion" issue we'd previously catalogued as a doc finding).
- `pyproject.toml` 0.48.0 → 0.49.0.
- `README.md` feature row tick.
- `docs/how-to/validation-checklist.md` §E.4 (local-scan):
  update the expected output. Pre-046 we had 1860 docs from a
  pool of 100 files; post-046 we expect exactly 100.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.49.0
```

### Live re-verify

Replicate §E.4 against staging:

```bash
# Wipe both sides
bash scripts/staging/wipe-alfresco-docs.sh
rm -f sample/staging-tracking.db sample/staging-tracking.db-wal sample/staging-tracking.db-shm

# Same scan pool from §E.4
ls sample/local-scan-pool | wc -l   # expect ~200

CMIS_USERNAME=admin CMIS_PASSWORD=admin .venv/bin/cmcourier local-scan-pipeline run \
  --config sample/config-staging-localscan.yaml \
  --total 100 --no-tui
```

Acceptance:

- ``total_triggers == 100`` AND ``total_docs == 100`` (one doc
  per scanned file — no over-broad expansion).
- ``s5_done == 100``, ``s5_failed == 0``.
- Tree-walk of the 21 staging folders confirms 100 docs in
  Alfresco (matching the 100 scanned files exactly).

### Commit

```
docs(046): CHANGELOG 0.49.0 + version bump + local-scan re-verify (046 Phase 4)
```

### FF to main.

# 046 — Tasks

## Phase 1 — Trigger hierarchy in domain

- [ ] 1.1 Abstract ``Trigger`` ABC with ``audit_row()``.
- [ ] 1.2 ``ClientTrigger(shortname, cif, system_id)`` —
      audit_row returns literal fields.
- [ ] 1.3 ``RvabrepRowTrigger(row)`` — audit_row projects
      ``row[col_shortname]`` etc using the shared
      ``RvabrepColumnsConfig`` defaults.
- [ ] 1.4 ``LocalScanTrigger(file_path, row)`` — same projection
      as ``RvabrepRowTrigger``.
- [ ] 1.5 ``TriggerRecord = ClientTrigger`` backward-compat alias
      so every existing import keeps working.
- [ ] 1.6 Unit tests: audit_row per subtype + alias identity.
- [ ] 1.7 mypy + ruff clean.
- [ ] 1.8 Commit
      ``feat(domain): polymorphic Trigger hierarchy (046 Phase 1)``.

## Phase 2 — S0 strategies emit the right subtype

- [ ] 2.1 ``DirectRvabrepTriggerStrategy``: drop
      ``(shortname, system_id)`` dedup; yield
      ``RvabrepRowTrigger`` per non-deleted row.
- [ ] 2.2 ``LocalScanTriggerStrategy``: yield
      ``LocalScanTrigger(file_path, row)`` per scanned file.
- [ ] 2.3 ``As400TriggerStrategy``: yield ``RvabrepRowTrigger``
      per SQL row.
- [ ] 2.4 Update existing strategy unit tests to assert the new
      subtypes.
- [ ] 2.5 mypy + ruff clean.
- [ ] 2.6 Commit
      ``feat(services): per-pipeline trigger subtypes in S0 strategies (046 Phase 2)``.

## Phase 3 — S1 polymorphic enrich + CIF helper

- [ ] 3.1 ``IndexingService.enrich(trigger)`` dispatching on
      subtype; reuses ``find_documents`` for ClientTrigger and
      ``_classify`` for row-based triggers.
- [ ] 3.2 ``_trigger_cif(trigger)`` helper in metadata module.
- [ ] 3.3 ``MetadataResolver`` CIF self-heal uses the helper.
- [ ] 3.4 ``staged.py`` S1 stage calls ``enrich`` instead of
      ``find_documents``; ``_build_record`` uses
      ``trigger.audit_row()``.
- [ ] 3.5 Unit tests: enrich per subtype (with MagicMock guard on
      RvabrepRowTrigger / LocalScanTrigger paths).
- [ ] 3.6 Unit test: ``_trigger_cif`` parametrized over subtypes
      + CIF-present / CIF-absent.
- [ ] 3.7 mypy + ruff clean. Full suite green.
- [ ] 3.8 Commit
      ``feat(services,orchestrators): S1 polymorphic enrich + CIF helper (046 Phase 3)``.

## Phase 4 — docs + CHANGELOG 0.49.0 + version bump + live re-verify + FF

- [ ] 4.1 ``CHANGELOG.md [0.49.0]`` — Added (Trigger hierarchy),
      Changed (local-scan + rvabrep-direct semantics), Fixed
      (§E.4 over-broad expansion).
- [ ] 4.2 ``pyproject.toml`` 0.48.0 → 0.49.0.
- [ ] 4.3 ``.venv/bin/pip install -e . --no-deps``.
- [ ] 4.4 ``cmcourier --version`` reports 0.49.0.
- [ ] 4.5 ``README.md`` feature row tick.
- [ ] 4.6 ``docs/how-to/validation-checklist.md`` §E.4 — update
      expected output (100 docs, not 1860).
- [ ] 4.7 Live re-verify §E.4: 100 files → 100 docs in Alfresco.
- [ ] 4.8 Full unit + integration suite green; ruff + mypy clean.
- [ ] 4.9 Commit
      ``docs(046): CHANGELOG 0.49.0 + version bump + local-scan re-verify (046 Phase 4)``.
- [ ] 4.10 FF to main.

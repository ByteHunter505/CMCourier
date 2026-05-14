# 048 — Plan

Three phases (~2.5 h total).

## Phase 1 — Schema + wiring + delete As400TriggerStrategy (~1 h)

### Files

- `src/cmcourier/config/schema.py`
  - New ``CsvRvabrepSource`` / ``As400RvabrepSource`` models +
    ``RvabrepSourceUnion`` discriminated on ``kind``.
  - Rename ``IndexingSourceConfig`` → ``IndexingConfig``; replace
    its ``csv_path: FilePath`` field with
    ``source: RvabrepSourceUnion``.
  - Remove ``As400TriggerConfig`` from ``TriggerConfigUnion``. The
    config loader now rejects ``trigger.kind: as400`` with a
    discriminated-union error; we add an explicit, friendlier
    check in the loader that points at ``indexing.source``.
  - ``As400ConnectionConfig`` stays (shared with NIARVILOG sync).
- `src/cmcourier/config/wiring.py`
  - New ``_build_rvabrep_source(indexing_cfg, secrets) -> IDataSource``
    dispatching on ``indexing_cfg.source.kind``.
  - ``build_pipeline`` calls it once; the result feeds both
    ``IndexingService`` and ``_build_trigger_strategy``.
  - ``_build_trigger_strategy``: drop the ``As400TriggerConfig``
    branch. ``RvabrepTriggerConfig`` and ``LocalScanTriggerConfig``
    keep using the shared ``rvabrep_src`` (now possibly AS400).
  - Drop the ``As400TriggerStrategy`` import.
- `src/cmcourier/services/triggers/as400.py` — **deleted**.
- `src/cmcourier/services/triggers/__init__.py` — drop the
  ``As400TriggerStrategy`` export.
- `src/cmcourier/services/__init__.py` — same.
- `src/cmcourier/cli/app.py` — if the as400-trigger-pipeline
  subcommand exists as its own CLI entry, fold it: the
  ``as400-trigger-pipeline run`` command is removed (or aliased to
  ``rvabrep-pipeline``). Confirm during implementation.

### Tests

- `tests/unit/config/test_loader.py`:
  - ``test_indexing_source_csv_variant`` — loads, builds a
    ``CsvRvabrepSource``.
  - ``test_indexing_source_as400_variant`` — loads, builds an
    ``As400RvabrepSource`` with the query.
  - ``test_trigger_kind_as400_rejected`` — ``trigger.kind: as400``
    raises ``ConfigurationError`` mentioning ``indexing.source``.
- `tests/integration/config/test_wiring.py`:
  - ``test_build_rvabrep_source_csv`` — returns ``TabularDataSource``.
  - ``test_build_rvabrep_source_as400`` — returns ``As400DataSource``
    (driver-level fake, no live server).
- Delete `tests/.../test_*` cases that target
  ``As400TriggerStrategy`` directly; the as400 SQL path is now
  covered by the ``As400DataSource`` query-mode tests in
  ``test_as400.py``.

### Commit

```
feat(config,wiring): pluggable RVABREP source (CSV ↔ AS400); drop as400 trigger kind (048 Phase 1)
```

## Phase 2 — Migrate all configs + fixtures + tests (~1 h)

### Files

- `sample/config-staging.yaml`,
  `sample/config-staging-rvabrep.yaml`,
  `sample/config-staging-rvabrep-heavy-nolanes.yaml`,
  `sample/config-staging-rvabrep-heavy-lanes.yaml`,
  `sample/config-staging-localscan.yaml`,
  `sample/config-staging-singledoc.yaml`
  - ``indexing:\n  csv_path: X`` →
    ``indexing:\n  source:\n    kind: csv\n    csv_path: X``.
- ~17 integration test files that build YAML inline
  (``_common_blocks`` / ``_write_*_yaml`` helpers): same
  transform. A scripted ``python`` pass handles the uniform
  pattern; stragglers fixed by hand.
- `tests/unit/config/test_loader.py` — any fixture YAML with the
  old shape.
- Delete `sample/config-staging-rvabrep.yaml`'s separate
  ``config-staging-as400.yaml`` if one exists (none observed —
  confirm).

### Tests

- Full unit + integration suite green after migration. No new
  tests here — Phase 1 added the coverage; Phase 2 is mechanical.

### Commit

```
test(config): migrate all configs + fixtures to indexing.source shape (048 Phase 2)
```

## Phase 3 — Docs + CHANGELOG 0.51.0 + version bump + live re-verify + FF (~30 min)

### Files

- `CHANGELOG.md` ``[0.51.0]`` — Added (pluggable RVABREP source),
  Changed (``indexing.csv_path`` → ``indexing.source``; ``as400``
  trigger kind removed), Removed (``As400TriggerStrategy``,
  ``As400TriggerConfig``).
- `pyproject.toml` 0.50.0 → 0.51.0.
- `README.md` feature row tick.
- `docs/how-to/validation-checklist.md` — §0.3 config table +
  §E.3 (the "as400-trigger" section) updated: §E.3 becomes "run
  the rvabrep pipeline with ``indexing.source.kind: as400``".
- `docs/how-to/local-staging-simulation.md` — if it shows an
  ``indexing.csv_path`` snippet, migrate it.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.51.0
```

### Live re-verify (CSV variant — the regression gate)

```bash
bash scripts/staging/wipe-alfresco-docs.sh
rm -f sample/staging-tracking.db sample/staging-tracking.db-wal sample/staging-tracking.db-shm

CMIS_USERNAME=admin CMIS_PASSWORD=admin .venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml --total 5 --no-tui
```

Acceptance: same shape as the 047 verify — 5 triggers, 5 docs,
``s5_done=5 s5_failed=0``, ``cm_object_id`` populated. The
migrated config behaves byte-identically to pre-048.

### Commit

```
docs(048): CHANGELOG 0.51.0 + version bump + indexing.source migration verify (048 Phase 3)
```

### FF to main.

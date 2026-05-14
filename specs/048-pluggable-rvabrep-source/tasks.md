# 048 — Tasks

## Phase 1 — Schema + wiring + delete As400TriggerStrategy

- [ ] 1.1 ``CsvRvabrepSource`` / ``As400RvabrepSource`` +
      ``RvabrepSourceUnion`` discriminated union in ``schema.py``.
- [ ] 1.2 Rename ``IndexingSourceConfig`` → ``IndexingConfig``;
      ``csv_path`` field → ``source: RvabrepSourceUnion``.
- [ ] 1.3 Remove ``As400TriggerConfig`` from ``TriggerConfigUnion``;
      add a friendly loader error for ``trigger.kind: as400``.
- [ ] 1.4 ``wiring.py``: ``_build_rvabrep_source(indexing_cfg,
      secrets)`` dispatching csv/as400.
- [ ] 1.5 ``build_pipeline`` builds the source once, feeds
      ``IndexingService`` + ``_build_trigger_strategy``.
- [ ] 1.6 ``_build_trigger_strategy``: drop the
      ``As400TriggerConfig`` branch + the import.
- [ ] 1.7 Delete ``services/triggers/as400.py``; drop exports from
      ``services/triggers/__init__.py`` + ``services/__init__.py``.
- [ ] 1.8 ``cli/app.py``: confirm + remove/alias the
      ``as400-trigger-pipeline`` CLI command.
- [ ] 1.9 Unit tests: loader csv / as400 variants +
      ``trigger.kind: as400`` rejection.
- [ ] 1.10 Integration tests: ``_build_rvabrep_source`` csv +
      as400.
- [ ] 1.11 Delete ``As400TriggerStrategy``-targeted tests.
- [ ] 1.12 mypy + ruff clean.
- [ ] 1.13 Commit
      ``feat(config,wiring): pluggable RVABREP source (CSV ↔ AS400); drop as400 trigger kind (048 Phase 1)``.

## Phase 2 — Migrate all configs + fixtures + tests

- [ ] 2.1 Migrate the 6 ``sample/config-staging*.yaml`` configs to
      ``indexing.source``.
- [ ] 2.2 Migrate the ~17 integration test files' inline YAML
      (scripted pass for the uniform pattern + hand-fix stragglers).
- [ ] 2.3 Migrate ``tests/unit/config/test_loader.py`` fixture
      YAML.
- [ ] 2.4 Full unit + integration suite green.
- [ ] 2.5 ruff + mypy clean.
- [ ] 2.6 Commit
      ``test(config): migrate all configs + fixtures to indexing.source shape (048 Phase 2)``.

## Phase 3 — docs + CHANGELOG 0.51.0 + version bump + live re-verify + FF

- [ ] 3.1 ``CHANGELOG.md [0.51.0]`` — Added / Changed / Removed.
- [ ] 3.2 ``pyproject.toml`` 0.50.0 → 0.51.0.
- [ ] 3.3 ``.venv/bin/pip install -e . --no-deps``.
- [ ] 3.4 ``cmcourier --version`` reports 0.51.0.
- [ ] 3.5 ``README.md`` feature row tick.
- [ ] 3.6 ``docs/how-to/validation-checklist.md`` §0.3 + §E.3
      updated for the new source shape.
- [ ] 3.7 ``docs/how-to/local-staging-simulation.md`` — migrate
      any ``indexing.csv_path`` snippet.
- [ ] 3.8 Live re-verify: ``config-staging-rvabrep.yaml`` 5-doc
      run, same shape as 047 verify.
- [ ] 3.9 Full suite + ruff + mypy clean.
- [ ] 3.10 Commit
      ``docs(048): CHANGELOG 0.51.0 + version bump + indexing.source migration verify (048 Phase 3)``.
- [ ] 3.11 FF to main.

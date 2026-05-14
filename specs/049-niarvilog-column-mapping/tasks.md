# 049 — Tasks

## Phase 1 — Schema + adapter refactor + wiring + tests

- [ ] 1.1 ``schema.py``: ``_SQL_IDENTIFIER_RE`` + reusable
      identifier validator helper.
- [ ] 1.2 ``schema.py``: ``NiarvilogColumnsModel`` (15 fields,
      canonical defaults, ``field_validator("*")``).
- [ ] 1.3 ``schema.py``: ``As400SyncConfig`` gains
      ``columns: NiarvilogColumnsModel``; ``library`` / ``table``
      gain identifier validation; ``__all__`` updated.
- [ ] 1.4 ``as400_niarvilog.py``: frozen ``NiarvilogColumns``
      dataclass (15 fields, canonical defaults).
- [ ] 1.5 ``as400_niarvilog.py``: ``__init__`` gains ``columns``;
      ``_SELECT_COLUMNS`` → ``_select_columns()``.
- [ ] 1.6 ``as400_niarvilog.py``: rewrite SQL in ``try_claim`` +
      ``_insert_new_claim`` to use ``self._cols``.
- [ ] 1.7 ``as400_niarvilog.py``: rewrite ``mark_uploaded`` /
      ``mark_failed`` / ``mark_uploaded_by_txn`` /
      ``cleanup_stale_in_progress``.
- [ ] 1.8 ``as400_niarvilog.py``: rewrite ``read_state`` /
      ``read_state_by_txn`` SQL + result-dict parsing by configured
      names.
- [ ] 1.9 ``wiring.py``: ``_niarvilog_columns_from_schema`` +
      pass ``columns=`` into ``As400NiarvilogStore``.
- [ ] 1.10 Unit tests: ``NiarvilogColumnsModel`` defaults /
      override / invalid-identifier rejection (incl.
      ``library`` / ``table``).
- [ ] 1.11 Integration tests: ``TestConfigurableColumns`` in
      ``test_as400_niarvilog.py``.
- [ ] 1.12 Integration test: wiring passes columns through.
- [ ] 1.13 Full unit + integration suite green; mypy + ruff clean.
- [ ] 1.14 Commit
      ``feat(config,niarvilog): configurable NIARVILOG column + identifier names (049 Phase 1)``.

## Phase 2 — CHANGELOG 0.52.0 + version bump + docs + FF

- [ ] 2.1 ``CHANGELOG.md [0.52.0]`` — Added / Changed / Security.
- [ ] 2.2 ``pyproject.toml`` 0.51.0 → 0.52.0.
- [ ] 2.3 ``.venv/bin/pip install -e . --no-deps``.
- [ ] 2.4 ``cmcourier --version`` reports 0.52.0.
- [ ] 2.5 ``README.md`` feature row tick.
- [ ] 2.6 ``docs/how-to/as400-sync.md`` — document the ``columns``
      block + identifier rules + per-environment example.
- [ ] 2.7 Full suite + ruff + mypy clean.
- [ ] 2.8 Commit
      ``docs(049): CHANGELOG 0.52.0 + version bump + as400-sync columns docs (049 Phase 2)``.
- [ ] 2.9 FF to main.

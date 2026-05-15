# 049 — Tasks

## Fase 1 — Schema + refactor del adapter + wiring + tests

- [ ] 1.1 ``schema.py``: ``_SQL_IDENTIFIER_RE`` + helper validador
      de identificador reusable.
- [ ] 1.2 ``schema.py``: ``NiarvilogColumnsModel`` (15 campos,
      defaults canónicos, ``field_validator("*")``).
- [ ] 1.3 ``schema.py``: ``As400SyncConfig`` gana
      ``columns: NiarvilogColumnsModel``; ``library`` / ``table``
      ganan validación de identificador; ``__all__`` actualizado.
- [ ] 1.4 ``as400_niarvilog.py``: dataclass frozen
      ``NiarvilogColumns`` (15 campos, defaults canónicos).
- [ ] 1.5 ``as400_niarvilog.py``: ``__init__`` gana ``columns``;
      ``_SELECT_COLUMNS`` → ``_select_columns()``.
- [ ] 1.6 ``as400_niarvilog.py``: reescribir SQL en ``try_claim`` +
      ``_insert_new_claim`` para usar ``self._cols``.
- [ ] 1.7 ``as400_niarvilog.py``: reescribir ``mark_uploaded`` /
      ``mark_failed`` / ``mark_uploaded_by_txn`` /
      ``cleanup_stale_in_progress``.
- [ ] 1.8 ``as400_niarvilog.py``: reescribir SQL de ``read_state`` /
      ``read_state_by_txn`` + parseo del dict resultado por
      nombres configurados.
- [ ] 1.9 ``wiring.py``: ``_niarvilog_columns_from_schema`` +
      pasar ``columns=`` al ``As400NiarvilogStore``.
- [ ] 1.10 Tests unitarios: ``NiarvilogColumnsModel`` defaults /
      override / rechazo de identificador inválido (incl.
      ``library`` / ``table``).
- [ ] 1.11 Tests de integración: ``TestConfigurableColumns`` en
      ``test_as400_niarvilog.py``.
- [ ] 1.12 Test de integración: el wiring pasa las columnas.
- [ ] 1.13 Suite completa unit + integration verde; mypy + ruff
      limpios.
- [ ] 1.14 Commit
      ``feat(config,niarvilog): configurable NIARVILOG column + identifier names (049 Phase 1)``.

## Fase 2 — CHANGELOG 0.52.0 + bump de versión + docs + FF

- [ ] 2.1 ``CHANGELOG.md [0.52.0]`` — Added / Changed / Security.
- [ ] 2.2 ``pyproject.toml`` 0.51.0 → 0.52.0.
- [ ] 2.3 ``.venv/bin/pip install -e . --no-deps``.
- [ ] 2.4 ``cmcourier --version`` reporta 0.52.0.
- [ ] 2.5 Tick en fila de features de ``README.md``.
- [ ] 2.6 ``docs/how-to/as400-sync.md`` — documentar el bloque
      ``columns`` + reglas de identificador + ejemplo
      por-entorno.
- [ ] 2.7 Suite completa + ruff + mypy limpios.
- [ ] 2.8 Commit
      ``docs(049): CHANGELOG 0.52.0 + version bump + as400-sync columns docs (049 Phase 2)``.
- [ ] 2.9 FF a main.

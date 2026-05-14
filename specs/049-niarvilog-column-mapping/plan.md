# 049 — Plan

Two phases (~1.5 h total).

## Phase 1 — Schema + adapter refactor + wiring + tests (~1 h)

### Files

- `src/cmcourier/config/schema.py`
  - New ``NiarvilogColumnsModel`` (``_STRICT``, 15 logical→physical
    fields, canonical defaults, ``field_validator("*")`` enforcing
    the DB2 identifier regex).
  - A shared ``_SQL_IDENTIFIER_RE`` + a reusable validator helper —
    also applied to ``As400SyncConfig.library`` / ``.table`` via a
    ``field_validator`` (pre-049 they were unvalidated).
  - ``As400SyncConfig`` gains
    ``columns: NiarvilogColumnsModel = Field(default_factory=NiarvilogColumnsModel)``.
  - Add ``"NiarvilogColumnsModel"`` to ``__all__``.
- `src/cmcourier/adapters/tracking/as400_niarvilog.py`
  - New frozen ``NiarvilogColumns`` dataclass (15 str fields,
    canonical defaults) — the adapter's own type.
  - ``As400NiarvilogStore.__init__`` gains ``columns:
    NiarvilogColumns | None = None`` → ``self._cols = columns or
    NiarvilogColumns()``.
  - Replace ``_SELECT_COLUMNS`` constant with
    ``_select_columns(self) -> str`` built from ``self._cols``.
  - Rewrite the SQL in ``try_claim``, ``_insert_new_claim``,
    ``mark_uploaded``, ``mark_failed``, ``read_state``,
    ``read_state_by_txn``, ``mark_uploaded_by_txn``,
    ``cleanup_stale_in_progress`` to interpolate ``self._cols.*``
    instead of literal names.
  - ``read_state`` / ``read_state_by_txn``: key the result dict by
    the configured names when building ``NiarvilogRow``.
  - ``STSCOD`` *values* stay literal; ``NiarvilogRow`` field names
    stay logical.
- `src/cmcourier/config/wiring.py`
  - New ``_niarvilog_columns_from_schema(model) -> NiarvilogColumns``
    translator (mirrors ``_indexing_columns_from_schema``).
  - ``_build_idempotency_coordinator`` passes ``columns=`` into
    ``As400NiarvilogStore``.

### Tests

- `tests/unit/config/test_schema.py`:
  - ``NiarvilogColumnsModel`` defaults + partial override.
  - Invalid identifier rejected (space, ``;``, quote, leading
    digit, > 128 chars) — for ``columns.*`` and for
    ``library`` / ``table``.
- `tests/integration/adapters/test_as400_niarvilog.py`:
  - New ``TestConfigurableColumns`` — store built with a
    non-default ``NiarvilogColumns``; assert custom names appear in
    the SQL for ``try_claim`` / ``mark_uploaded`` / ``mark_failed``
    / ``cleanup_stale_in_progress``, and ``read_state`` parses a
    result set keyed by custom names.
  - All existing tests stay green unchanged (default columns →
    byte-identical SQL).
- `tests/integration/config/test_wiring.py`:
  - ``test_build_idempotency_coordinator_passes_columns`` — custom
    ``columns`` block reaches the store.

### Commit

```
feat(config,niarvilog): configurable NIARVILOG column + identifier names (049 Phase 1)
```

## Phase 2 — CHANGELOG 0.52.0 + version bump + docs + FF (~30 min)

### Files

- `CHANGELOG.md` ``[0.52.0]`` — Added (``NiarvilogColumnsModel`` /
  ``tracking.as400_sync.columns``), Changed (``library`` / ``table``
  now identifier-validated), Security (identifier validation closes
  the interpolation surface).
- `pyproject.toml` 0.51.0 → 0.52.0.
- `README.md` feature row tick (51st change / 049).
- `docs/how-to/as400-sync.md` — document the ``columns`` block, the
  identifier rules, and a per-environment example.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.52.0
```

### Verify

No live AS400 in CI — the driver-level fake in
``test_as400_niarvilog.py`` is the regression gate. Run the full
unit + integration suite + ruff + mypy; that is the acceptance
gate for this spec (049 touches no CMIS / pipeline path, so the
staging Alfresco smoke is unaffected and not re-run).

### Commit

```
docs(049): CHANGELOG 0.52.0 + version bump + as400-sync columns docs (049 Phase 2)
```

### FF to main.

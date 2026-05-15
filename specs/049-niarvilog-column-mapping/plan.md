# 049 — Plan

Dos fases (~1.5 h total).

## Fase 1 — Schema + refactor del adapter + wiring + tests (~1 h)

### Archivos

- `src/cmcourier/config/schema.py`
  - Nuevo ``NiarvilogColumnsModel`` (``_STRICT``, 15 campos
    lógico→físico, defaults canónicos, ``field_validator("*")``
    forzando el regex de identificador DB2).
  - Un ``_SQL_IDENTIFIER_RE`` compartido + un helper validador
    reusable — también aplicado a ``As400SyncConfig.library`` /
    ``.table`` vía un ``field_validator`` (pre-049 quedaban sin
    validar).
  - ``As400SyncConfig`` gana
    ``columns: NiarvilogColumnsModel = Field(default_factory=NiarvilogColumnsModel)``.
  - Agregar ``"NiarvilogColumnsModel"`` a ``__all__``.
- `src/cmcourier/adapters/tracking/as400_niarvilog.py`
  - Nuevo dataclass frozen ``NiarvilogColumns`` (15 campos str,
    defaults canónicos) — el tipo propio del adapter.
  - ``As400NiarvilogStore.__init__`` gana ``columns:
    NiarvilogColumns | None = None`` → ``self._cols = columns or
    NiarvilogColumns()``.
  - Reemplazar la constante ``_SELECT_COLUMNS`` con
    ``_select_columns(self) -> str`` construido desde ``self._cols``.
  - Reescribir el SQL en ``try_claim``, ``_insert_new_claim``,
    ``mark_uploaded``, ``mark_failed``, ``read_state``,
    ``read_state_by_txn``, ``mark_uploaded_by_txn``,
    ``cleanup_stale_in_progress`` para interpolar ``self._cols.*``
    en vez de nombres literales.
  - ``read_state`` / ``read_state_by_txn``: keyear el dict
    resultado por los nombres configurados al construir
    ``NiarvilogRow``.
  - Los *valores* ``STSCOD`` quedan literales; los nombres de
    campo de ``NiarvilogRow`` quedan lógicos.
- `src/cmcourier/config/wiring.py`
  - Nuevo traductor ``_niarvilog_columns_from_schema(model) -> NiarvilogColumns``
    (espeja ``_indexing_columns_from_schema``).
  - ``_build_idempotency_coordinator`` pasa ``columns=`` al
    ``As400NiarvilogStore``.

### Tests

- `tests/unit/config/test_schema.py`:
  - ``NiarvilogColumnsModel`` defaults + override parcial.
  - Identificador inválido rechazado (espacio, ``;``, comilla,
    dígito inicial, > 128 chars) — para ``columns.*`` y para
    ``library`` / ``table``.
- `tests/integration/adapters/test_as400_niarvilog.py`:
  - Nuevo ``TestConfigurableColumns`` — store construido con un
    ``NiarvilogColumns`` no-default; assertear que los nombres
    custom aparecen en el SQL para ``try_claim`` /
    ``mark_uploaded`` / ``mark_failed`` /
    ``cleanup_stale_in_progress``, y que ``read_state`` parsea un
    result set keyeado por nombres custom.
  - Todos los tests existentes quedan verdes sin cambios (columnas
    default → SQL byte-idéntico).
- `tests/integration/config/test_wiring.py`:
  - ``test_build_idempotency_coordinator_passes_columns`` —
    bloque ``columns`` custom llega al store.

### Commit

```
feat(config,niarvilog): configurable NIARVILOG column + identifier names (049 Phase 1)
```

## Fase 2 — CHANGELOG 0.52.0 + bump de versión + docs + FF (~30 min)

### Archivos

- `CHANGELOG.md` ``[0.52.0]`` — Added (``NiarvilogColumnsModel`` /
  ``tracking.as400_sync.columns``), Changed (``library`` /
  ``table`` ahora identifier-validados), Security (la validación
  de identificador cierra la superficie de interpolación).
- `pyproject.toml` 0.51.0 → 0.52.0.
- Tick en fila de features de `README.md` (cambio 51 / 049).
- `docs/how-to/as400-sync.md` — documentar el bloque ``columns``,
  las reglas de identificador, y un ejemplo por-entorno.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.52.0
```

### Verify

Sin AS400 en vivo en CI — el fake a nivel driver en
``test_as400_niarvilog.py`` es el gate de regresión. Correr la
suite completa unit + integration + ruff + mypy; ese es el gate
de aceptación para esta spec (049 no toca ningún camino CMIS /
pipeline, así que el smoke contra Alfresco de staging queda
inalterado y no se re-corre).

### Commit

```
docs(049): CHANGELOG 0.52.0 + version bump + as400-sync columns docs (049 Phase 2)
```

### FF a main.

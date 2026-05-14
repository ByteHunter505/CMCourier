# 049 — Configurable NIARVILOG column / identifier names

## Why

The bank runs CMCourier against several AS400 environments (dev /
test / prod, plus per-branch variants). Across those environments the
``NIARVILOG`` coordination table has the **same 15 columns** but the
**physical column names differ**, and the **library / table names**
differ too.

Today only half of that is configurable:

- **RVABREP column names** — already solved. ``IndexingColumnsModel``
  (``schema.py:147``) is a logical→physical column map; the operator
  redefines ``indexing.columns.*`` per environment.
- **NIARVILOG library + table** — already solved.
  ``As400SyncConfig.library`` / ``.table`` (``schema.py:451-452``)
  are wired through to ``As400NiarvilogStore`` (``wiring.py:203-204``).
- **NIARVILOG column names** — **NOT solved.** The 15 physical names
  (``SISCOD``, ``TRNNUM``, ``DOCFRM``, ``IMGARC``, ``IMGTIP``,
  ``CTECIF``, ``CTENUM``, ``STSCOD``, ``IDNBAC``, ``TIPIDN``,
  ``OBJIDN``, ``NUMREI``, ``PMRREI``, ``FINREI``, ``EERRMSG``) are
  **hard-coded** in ``as400_niarvilog.py`` — in the ``_SELECT_COLUMNS``
  constant and in every ``UPDATE`` / ``INSERT`` / ``WHERE`` /
  ``SELECT`` and in the row-parsing dict keys. An environment whose
  NIARVILOG uses different names cannot be configured — it needs a
  code change.

049 closes that gap, symmetric to what ``IndexingColumnsModel`` does
for RVABREP.

## Security note (in scope)

NIARVILOG column / library / table names are **not** bind-parameters
— a SQL identifier can never be a ``?`` placeholder, it has to be
string-interpolated into the statement. That makes every configurable
identifier a potential SQL-injection surface. 049 therefore adds
**identifier validation** to all of them:

- the new ``NiarvilogColumnsModel`` validates each of its 15 fields,
- ``As400SyncConfig.library`` / ``.table`` gain the **same**
  validation (pre-049 they were interpolated into ``_full_table()``
  **unvalidated** — a latent issue this spec also fixes).

A valid identifier matches ``^[A-Za-z@#$][A-Za-z0-9@#$_]{0,127}$``
(DB2 for i ordinary-identifier rules: ``@``, ``#``, ``$`` count as
letters; 128-char max). Anything else raises at config-load time.

## What

### 1. `NiarvilogColumnsModel` in `schema.py`

A new ``BaseModel`` (``_STRICT``) — logical→physical map, 15 fields,
defaults equal to the current hard-coded physical names so existing
configs and tests are byte-identical when the block is omitted:

```python
class NiarvilogColumnsModel(BaseModel):
    model_config = _STRICT
    system_id_column: str = "SISCOD"
    txn_num_column: str = "TRNNUM"
    doc_format_column: str = "DOCFRM"
    image_archive_column: str = "IMGARC"
    image_type_column: str = "IMGTIP"
    client_cif_column: str = "CTECIF"
    client_num_column: str = "CTENUM"
    status_column: str = "STSCOD"
    idcm_column: str = "IDNBAC"
    cm_type_column: str = "TIPIDN"
    cm_object_id_column: str = "OBJIDN"
    retry_count_column: str = "NUMREI"
    started_at_column: str = "PMRREI"
    finished_at_column: str = "FINREI"
    error_message_column: str = "EERRMSG"

    @field_validator("*")
    @classmethod
    def _valid_sql_identifier(cls, v: str) -> str: ...
```

Hangs off ``As400SyncConfig`` as
``columns: NiarvilogColumnsModel = Field(default_factory=...)``.

```yaml
tracking:
  as400_sync:
    enabled: true
    library: MIBIB
    table: MININARVILOG
    connection: {host: 10.0.0.1}
    columns:
      status_column: ESTADO
      txn_num_column: NUMTRX
      # ... any subset; omitted fields keep the canonical default
```

### 2. `NiarvilogColumns` dataclass + SQL builder in the adapter

``as400_niarvilog.py`` already imports ``As400ConnectionConfig`` from
``config.schema`` (line 47), so the constitution's "adapters don't
import schema" boundary is already crossed here for the connection
type. To avoid *deepening* that, 049 introduces a frozen
``NiarvilogColumns`` dataclass **in the adapter module** (the
adapter's own type), and ``wiring.py`` translates
``NiarvilogColumnsModel`` → ``NiarvilogColumns`` — the same pattern
``IndexingService`` uses (``IndexingColumnsModel`` →
``IndexingColumnsConfig``).

``As400NiarvilogStore.__init__`` gains ``columns: NiarvilogColumns |
None = None`` (defaults to ``NiarvilogColumns()`` with canonical
names → every existing caller / test is unaffected).

Every hard-coded SQL identifier is replaced by ``self._cols.<field>``:

- ``_SELECT_COLUMNS`` constant → a ``_select_columns()`` built from
  the model.
- ``try_claim`` — ``UPDATE`` (SET status/idcm/cm_type, WHERE pk +
  status='N') + ``_insert_new_claim`` ``INSERT`` (13 columns).
- ``mark_uploaded`` / ``mark_uploaded_by_txn`` — ``UPDATE`` SET
  status/cm_object_id/error WHERE pk-or-txn.
- ``mark_failed`` — ``UPDATE`` SET status/error/retry WHERE pk.
- ``read_state`` / ``read_state_by_txn`` — ``SELECT`` + the
  ``NiarvilogRow`` construction now keys the result dict by the
  **configured** physical names.
- ``cleanup_stale_in_progress`` — ``UPDATE`` SET status WHERE
  status + finished_at.
- ``_full_table()`` — unchanged shape, but ``library`` / ``table``
  now arrive pre-validated.

The ``STSCOD`` *values* (``'N'`` / ``'I'`` / ``'O'`` / ``'F'``) are
data, not identifiers — they stay literal. ``NiarvilogRow`` keeps its
logical field names (``siscod``, ``trnnum``, …) — it's the adapter's
internal return shape, unaffected.

### 3. Wiring

``_build_idempotency_coordinator`` (``wiring.py:~199``) passes
``columns=_niarvilog_columns_from_schema(sync_cfg.columns)`` into
``As400NiarvilogStore``.

## Out of scope

- RVABREP column-name validation. RVABREP physical names are **not**
  interpolated into SQL — for the AS400 RVABREP source the operator
  supplies the full ``query`` and ``IndexingColumnsModel`` maps the
  *result-set* dict keys (pandas level). No injection surface, no
  change needed.
- Per-environment config profiles / a config-include mechanism. Each
  environment keeps its own full YAML, as today.
- Changing the NIARVILOG **logical schema** (the 15 fields, the
  composite PK, the ``STSCOD`` state machine). 049 only makes the
  *physical names* configurable.
- A migration shim. Pre-production — the only NIARVILOG configs in
  the repo are test fixtures; omitting the ``columns`` block keeps
  the canonical defaults, so nothing to migrate.

## Acceptance criteria

- ``tracking.as400_sync.columns`` loads; omitted → canonical
  defaults; partial → per-field override.
- An invalid identifier (spaces, ``;``, quotes, leading digit,
  > 128 chars) in any ``columns.*`` field, or in ``library`` /
  ``table``, raises ``ValidationError`` / ``ConfigurationError`` at
  load time.
- ``As400NiarvilogStore`` built with a custom ``NiarvilogColumns``
  emits SQL using the custom names — asserted on the captured
  ``(sql, params)`` tuples for ``try_claim`` / ``mark_uploaded`` /
  ``mark_failed`` / ``read_state`` / ``cleanup_stale_in_progress``.
- ``read_state`` parses a result set keyed by **custom** names.
- With default columns, every existing ``test_as400_niarvilog.py``
  assertion still passes (SQL byte-identical for the default case).
- ``wiring`` passes the translated columns through.
- Full unit + integration suite green; mypy + ruff clean.
- ``CHANGELOG.md [0.52.0]`` entry; ``pyproject.toml`` 0.51.0 →
  0.52.0; ``docs/how-to/as400-sync.md`` documents the new block.

## Notes on test strategy

Same approach as the existing ``test_as400_niarvilog.py`` — fake
``pyodbc`` at the cursor/connection boundary, assert on the recorded
SQL strings. 049 adds a ``TestConfigurableColumns`` class that builds
the store with a non-default ``NiarvilogColumns`` and asserts the
custom identifiers appear in the emitted SQL (and the canonical ones
do not). The identifier-validation tests live in
``tests/unit/config/test_schema.py``.

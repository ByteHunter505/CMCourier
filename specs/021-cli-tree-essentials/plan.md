# Plan — 021-cli-tree-essentials

**Status**: Draft
**Spec**: `specs/021-cli-tree-essentials/spec.md`

---

## 1. Architecture in one paragraph

Two domain dataclasses (`BatchInfo`, `BatchDetails`) + three port
extensions on `ITrackingStore` (`list_batches`,
`get_batch_details`, `retry_failed`) + the SQLite implementation
of those + six Click commands across two groups (`batch`, `inspect`)
and one top-level (`as400-query`). The CLI code reads via the
port — no SQLite knowledge leaks. `as400-query` and the inspect
commands reuse the existing wiring (`build_pipeline` returns
collaborators we can introspect directly via the orchestrator's
public attrs, but for these read-only commands we wire the
specific services we need to avoid spinning up the upload stack).

---

## 2. Module layout

```
src/cmcourier/domain/models.py             # +BatchInfo +BatchDetails
src/cmcourier/domain/ports.py              # +3 abstract methods on ITrackingStore
src/cmcourier/adapters/tracking/sqlite.py  # +3 impl methods
src/cmcourier/cli/commands/                # new subpackage (or one file per group)
  batch.py                                 # batch list/show/retry-failed
  inspect.py                               # inspect rvabrep/mapping
  as400_query.py                           # as400-query
src/cmcourier/cli/app.py                   # register new groups/commands
```

The new commands could live inline in `cli/app.py`, but with six
new commands the file would balloon past 600 lines. Move them to
`cli/commands/`. The `cli/commands/__init__.py` already exists
empty — use it.

---

## 3. Domain shapes

```python
@dataclass(frozen=True, slots=True)
class BatchInfo:
    batch_id: str
    started_at: datetime
    completed_at: datetime | None
    total_records: int

    @property
    def status(self) -> str:
        return "completed" if self.completed_at is not None else "in_progress"


@dataclass(frozen=True, slots=True)
class FailedRecord:
    txn_num: str
    stage: str          # e.g., "S5_FAILED"
    error_message: str


@dataclass(frozen=True, slots=True)
class BatchDetails:
    info: BatchInfo
    stage_counts: Mapping[str, Mapping[str, int]]  # {"S1": {"DONE": 10, "FAILED": 0, "PENDING": 0}, ...}
    failed_records: tuple[FailedRecord, ...]
```

---

## 4. Port additions (`ITrackingStore`)

```python
@abstractmethod
def list_batches(
    self, status: Literal["in_progress", "completed"] | None = None
) -> list[BatchInfo]: ...

@abstractmethod
def get_batch_details(self, batch_id: str) -> BatchDetails | None: ...

@abstractmethod
def retry_failed(
    self, batch_id: str, stage: StageStatus | None = None
) -> int: ...
```

---

## 5. SQLite implementation sketches

### 5.1 `list_batches`

```python
def list_batches(self, status=None):
    sql = "SELECT batch_id, started_at, completed_at, total_records FROM migration_batch"
    where_clauses = []
    if status == "in_progress":
        where_clauses.append("completed_at IS NULL")
    elif status == "completed":
        where_clauses.append("completed_at IS NOT NULL")
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY started_at DESC"
    rows = self._conn.execute(sql).fetchall()
    return [_row_to_batch_info(r) for r in rows]
```

### 5.2 `get_batch_details`

```python
def get_batch_details(self, batch_id):
    batch_row = self._conn.execute(
        "SELECT batch_id, started_at, completed_at, total_records "
        "FROM migration_batch WHERE batch_id = ?", (batch_id,)
    ).fetchone()
    if batch_row is None:
        return None
    info = _row_to_batch_info(batch_row)
    # Group rows by status column.
    rows = self._conn.execute(
        "SELECT status, COUNT(*) FROM migration_log "
        "WHERE batch_id = ? GROUP BY status", (batch_id,)
    ).fetchall()
    stage_counts = _pivot_status_counts(rows)
    failed = self._conn.execute(
        "SELECT rvabrep_txn_num, status, COALESCE(error_message, '') "
        "FROM migration_log WHERE batch_id = ? AND status LIKE '%_FAILED'",
        (batch_id,)
    ).fetchall()
    failed_records = tuple(FailedRecord(*row) for row in failed)
    return BatchDetails(info=info, stage_counts=stage_counts, failed_records=failed_records)
```

`_pivot_status_counts({"S1_DONE": 10, "S2_FAILED": 2, ...})` →
`{"S1": {"DONE": 10, "FAILED": 0, "PENDING": 0}, "S2": {..}, ...}`.
Always include all 6 stages (S0..S5) with zeros for missing combos
so the printed table is predictable.

### 5.3 `retry_failed`

```python
def retry_failed(self, batch_id, stage=None):
    if stage is None:
        sql = (
            "UPDATE migration_log "
            "SET status = REPLACE(status, '_FAILED', '_PENDING'), "
            "    error_message = NULL "
            "WHERE batch_id = ? AND status LIKE '%_FAILED'"
        )
        cursor = self._conn.execute(sql, (batch_id,))
    else:
        # stage is a StageStatus like S5_FAILED — derive prefix
        stage_prefix = stage.value.split("_")[0]  # "S5"
        sql = (
            "UPDATE migration_log "
            "SET status = REPLACE(status, '_FAILED', '_PENDING'), "
            "    error_message = NULL "
            "WHERE batch_id = ? AND status = ?"
        )
        cursor = self._conn.execute(sql, (batch_id, f"{stage_prefix}_FAILED"))
    self._conn.commit()
    return cursor.rowcount
```

REPLACE on the status text is safe because the only `_FAILED`
substring in any status value is the suffix.

---

## 6. Click command signatures

### 6.1 `batch` group

```python
@main.group(name="batch")
def batch_group():
    """Batch lifecycle commands."""

@batch_group.command(name="list")
@click.option("--config", "-c", "config_path", required=True, type=click.Path(exists=True))
@click.option("--status", type=click.Choice(["in_progress", "completed"]), default=None)
def batch_list_command(config_path, status): ...

@batch_group.command(name="show")
@click.option("--config", "-c", "config_path", required=True, type=click.Path(exists=True))
@click.argument("batch_id", type=str)
def batch_show_command(config_path, batch_id): ...

@batch_group.command(name="retry-failed")
@click.option("--config", "-c", "config_path", required=True, type=click.Path(exists=True))
@click.option("--batch", "batch_id", required=True, type=str)
@click.option("--stage", type=click.Choice(["S1", "S2", "S3", "S4", "S5"]), default=None)
def batch_retry_failed_command(config_path, batch_id, stage): ...
```

### 6.2 `inspect` group

```python
@main.group(name="inspect")
def inspect_group():
    """Read-only previews of pipeline state."""

@inspect_group.command(name="rvabrep")
@click.option("--config", "-c", "config_path", required=True, type=click.Path(exists=True))
@click.argument("shortname", type=str)
@click.argument("system_id", type=str)
def inspect_rvabrep_command(config_path, shortname, system_id): ...

@inspect_group.command(name="mapping")
@click.option("--config", "-c", "config_path", required=True, type=click.Path(exists=True))
@click.argument("id_rvi", type=str)
def inspect_mapping_command(config_path, id_rvi): ...
```

### 6.3 `as400-query`

```python
@main.command(name="as400-query")
@click.option("--config", "-c", "config_path", required=True, type=click.Path(exists=True))
@click.argument("sql", type=str)
def as400_query_command(config_path, sql): ...
```

---

## 7. Output formatting helpers

Add to `cli/commands/_formatting.py` (or inline in the module that
needs them):

```python
def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a fixed-width text table. ≤2 levels of column padding."""

def truncate(value: str, width: int) -> str:
    """Truncate to ``width`` chars + ellipsis if longer."""
```

Avoid adding `tabulate` or other deps — Python str padding is enough
for operator-facing tables.

---

## 8. Test plan

### 8.1 `tests/unit/adapters/tracking/test_sqlite.py` — +4 tests

- `list_batches` returns empty list on fresh store.
- `list_batches(status="completed")` filters correctly after one
  complete + one incomplete batch.
- `get_batch_details` returns None for unknown id; returns
  populated details for known id with mixed S1_DONE / S2_FAILED.
- `retry_failed(batch_id)` resets all FAILED rows; `retry_failed(
  batch_id, stage=S5_FAILED)` resets only S5.

### 8.2 `tests/integration/cli/test_batch.py` — new file, ~9 tests

`TestBatchList`, `TestBatchShow`, `TestBatchRetryFailed`, each
with help + happy path + error path.

### 8.3 `tests/integration/cli/test_inspect.py` — new file, ~6 tests

`TestInspectRvabrep`, `TestInspectMapping`, each with help + happy
+ no-match path.

### 8.4 `tests/integration/cli/test_as400_query.py` — new file, ~4 tests

Help, happy path with mocked pyodbc, missing creds, SQL error.

### 8.5 `tests/integration/cli/test_operator_flow.py` — new file, 1 e2e

Run csv-trigger-pipeline → batch list shows the run → batch show
returns counts → retry-failed handles a synthetic failure.

---

## 9. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..002 (port + models) | §3, §4 | §8.1 |
| REQ-003..005 (SQLite impl) | §5 | §8.1 |
| REQ-006..008 (Click groups) | §6 | §8.2, §8.3 |
| REQ-009..014 (output) | §6, §7 | §8.2, §8.3, §8.4 |
| REQ-015..020 (errors) | §6 | §8.2, §8.3, §8.4 |
| REQ-021 (observability) | §6 | §8.5 |
| REQ-022..024 (test counts) | §8 | all |
| REQ-025..027 (verification) | — | pytest/mypy |

---

## 10. Files touched

```
EDIT  src/cmcourier/domain/models.py
EDIT  src/cmcourier/domain/ports.py
EDIT  src/cmcourier/adapters/tracking/sqlite.py
NEW   src/cmcourier/cli/commands/batch.py
NEW   src/cmcourier/cli/commands/inspect.py
NEW   src/cmcourier/cli/commands/as400_query.py
NEW   src/cmcourier/cli/commands/_formatting.py
EDIT  src/cmcourier/cli/commands/__init__.py
EDIT  src/cmcourier/cli/app.py
EDIT  tests/unit/adapters/tracking/test_sqlite.py
NEW   tests/integration/cli/test_batch.py
NEW   tests/integration/cli/test_inspect.py
NEW   tests/integration/cli/test_as400_query.py
NEW   tests/integration/cli/test_operator_flow.py
EDIT  CHANGELOG.md
EDIT  README.md
NEW   specs/021-cli-tree-essentials/{spec,plan,tasks}.md
```

---

## 11. Risks

- **R1**: The `retry_failed` UPDATE uses `REPLACE(status,
  '_FAILED', '_PENDING')`. This is safe because the only stage
  values containing `_FAILED` are the failure suffixes — but a
  future change adding a status like `S5_FAILED_RETRYABLE` would
  break this. Mitigation: comment in the implementation; add a
  regression test that ensures only `S?_FAILED` values are
  rewritten.
- **R2**: Adding 3 abstract methods to `ITrackingStore` means
  every existing test that stubs the port must be updated. Search
  for `class.*ITrackingStore` in tests — if there are mocks, fill
  in stub implementations that return empty/None.
- **R3**: `inspect rvabrep` and `inspect mapping` need
  `IndexingService` / `MappingService` initialized from config.
  Build them via wiring helpers without building the full
  pipeline (no uploader needed). Add a thin helper
  `wire_inspection_services(config) -> InspectionServices` in
  `config/wiring.py` or inline in the command.
- **R4**: `as400-query` runs raw user-supplied SQL. PII could leak
  through query results. The command MUST run through the PII
  masking filter (the result cells are written via
  `click.echo`, not via the logger — `click.echo` bypasses
  observability filters). The truncation to 80 chars per cell
  helps but doesn't eliminate the risk. Decision: 021 ships
  `as400-query` as documented-debug-only; operators are
  responsible for the SQL they run. Add a WARNING log line at
  start of execution noting that raw values are displayed.
- **R5**: SQLite `UPDATE ... rowcount` is reliable across SQLite
  versions in Python 3.12 (we verified with sqlite3 module). OK.

---

## 12. Estimated effort

- Spec / plan / tasks: 60 min (done)
- Phase 1 (port + models + SQLite impl + 4 tests): 70 min
- Phase 2 (batch CLI + 9 tests): 60 min
- Phase 3 (inspect + as400-query + ~10 tests): 70 min
- Phase 4 (verification + docs + commit + merge): 30 min
- **Total**: ~3 h 50 min (≈4h)

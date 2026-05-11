# Plan — 023-complete-cli-menus

**Status**: Draft
**Spec**: `specs/023-complete-cli-menus/spec.md`

---

## 1. Architecture in one paragraph

Three new commands. `inspect trigger` and `inspect mapping-stats`
extend the `inspect_group` from 021. `batch export-report`
extends the `batch_group`. All three reuse existing services
(`MappingService`, `S0Strategy` family, `ITrackingStore`
`get_batch_details`). One new helper file
(`cli/commands/_source_descriptor.py`) parses the
`--source csv:<path>` and `--source single_doc:<...>` minilanguage.
No new ports, no new schemas.

---

## 2. Module layout

```
src/cmcourier/cli/commands/inspect.py          # +inspect_trigger_command +inspect_mapping_stats_command
src/cmcourier/cli/commands/batch.py            # +batch_export_report_command
src/cmcourier/cli/commands/_source_descriptor.py  # NEW — parse --source values
tests/integration/cli/test_inspect.py          # +tests
tests/integration/cli/test_batch.py            # +tests
```

`_source_descriptor.py` exists to keep the parser logic isolated
and unit-testable independently of Click.

---

## 3. Public API contracts

### 3.1 `_source_descriptor`

```python
@dataclass(frozen=True, slots=True)
class _ParsedDescriptor:
    scheme: str          # "csv" | "single_doc"
    path: Path | None    # for csv
    shortname: str       # for single_doc
    system_id: str       # for single_doc
    cif: str | None      # for single_doc


def parse_source_descriptor(value: str) -> _ParsedDescriptor:
    """Parse ``csv:<path>`` or ``single_doc:<short>,<sys>[,<cif>]``.

    Raises ``ConfigurationError`` for unknown / unsupported
    schemes with operator-readable guidance.
    """
```

Schemes accepted: `csv:`, `single_doc:`. Other recognized
schemes (`rvabrep:`, `as400:`, `local_scan:`) raise with a
message recommending YAML config.

### 3.2 `inspect_trigger_command`

```python
@inspect_group.command(name="trigger")
@click.option("--config", "-c", "config_path", required=True, ...)
@click.option("--source", "source_descriptor", type=str, default=None,
              help="Override the YAML's trigger.kind. e.g. csv:./t.csv "
                   "or single_doc:SHORT,SYS[,CIF].")
@click.option("--limit", type=click.IntRange(min=1), default=10)
def inspect_trigger_command(config_path, source_descriptor, limit):
    """Preview the first N triggers from a configured or ad-hoc source."""
```

When `source_descriptor` is None → use `config.trigger`; build
strategy via `_build_trigger_strategy` (existing wiring helper)
or a thin local helper that only needs `rvabrep_src` /
`indexing_service` for the rvabrep + local_scan modes. For
csv/as400/single_doc the strategy is self-contained.

### 3.3 `inspect_mapping_stats_command`

```python
@inspect_group.command(name="mapping-stats")
@click.option("--config", "-c", "config_path", required=True, ...)
def inspect_mapping_stats_command(config_path):
    """Print a summary of the Modelo Documental."""
```

Builds `TabularDataSource + MappingService` (no uploader / no
pipeline). Iterates `mapping_service.get_all()` once,
aggregates in memory, prints.

### 3.4 `batch_export_report_command`

```python
@batch_group.command(name="export-report")
@click.option("--config", "-c", "config_path", required=True, ...)
@click.option("--batch", "batch_id", required=True, type=str)
@click.option("--format", "output_format",
              type=click.Choice(["csv", "json"]), required=True)
@click.option("--output", "output_path",
              type=click.Path(dir_okay=False, path_type=Path), default=None)
def batch_export_report_command(config_path, batch_id, output_format, output_path):
    """Export a batch's full state for offline analysis."""
```

---

## 4. Algorithm sketches

### 4.1 inspect trigger flow

```
parse args
load config + secrets
configure observability
if --source given:
    parse_source_descriptor(value)
    build strategy from parsed descriptor (csv | single_doc)
else:
    build strategy from config.trigger (use wiring helpers;
    bypass non-trigger collaborators when possible)
triggers = islice(strategy.acquire(source_descriptor=""), limit)
if no triggers: echo "No triggers produced" to stderr, exit 0
render table (SHORTNAME | CIF | SYSTEM_ID)
close strategy / data sources
emit DEBUG audit log
```

### 4.2 mapping-stats aggregation

```python
total = mapping_service.count()
classes: dict[str, int] = {}
folders: set[str] = set()
types: set[str] = set()
id_corto_count = 0
for m in mapping_service.get_all():
    classes[m.clase_name] = classes.get(m.clase_name, 0) + 1
    folders.add(m.cm_folder)
    types.add(m.cm_object_type)
    if m.id_corto:
        id_corto_count += 1
top5 = sorted(classes.items(), key=lambda kv: kv[1], reverse=True)[:5]
print stats
```

### 4.3 export-report CSV

```
header: batch_id,status,started_at,completed_at,total_records,stage,done,failed,pending
for stage in S0..S5:
    row = [info.batch_id, info.status, info.started_at.isoformat(),
           info.completed_at or "", info.total_records, stage,
           counts[stage]["DONE"], counts[stage]["FAILED"], counts[stage]["PENDING"]]
    csv writer writerow
```

### 4.4 export-report JSON

```python
payload = {
    "batch_id": info.batch_id,
    "status": info.status,
    "started_at": info.started_at.isoformat(),
    "completed_at": info.completed_at.isoformat() if info.completed_at else None,
    "total_records": info.total_records,
    "stage_counts": dict(details.stage_counts),
    "failed_records": [
        {"txn_num": f.txn_num, "status": f.status, "error_message": f.error_message}
        for f in details.failed_records
    ],
}
json.dump(payload, fh, indent=2)
```

---

## 5. Test plan

### 5.1 `tests/unit/cli/commands/test_source_descriptor.py` — NEW, 5 tests

- `csv:./path` → ParsedDescriptor(scheme="csv", path=Path("./path"))
- `single_doc:SHORT,SYS` → scheme="single_doc", cif=None
- `single_doc:SHORT,SYS,CIF` → cif="CIF"
- `rvabrep:` → ConfigurationError with recommend-YAML message
- `unknown_scheme:foo` → ConfigurationError

### 5.2 `tests/integration/cli/test_inspect.py` — +6 tests

`TestInspectTrigger`:
- `--help` lists `--source` and `--limit`
- No `--source` reads from config
- `--source csv:<path>` overrides
- `--source single_doc:X,1,123` yields 1 row
- `--source as400:...` exits 2
- `--limit 2` caps output

`TestInspectMappingStats`:
- `--help`
- Basic summary lists "Total mappings" + "Distinct"
- Top-5 table appears

### 5.3 `tests/integration/cli/test_batch.py` — +5 tests

`TestBatchExportReport`:
- `--help` lists --batch / --format / --output
- CSV stdout (basic shape)
- JSON stdout (parseable + has expected keys)
- `--output` file path: writes file + confirmation
- Unknown batch exits 1

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..007 (inspect trigger) | §3.2, §4.1 | §5.2 TestInspectTrigger |
| REQ-008..009 (mapping-stats) | §3.3, §4.2 | §5.2 TestInspectMappingStats |
| REQ-010..015 (export-report) | §3.4, §4.3, §4.4 | §5.3 |
| REQ-016..018 (observability) | every command | §5.2, §5.3 |
| REQ-019..021 (test counts) | §5 | all |
| REQ-022..024 (verification) | — | pytest/mypy |

---

## 7. Files touched

```
NEW   src/cmcourier/cli/commands/_source_descriptor.py
EDIT  src/cmcourier/cli/commands/inspect.py
EDIT  src/cmcourier/cli/commands/batch.py
NEW   tests/unit/cli/commands/__init__.py
NEW   tests/unit/cli/commands/test_source_descriptor.py
EDIT  tests/integration/cli/test_inspect.py
EDIT  tests/integration/cli/test_batch.py
EDIT  CHANGELOG.md
EDIT  README.md
NEW   specs/023-complete-cli-menus/{spec,plan,tasks}.md
```

---

## 8. Risks

- **R1**: `inspect trigger` without `--source` needs to build
  a trigger strategy from the YAML. The full wiring path goes
  through `build_pipeline` which spins up uploader + tracking
  store too. For inspect we only need the strategy. Mitigation:
  carve out a thin helper `_build_trigger_strategy_only(config,
  secrets)` reusing the wiring's `_build_trigger_strategy`
  internal (already exposed-ish since wiring.py is internal).
- **R2**: `--source single_doc:SHORT,SYS,CIF` — splitting by
  comma works but breaks if CIF contains a comma. Real CIFs
  are digits, but be defensive: split at most 3 ways
  (`value.split(",", 2)`).
- **R3**: `export-report --output` to an unwritable path —
  Python's `open(...)` raises OSError. Catch + exit 2.
- **R4**: `inspect mapping-stats` iterates the full Modelo
  Documental. Today's fixture is ~7 rows; production might be
  hundreds. Still fast — no streaming needed.
- **R5**: The `inspect_group` in 021 doesn't export
  `inspect_trigger_command` — adding two new commands to it
  is mechanical. No conflict with existing `rvabrep` /
  `mapping`.

---

## 9. Estimated effort

- Spec / plan / tasks: 50 min (done)
- Phase 1 (descriptor parser + inspect trigger + 6 tests): 80 min
- Phase 2 (mapping-stats + 3 tests): 40 min
- Phase 3 (export-report + 5 tests): 60 min
- Phase 4 (verification + docs + commit + merge): 30 min
- **Total**: ~4 h

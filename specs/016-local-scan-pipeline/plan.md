# Plan — 016-local-scan-pipeline

**Status**: Draft
**Spec**: `specs/016-local-scan-pipeline/spec.md`

---

## 1. Architecture in one paragraph

One new strategy module (`services/triggers/local_scan.py`)
implementing `S0Strategy`. The strategy lists `scan_path`, filters
to native PDFs + first-page paged files, cross-references each
against the RVABREP source via `IDataSource.get_by_fields(...)`,
and yields `TriggerRecord`. Schema gains
`LocalScanTriggerConfig(kind=local_scan, scan_path)` in the
discriminated union. Wiring dispatches. A new CLI command wraps
the existing `_run_pipeline_command` helper.

Stub removed from `services/triggers/stubs.py` (only the test
fixture remains).

---

## 2. Module layout

```
src/cmcourier/services/triggers/
├── local_scan.py            # NEW — real LocalScanTriggerStrategy
├── stubs.py                 # — LocalScanTriggerStrategy removed
└── __init__.py              # re-export from local_scan
src/cmcourier/services/triggers/direct_rvabrep.py
                              # +file_name_column on RvabrepColumnsConfig
src/cmcourier/config/schema.py
                              # +LocalScanTriggerConfig
src/cmcourier/config/wiring.py
                              # +local_scan dispatch branch
src/cmcourier/cli/app.py
                              # +local-scan-pipeline run command
```

`stubs.py` ends up empty (no remaining stubs). DELETE the file
entirely and update `__init__.py` accordingly.

---

## 3. Public API contracts

### 3.1 `LocalScanTriggerStrategy`

```python
class LocalScanTriggerStrategy(S0Strategy):
    """the spec `local_scan` mode.

    Lists *scan_path* non-recursively, filters to native PDFs
    (``*.PDF`` case-insensitive) and paged-doc first pages
    (``*.001``). For each survivor, queries the RVABREP source via
    ``get_by_fields({file_name_column: <name>})`` and yields one
    ``TriggerRecord`` per matched row.
    """

    def __init__(
        self,
        scan_path: Path,
        rvabrep_source: IDataSource,
        columns: RvabrepColumnsConfig | None = None,
    ) -> None: ...

    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]: ...
```

### 3.2 `LocalScanTriggerConfig`

```python
class LocalScanTriggerConfig(BaseModel):
    model_config = _STRICT
    kind: Literal["local_scan"]
    scan_path: DirectoryPath
```

### 3.3 `RvabrepColumnsConfig` amendment

```python
@dataclass(frozen=True, slots=True)
class RvabrepColumnsConfig:
    col_shortname: str = "ABABCD"
    col_cif: str = "ABACCD"
    col_system_id: str = "ABAACD"
    col_id_rvi: str = "ABAHCD"
    file_name_column: str = "ABAJCD"  # NEW
```

---

## 4. Algorithm sketches

### 4.1 `acquire`

```python
def acquire(self, source_descriptor=""):
    del source_descriptor
    if not self._scan_path.is_dir():
        raise ConfigurationError(
            "scan_path is not a readable directory",
            scan_path=str(self._scan_path),
        )
    for entry in self._scan_path.iterdir():
        if not entry.is_file():
            continue
        if not _is_trigger_filename(entry.name):
            continue
        rows = self._rvabrep.get_by_fields(
            {self._columns.file_name_column: entry.name}
        )
        if not rows:
            _log.warning(
                "local_scan: no RVABREP match for file",
                extra={"file_name": entry.name, "scan_path": str(self._scan_path)},
            )
            continue
        for row in rows:
            shortname = row.get(self._columns.col_shortname)
            if not shortname or (isinstance(shortname, str) and not shortname.strip()):
                continue
            yield TriggerRecord(
                shortname=str(shortname).strip(),
                cif=_clean_cif(row.get(self._columns.col_cif)),
                system_id=str(row.get(self._columns.col_system_id, "")).strip(),
            )


def _is_trigger_filename(name: str) -> bool:
    upper = name.upper()
    return upper.endswith(".PDF") or name.endswith(".001")


def _clean_cif(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return str(value).strip()
```

### 4.2 Wiring branch

```python
if isinstance(trigger_cfg, LocalScanTriggerConfig):
    return LocalScanTriggerStrategy(
        scan_path=trigger_cfg.scan_path,
        rvabrep_source=rvabrep_src,
        columns=RvabrepColumnsConfig(
            col_shortname=config.indexing.columns.shortname_column,
            col_cif=config.indexing.columns.index2_column,
            col_system_id=config.indexing.columns.system_id_column,
            col_id_rvi=config.indexing.columns.index7_column,
            file_name_column=config.indexing.columns.file_name_column,
        ),
    )
```

### 4.3 CLI command

Follows the same pattern as the rvabrep-pipeline command from 014.

---

## 5. Test plan

### 5.1 `tests/unit/services/test_trigger_strategies.py` (~10 new tests for local_scan)

A `TestLocalScanStrategy` class covering:
- Yields one trigger per matched file (happy path with 2 files).
- Skips non-trigger filenames (`.002`, `.txt`, `.tmp`).
- WARNING on unmatched file.
- ConfigurationError on missing `scan_path`.
- Blank shortname row dropped.
- Case-insensitive `.PDF` match.
- Empty CIF → `TriggerRecord.cif = None`.
- Empty `scan_path` directory yields zero triggers.
- Single file matches multiple RVABREP rows → yields one trigger
  per row.
- Friendly column names (override `RvabrepColumnsConfig`).

The stub tests for `LocalScanTriggerStrategy` are REPLACED by the
real-strategy tests (just as 014 did for `As400TriggerStrategy`).

### 5.2 `tests/unit/config/test_schema.py` (~3 new tests)

- `kind=local_scan` config loads to `LocalScanTriggerConfig`.
- Missing `scan_path` raises.
- Unknown `kind=foo` rejected (existing behavior re-tested in
  context).

### 5.3 `tests/integration/config/test_wiring.py` (~1 new test)

- Wiring dispatches to `LocalScanTriggerStrategy` for `kind=local_scan`.

### 5.4 `tests/integration/cli/test_pipeline_kinds.py` (~3 new tests)

- `local-scan-pipeline run --help` lists flags.
- `local-scan-pipeline run` happy path (mocked CMIS).
- `local-scan-pipeline run` exit 2 when YAML has wrong kind.

### 5.5 Stub tests cleanup

`tests/unit/services/test_trigger_strategies.py::TestStubStrategies`
is REMOVED entirely after the local_scan stub is replaced. No
stubs remain.

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..005 (strategy) | §3.1, §4.1 | TestLocalScanStrategy (5.1) |
| REQ-006..008 (schema) | §3.2 | test_schema (5.2) |
| REQ-009..010 (wiring) | §4.2 | test_wiring (5.3) |
| REQ-011 (RvabrepColumnsConfig) | §3.3 | test_local_scan (column-override test) |
| REQ-012 (CLI) | §4.3 | test_pipeline_kinds (5.4) |
| REQ-013 (doctor unchanged) | — | existing tests survive |
| REQ-014 (logging) | §4.1 | TestLocalScanStrategy (warning test) |

---

## 7. Files touched

```
NEW   src/cmcourier/services/triggers/local_scan.py
DEL   src/cmcourier/services/triggers/stubs.py
EDIT  src/cmcourier/services/triggers/__init__.py
EDIT  src/cmcourier/services/triggers/direct_rvabrep.py    # +file_name_column field
EDIT  src/cmcourier/config/schema.py                       # +LocalScanTriggerConfig
EDIT  src/cmcourier/config/wiring.py                       # +dispatch branch
EDIT  src/cmcourier/cli/app.py                             # +local-scan-pipeline group + run
EDIT  tests/unit/services/test_trigger_strategies.py        # +TestLocalScanStrategy, -TestStubStrategies
EDIT  tests/unit/config/test_schema.py                      # +local_scan tests
EDIT  tests/integration/config/test_wiring.py               # +dispatch test
EDIT  tests/integration/cli/test_pipeline_kinds.py          # +local-scan-pipeline tests
EDIT  CHANGELOG.md                                          # [0.18.0]
EDIT  README.md                                             # Status checklist
NEW   specs/016-local-scan-pipeline/{spec,plan,tasks}.md
```

No new dependencies. No new fixtures needed (reuse existing
`tests/fixtures/pipeline/rvabrep.csv` + `tests/fixtures/assembly/`).

---

## 8. Risks

- **Risk**: `Path.iterdir()` ordering is filesystem-dependent. Tests
  that assert on the trigger emission order MUST sort the expected
  values or assert with a set. Mitigation: tests use sets.
- **Risk**: Removing `services/triggers/stubs.py` entirely changes
  `from cmcourier.services.triggers import LocalScanTriggerStrategy`
  to resolve via the new module. The `__init__.py` re-export keeps
  the public path stable.
- **Risk**: `RvabrepColumnsConfig` field addition (`file_name_column`)
  is backwards-compatible (default `"ABAJCD"`), but any callsite
  that uses positional construction breaks. Grep — all callsites use
  kwargs. Verified.
- **Risk**: the CLI tests for `local-scan-pipeline` need a real folder
  with one matching file. The existing assembly fixtures provide
  paged TIFF files (`DAAAH9X4.001`) but their image_path doesn't
  align with the RVABREP fixture's `image_path` column. Mitigation:
  the local_scan strategy only cares about `file_name`, not
  `image_path`; the matching is by filename alone. Use the existing
  `tests/fixtures/assembly/paged_tiff/PROD/2025/11/17/DAAAH9X4.001`
  + add a corresponding row to the test's scan folder (just create
  an empty `DAAAH9X4.001` in `tmp_path`).

---

## 9. Estimated effort

- Spec / plan / tasks: done
- Phase 1 (strategy + 10 tests): 60 min
- Phase 2 (schema + wiring + CLI + ~6 tests): 75 min
- Phase 3 (end-to-end + verification): 30 min
- Phase 4 (docs + commit + merge): 20 min
- **Total**: ~3 h 5 min

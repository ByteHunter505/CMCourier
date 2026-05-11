# Spec — 016-local-scan-pipeline

**Status**: Draft
**Pipeline**: `local-scan-pipeline` (REBIRTH §10.2, §5.1).
**Constitution alignment**: I (the new trigger strategy implements
the existing `S0Strategy` port and consumes the existing
`IDataSource` for RVABREP), III (the strategy is one focused class
≤ 100 LOC), V (config drives everything; the new `kind: local_scan`
fits the discriminated-union pattern).

---

## 1. Intent

Ship the fourth and final production pipeline composition from
REBIRTH §10.2: `local-scan-pipeline`. With this change, the project
covers every trigger source mode the rewrite committed to.

The strategy is:

> **`local_scan`** — Scan a local folder for files, cross-reference
> RVABREP for metadata.

Use case: files have already been extracted from the AS400 file
server to a local directory (e.g., during a one-time bulk
extraction). The pipeline drives discovery off filesystem state
rather than off RVABREP scans or trigger CSVs.

---

## 2. Scope

### In scope

- **`cmcourier.services.triggers.local_scan.LocalScanTriggerStrategy`**
  — real implementation replacing the stub in
  `services/triggers/stubs.py`. The stub is removed from the stubs
  module (matches the 014 pattern when `As400TriggerStrategy` was
  promoted).
- **Algorithm**: list `scan_path` (non-recursive), filter entries
  whose name matches `*.PDF` (native PDFs, case-insensitive) OR
  `*.001` (the first page of a paged document — REBIRTH §3.4
  guarantees paged docs always have a `.001` page). For each
  surviving filename, query the RVABREP source via
  `get_by_fields({file_name_column: name})`. For every matched
  RVABREP row, yield a `TriggerRecord` constructed from the row's
  index1 (shortname), index2 (cif), and system_code (system_id).
  Files with no RVABREP match are dropped with a WARNING log
  carrying the file name and the scan path.
- **Schema**: add `LocalScanTriggerConfig(kind: Literal["local_scan"],
  scan_path: DirectoryPath)`. Extend `TriggerConfigUnion` to include
  the new shape. The existing discriminator-injection logic in the
  loader does NOT default to local_scan (it stays `csv`); operators
  who want local_scan are explicit.
- **Wiring**: `_build_trigger_strategy` gets a `local_scan` branch
  that constructs the strategy over the existing rvabrep source
  (the same one the rvabrep-pipeline uses).
- **CLI**: new `cmcourier local-scan-pipeline run --config <yaml>`
  command, identical surface to the other pipeline commands. The
  `_run_pipeline_command(..., expected_kind="local_scan", ...)`
  helper from 014 wraps the run.
- **Tests**: ~10 unit tests for the strategy, ~3 schema tests, ~2
  wiring + CLI tests, ~1 end-to-end pipeline test.

### Out of scope

- **Recursive folder scanning**. The MVP scans one directory level.
  Operators with nested layouts can either flatten in advance or
  invoke the pipeline once per subdirectory. Recursive support is a
  small follow-up change (one `Path.rglob` call).
- **Per-file image-type filtering**. The scan accepts every `*.PDF`
  and `*.001` regardless of `image_type` in RVABREP. The assembly
  stage later validates page-set consistency.
- **CIF self-healing** via a separate `cif_lookup_source` (the old
  stub had this parameter). 016 simplifies: the CIF comes from
  RVABREP.index2, identical to how the rvabrep-pipeline resolves
  it. The metadata service's existing CIF self-healing rule
  (REBIRTH §6.5) catches trigger.cif=None cases.
- **`source_descriptor` overrides**. The pipeline's vestigial
  `source_descriptor` parameter is ignored; the scan path comes
  from config.

---

## 3. Functional requirements (RFC 2119)

### Strategy

- **REQ-001** `LocalScanTriggerStrategy` MUST live at
  `src/cmcourier/services/triggers/local_scan.py`. The stub of the
  same name in `services/triggers/stubs.py` MUST be REMOVED.
- **REQ-002** Constructor signature:
  ```python
  LocalScanTriggerStrategy(
      scan_path: Path,
      rvabrep_source: IDataSource,
      columns: RvabrepColumnsConfig | None = None,
  )
  ```
  - `columns` defaults to `RvabrepColumnsConfig()` (the defaults
    match REBIRTH §3.2 physical names — `ABABCD` for shortname,
    etc.). Production configs (with friendly column names) pass an
    explicit `columns`.
- **REQ-003** `acquire(source_descriptor: str = "")` MUST:
  - Ignore `source_descriptor` (vestigial port parameter).
  - List `scan_path` non-recursively via `Path.iterdir()`.
  - Filter entries to those whose name matches: extension equals
    `.PDF` (case-insensitive) OR extension equals `.001` (exact
    case).
  - For each surviving entry, run
    `self._rvabrep.get_by_fields({file_name_column: entry.name})`.
  - For every matched row, yield
    `TriggerRecord(shortname=row[index1_column],
    cif=row[index2_column] or None, system_id=row[system_code_column])`.
  - Files with zero matches MUST be logged at WARNING (one line
    per unmatched file) with `extra={"file_name", "scan_path"}`.
  - Empty / blank `shortname` from a matched row MUST be skipped
    silently (matches the CSV strategy's blank-row policy).
- **REQ-004** If `scan_path` does not exist OR is not a directory,
  `acquire` MUST raise `ConfigurationError("scan_path is not a
  readable directory", scan_path=str(scan_path))`.
- **REQ-005** The strategy's import path
  (`cmcourier.services.triggers.local_scan`) MUST be exposed via
  `services/triggers/__init__.py`'s `__all__`.

### Schema

- **REQ-006** `LocalScanTriggerConfig` MUST be added with:
  ```python
  class LocalScanTriggerConfig(BaseModel):
      model_config = _STRICT
      kind: Literal["local_scan"]
      scan_path: DirectoryPath
  ```
- **REQ-007** `TriggerConfigUnion` MUST include
  `LocalScanTriggerConfig` in its union members.
- **REQ-008** The loader's `_inject_default_kinds` MUST NOT default
  to `local_scan`. Operators who want this pipeline declare
  `kind: local_scan` explicitly.

### Wiring

- **REQ-009** `_build_trigger_strategy` MUST gain a branch for
  `LocalScanTriggerConfig` that constructs the strategy:
  ```python
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
- **REQ-010** The wiring MUST NOT require AS400 credentials for
  `local_scan`-kind triggers. The RVABREP source is whatever the
  config's `indexing` block resolves to.

### `RvabrepColumnsConfig` amendment

- **REQ-011** `RvabrepColumnsConfig` MUST gain a `file_name_column`
  field (default `"ABAJCD"`, matching REBIRTH §3.2). The
  LocalScanStrategy uses this to drive
  `get_by_fields({file_name_column: ...})`.

### CLI

- **REQ-012** A new Click command `cmcourier local-scan-pipeline run`
  MUST be added at `cmcourier/cli/app.py`. Flags: identical to the
  other pipeline commands minus `--triggers` (no CSV override for
  local_scan). The command MUST verify
  `config.trigger.kind == "local_scan"` and exit 2 on mismatch.

### Doctor

- **REQ-013** No new doctor check. Existing checks (cmis,
  tracking, mapping, metadata, type alignment, sample dry-run)
  cover local-scan configs. The sample dry-run already exercises
  the strategy via `pipeline._trigger_strategy.acquire()`.

### Logging discipline

- **REQ-014** The strategy's WARNING for unmatched files MUST
  carry the file NAME (e.g., `STRAY.PDF`) but NEVER any inferred
  customer values. Operational keys only.

---

## 4. Acceptance scenarios

### 4.1 Strategy yields TriggerRecord per matched file
- Given a scan folder containing `DAAAH9X4.001` and `0AAAUI0K.PDF`,
  both matched by RVABREP rows.
- When `acquire()` is iterated.
- Then 2 `TriggerRecord` instances are yielded with the
  shortname/cif/system_id from the matched rows.

### 4.2 Strategy filters out non-trigger files
- Given a scan folder containing `DAAAH9X4.001`, `DAAAH9X4.002`,
  `DAAAH9X4.PDF.tmp`, `random.txt`.
- When `acquire()` is iterated.
- Then only `DAAAH9X4.001` is considered (the .002 / .tmp / .txt
  are skipped silently — the .002 is the second page of a paged
  doc and its trigger comes from the .001).

### 4.3 Unmatched files log WARNING
- Given a scan folder with `STRAY.PDF` and no RVABREP row for that
  filename.
- When `acquire()` is iterated.
- Then no TriggerRecord is yielded AND a WARNING log line carries
  `file_name="STRAY.PDF"`.

### 4.4 Missing scan_path raises ConfigurationError
- Given `scan_path = "/does/not/exist"`.
- When `acquire()` is called.
- Then `ConfigurationError(scan_path="/does/not/exist")` raises.

### 4.5 Blank shortname row dropped
- Given a matched RVABREP row whose index1 is empty.
- When `acquire()` is iterated.
- Then no TriggerRecord is yielded for that row.

### 4.6 Schema accepts kind=local_scan
- Given a YAML with `trigger.kind: local_scan` + `scan_path: ...`.
- When `load_config(path)` runs.
- Then `config.trigger` is `LocalScanTriggerConfig`.

### 4.7 Wiring dispatches to LocalScanTriggerStrategy
- Given a `kind=local_scan` config.
- When `build_pipeline` runs.
- Then `pipeline._trigger_strategy` is a `LocalScanTriggerStrategy`.

### 4.8 CLI `local-scan-pipeline run` happy path
- Given a `kind=local_scan` config + a scan folder with one matched
  file + responses-mocked CMIS.
- When `cmcourier local-scan-pipeline run --config <yaml>` runs.
- Then exit code 0; `s5_done >= 1` in stdout.

### 4.9 CLI rejects mismatched kind
- Given a YAML with `kind: csv`.
- When `cmcourier local-scan-pipeline run --config <yaml>` is invoked.
- Then exit 2; stderr names the mismatch.

### 4.10 Native PDF case-insensitive match
- Given files `0AAAUI0K.PDF` and `0AAAUI0K.pdf` (different cases).
- When `acquire()` runs.
- Then both are recognized as native PDFs (the filter is
  `name.upper().endswith(".PDF")`).

---

## 5. Non-functional requirements

- **NFR-001** `cmcourier --help` MUST list FIVE commands after 016:
  `doctor`, `csv-trigger-pipeline`, `rvabrep-pipeline`,
  `as400-trigger-pipeline`, `local-scan-pipeline`.
- **NFR-002** Branch coverage on the new module
  `services/triggers/local_scan.py` MUST be ≥ 90%.
- **NFR-003** Method length cap (Constitution III): ≤ 50 lines per
  method. The `acquire` generator is the longest at ~30 lines.

---

## 6. Tooling expectations

- `ruff check src/ tests/`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean.
- `pre-commit run --all-files`: clean.
- `pytest`: full suite passes; ~16 net new tests.

---

## 7. Open questions / risks

- **Risk**: `Path.iterdir()` on a large folder (100k+ files) is
  slow. For 016 the folder is "already extracted" and bounded by
  the batch size. Mitigation: future change can add a streaming
  iterator if it surfaces.
- **Risk**: `get_by_fields({file_name_column: name})` is O(N) on
  TabularDataSource (CSV adapter). For AS400 it's an indexed
  query. Mitigation: this matches how rvabrep-pipeline works
  today; no regression.
- **Risk**: a `*.PDF.tmp` file matches `*.PDF` if we use loose
  endswith. We use `Path.suffix.upper() == ".PDF"` which checks the
  literal extension. `.PDF.tmp` has suffix `.tmp`, not `.PDF` —
  correctly excluded. Verified by scenario 4.2.
- **Open question**: should the strategy stream-process files (yield
  one trigger as soon as we find a match) or batch-query RVABREP
  with all filenames at once via `get_by_fields_in`?
  **Resolved**: stream. The N×1 query pattern is simpler and matches
  how the CsvTriggerStrategy works. Batching is a performance
  optimization for a future change.
- **Open question**: should `LocalScanTriggerConfig` accept a
  `file_pattern` glob (e.g., `*.001` or `DAAA*.*`) for operators
  with multiple sources mixed in one folder?
  **Resolved**: no. The two-extension filter (`.PDF` + `.001`)
  matches REBIRTH §3.4's naming convention. Operators with custom
  layouts can curate the folder in advance.

# Spec — 023-complete-cli-menus

**Status**: Draft
**Owner**: bitBreaker
**Date**: 2026-05-10
**Predecessors**: 021 (CLI essentials), 022 (safety flags)
**Successors**: TBD (background runner, TUI)

---

## 1. Problem

REBIRTH §11 lists three more menu entries the project hasn't
shipped: `inspect trigger`, `inspect mapping-stats`,
`batch export-report`. Each is a small, focused command that
closes a real triage / post-run-analysis gap:

* **`inspect trigger`** — see the first N triggers a source
  would emit, *without* touching the rest of the pipeline. Today
  the only way to do this is to run a full pipeline with a tiny
  batch and read tracking-store rows.
* **`inspect mapping-stats`** — get a high-level summary of the
  Modelo Documental (how many mappings, how many distinct CM
  classes, how many have ID Corto, etc.). Currently no way
  short of opening the CSV in Excel.
* **`batch export-report`** — dump a batch's full state to CSV
  or JSON for offline analysis (pivot tables, charts, sharing
  with non-CLI stakeholders). Currently `batch show` prints to
  the terminal — fine for one batch, useless for spreadsheet
  workflows.

023 ships all three. No new ports, no schema changes — pure
extensions on top of the existing surfaces.

---

## 2. Goals

- **G1**: `cmcourier inspect trigger [--source <descriptor>]
  [--limit N]` previews triggers. When `--source` is omitted,
  uses the trigger from `config.trigger`. When supplied,
  parses the descriptor and builds a one-off strategy.
- **G2**: `cmcourier inspect mapping-stats` prints a structured
  summary of the Modelo Documental (totals + distinct counts +
  ID Corto coverage + top-N classes by frequency).
- **G3**: `cmcourier batch export-report --batch <id>
  --format csv|json [--output <path>]` dumps a batch's
  `BatchDetails` to stdout (or to a file with `--output`).
- **G4**: All three commands run `observability.setup.configure`
  after `load_config` (consistent with 021/022).
- **G5**: Backwards-compatible. Existing CLI surface unchanged.

## 3. Non-goals

- **NG1**: Supporting every `S0Strategy` source in
  `--source <descriptor>`. MVP supports `csv:<path>` and
  `single_doc:<short>,<sys>[,<cif>]`; the rest emit a clear
  error pointing at the appropriate full-config invocation.
  (Note: the no-`--source` path uses whatever the YAML
  configures, including `as400`/`local_scan`/`rvabrep`.)
- **NG2**: `mapping-stats` doesn't recompute fancy distributions
  (variance, percentiles). Operator-facing summary only.
- **NG3**: `export-report` doesn't paginate or stream. Batches
  with millions of failed records are out of scope; if needed,
  add later.
- **NG4**: No `--output-format` aliasing (e.g., yaml, tsv).
  CSV + JSON is the entire menu.
- **NG5**: No `inspect document <shortname> <system>` (already
  shipped as `inspect rvabrep` in 021, REBIRTH names differ).

---

## 4. Requirements (RFC 2119)

### `inspect trigger`

- **REQ-001**: `cmcourier inspect trigger` MUST accept
  `--config / -c`, optional `--source <descriptor>`, and
  optional `--limit N` (default 10, min 1).
- **REQ-002**: When `--source` is absent, the command MUST
  build the trigger strategy from `config.trigger` using the
  existing wiring helpers. The strategy is closed cleanly
  after consumption.
- **REQ-003**: When `--source csv:<path>` is given, the
  command MUST build a one-off `CsvTriggerStrategy` over a
  `TabularDataSource(<path>)`. Path resolution is relative to
  the operator's `cwd`.
- **REQ-004**: When `--source single_doc:<short>,<sys>` (or
  `<short>,<sys>,<cif>`) is given, the command MUST build a
  `SingleDocTriggerStrategy`. Yields exactly one trigger.
- **REQ-005**: When `--source` is an unknown scheme (or a known
  scheme that requires more config than args can carry —
  `rvabrep:`, `as400:`, `local_scan:`), the command MUST exit 2
  with a clear "use the YAML's trigger.kind / use
  `--config`-only invocation" message.
- **REQ-006**: Output MUST be a text table with columns
  `SHORTNAME | CIF | SYSTEM_ID`, capped at `--limit` rows.
- **REQ-007**: When the source yields zero triggers, MUST
  print "No triggers produced" to stderr and exit 0.

### `inspect mapping-stats`

- **REQ-008**: `cmcourier inspect mapping-stats` MUST accept
  `--config / -c` only.
- **REQ-009**: Output MUST include:
  - `Total mappings: <n>`
  - `Distinct document classes: <n>`
  - `Mappings with ID Corto: <n> / <total>`
  - `Distinct CM object types: <n>`
  - `Distinct CM folders: <n>`
  - Top-5 classes by mapping count (formatted as a small table).

### `batch export-report`

- **REQ-010**: `cmcourier batch export-report` MUST accept
  `--config / -c`, `--batch <id>`, `--format csv|json`, and
  optional `--output <path>`.
- **REQ-011**: With `--output`, MUST write to the path and
  print a one-line confirmation to stdout. Without
  `--output`, MUST stream the report to stdout.
- **REQ-012**: Unknown `batch_id` MUST exit 1 with
  "Batch not found: <id>" to stderr.
- **REQ-013**: CSV format MUST emit:
  - Header row: `batch_id,status,started_at,completed_at,total_records,stage,done,failed,pending`
  - One row per stage (S0..S5), each repeating the batch
    metadata columns. Failed records NOT included (CSV stays
    flat; complex nested data belongs in JSON).
- **REQ-014**: JSON format MUST emit a single JSON object
  with keys `batch_id`, `status`, `started_at`,
  `completed_at`, `total_records`, `stage_counts`,
  `failed_records`. The `stage_counts` value is the
  predictable `S0..S5 × DONE/FAILED/PENDING` shape from
  `BatchDetails`; `failed_records` is a list of
  `{txn_num, status, error_message}` objects.
- **REQ-015**: Exit codes — 0 on success, 1 on batch not
  found, 2 on configuration error, 3 on unhandled exception.

### Observability + PII

- **REQ-016**: Each new command MUST call
  `observability.setup.configure(config.observability, "INFO")`
  after `load_config()`. Constitution VIII (no PII in logs)
  holds; the printed output may contain trigger
  shortname/cif (which themselves are PII per the project)
  — operator responsibility, same as `as400-query` in 021.
- **REQ-017**: `inspect trigger` MUST emit a DEBUG-level
  audit log line noting `source_descriptor` and `limit` so
  triage trails are auditable.
- **REQ-018**: `batch export-report` MUST emit a DEBUG-level
  audit log line on every invocation
  (`reason=export_report`).

### Tests

- **REQ-019**: ≥4 integration tests cover `inspect trigger`
  (help, no --source, --source csv, --source single_doc,
  unknown scheme, zero rows).
- **REQ-020**: ≥3 integration tests cover
  `inspect mapping-stats` (help, basic happy path, fixture
  with multiple classes).
- **REQ-021**: ≥4 integration tests cover
  `batch export-report` (help, CSV stdout, JSON stdout,
  `--output` file write, unknown batch).

### Verification

- **REQ-022**: `pytest` MUST report ≥560 passing.
- **REQ-023**: `mypy src/cmcourier/` MUST report zero errors.
- **REQ-024**: Coverage on the new command modules MUST be ≥85%.

---

## 5. Acceptance scenarios

1. **inspect trigger no --source uses YAML**: A csv-trigger
   config produces a preview of triggers from the configured
   CSV.
2. **inspect trigger --source csv:<path> overrides**: A
   different CSV path is used regardless of the YAML.
3. **inspect trigger --limit 3**: Output capped at 3 rows.
4. **inspect trigger --source single_doc:X,1,123**: One row,
   shortname X, cif 123, system 1.
5. **inspect trigger --source as400:...**: Exits 2 with
   "use --config-only invocation" message.
6. **inspect trigger zero triggers**: Empty CSV → "No triggers
   produced" + exit 0.
7. **inspect mapping-stats basic**: Modelo Documental fixture
   prints "Total mappings: 7" (or whatever the fixture has)
   plus distinct counts + top-5 table.
8. **batch export-report csv stdout**: Emits header + 6 rows
   (S0..S5) for a batch with known stage_counts.
9. **batch export-report json stdout**: Emits valid JSON with
   the documented keys.
10. **batch export-report --output file**: Writes the file +
    prints "Report written to <path>".
11. **batch export-report unknown batch**: Exits 1.
12. **Help responsive**: `cmcourier inspect --help` lists
    `trigger | rvabrep | mapping | mapping-stats`;
    `cmcourier batch --help` lists `list | show | retry-failed | export-report`.

---

## 6. Out of scope (explicit)

- Background runner; TUI.
- Other `--source` schemes for `inspect trigger`
  (rvabrep / as400 / local_scan) — operators use full config
  for those.
- Streaming output for huge batches.
- TSV / YAML / Excel export formats.
- Color / pager / pretty-printing.

---

## 7. References

- REBIRTH §11 — CLI Surface
- 021 — `get_batch_details` + `cli/commands/` subpackage
- 022 — auto-doctor (commands here do NOT auto-doctor — they
  are read-only / offline)

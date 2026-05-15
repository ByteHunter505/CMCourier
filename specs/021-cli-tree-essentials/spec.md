# Spec — 021-cli-tree-essentials

**Status**: Draft
**Owner**: bitBreaker
**Date**: 2026-05-10
**Predecessors**: 007 (SQLite tracking store), 012 (CLI bootstrap), 020 (observability)
**Successors**: TBD (the spec background runner + TUI + export-report)

---

## 1. Problem

the spec commits to a CLI surface with five command groups: the
pipelines (already shipped), `doctor` (013), plus three operational
families — `batch`, `inspect`, and the standalone `as400-query`. The
project ships the pipelines but the operator side is incomplete:

* No way to **see what batches exist** without opening the SQLite
  file with `sqlite3`.
* No way to **retry failed docs** without writing raw UPDATE
  statements.
* No way to **preview a trigger / RVABREP row / mapping** without
  loading the full pipeline.
* No way to **run a debug AS400 query** without a Python REPL.

These gaps make every dry run more painful than it has to be. 021
closes them with six commands — the **operational essentials** —
deferring `inspect trigger`, `inspect mapping-stats`,
`batch export-report`, `doctor --check`, pipeline flag enhancements,
TUI, and the background runner to later changes.

---

## 2. Goals

- **G1**: `cmcourier batch list [--status]` enumerates every batch
  with started/completed/total counts. Operators see state at a
  glance.
- **G2**: `cmcourier batch show <id>` shows per-stage counts
  (`Sn_DONE / Sn_FAILED / Sn_PENDING`) plus batch metadata.
- **G3**: `cmcourier batch retry-failed --batch <id> [--stage Sn]`
  resets `FAILED → PENDING` for the batch (optionally only one
  stage). Returns the count reset.
- **G4**: `cmcourier inspect rvabrep <shortname> <system_id>`
  prints the RVABREP rows that would be selected for one trigger
  — exactly what S1 sees.
- **G5**: `cmcourier inspect mapping <id_rvi>` prints the CM
  mapping (folder + object_type + required metadata fields) for
  a given ID RVI.
- **G6**: `cmcourier as400-query "<SQL>"` runs a raw SQL against
  the AS400 configured in YAML and dumps the result table. Debug
  only.
- **G7**: Every new command uses the same `--config / -c` flag
  surface as existing commands; outputs are operator-friendly
  (text tables for humans, optional `--json` later when needed).

## 3. Non-goals

- **NG1**: `inspect trigger --source <descriptor>` — wider preview
  surface, separate change.
- **NG2**: `inspect mapping-stats` — separate change.
- **NG3**: `batch export-report --format csv|json` — separate
  change.
- **NG4**: `doctor --check <name>` selective flag — separate
  change.
- **NG5**: Pipeline `--skip-doctor / --resume / --from Sn / --no-tui`
  flags — separate change.
- **NG6**: `background --pipeline` runner — separate change.
- **NG7**: TUI — separate change.
- **NG8**: JSON output flag. MVP ships text only; `--json` can be
  bolted on later without surface break.
- **NG9**: Pagination of batch list. Operators with thousands of
  batches will hit limits later; 021 emits all rows.

---

## 4. Requirements (RFC 2119)

### Port extensions

- **REQ-001**: `ITrackingStore` MUST gain three new abstract
  methods:
  - `list_batches(status: BatchStatusFilter | None = None) -> list[BatchInfo]`
  - `get_batch_details(batch_id: str) -> BatchDetails | None`
  - `retry_failed(batch_id: str, stage: StageStatus | None = None) -> int`
- **REQ-002**: Two new frozen dataclasses in
  `cmcourier.domain.models`:
  - `BatchInfo(batch_id, started_at, completed_at, total_records, status)` — status derived (`'completed'` if `completed_at is not None`, `'in_progress'` otherwise).
  - `BatchDetails(info, stage_counts, failed_records)` — `stage_counts: dict[stage_name, dict[outcome, int]]`; `failed_records: tuple[tuple[str, str], ...]` (txn_num, error_message).

### SQLite implementation

- **REQ-003**: `SQLiteTrackingStore.list_batches` SHALL execute
  `SELECT batch_id, started_at, completed_at, total_records FROM migration_batch`
  optionally filtered by status (computed via `completed_at IS NULL`),
  ordered by `started_at DESC`. Returned list MAY be empty.
- **REQ-004**: `SQLiteTrackingStore.get_batch_details` SHALL
  return `None` for unknown `batch_id`. Otherwise aggregates the
  `migration_log` rows by `status` column and returns the
  per-stage counts. Failed records list contains the txn_num +
  error_message of every `FAILED` row.
- **REQ-005**: `SQLiteTrackingStore.retry_failed` SHALL execute
  `UPDATE migration_log SET status = REPLACE(status, '_FAILED', '_PENDING'), error_message = NULL`
  scoped to `batch_id` AND (optionally) `status` starting with the
  given stage. Returns the number of rows reset. Idempotent: if no
  failures, returns 0.

### Click sub-groups

- **REQ-006**: `cmcourier batch` MUST register as a Click group
  with three commands: `list`, `show`, `retry-failed`.
- **REQ-007**: `cmcourier inspect` MUST register as a Click group
  with two commands: `rvabrep`, `mapping`.
- **REQ-008**: `cmcourier as400-query` MUST register as a
  top-level command (no sub-group).

### Output formats

- **REQ-009**: `batch list` MUST output a text table with columns
  `BATCH_ID | STATUS | STARTED | COMPLETED | TOTAL` ordered by
  started DESC.
- **REQ-010**: `batch show` MUST print batch metadata followed by
  a per-stage table:
  ```
  Batch: <id>
  Status: in_progress | completed
  Started: <iso>
  Completed: <iso | ->
  Total records: <n>

  STAGE  DONE  FAILED  PENDING
  S1     ...
  S2     ...
  ...

  FAILED records:
  <txn_num>  <stage>  <error_message-truncated>
  ```
- **REQ-011**: `batch retry-failed` MUST print one line:
  `Reset <n> FAILED rows to PENDING (batch=<id>, stage=<all|Sn>)`.
- **REQ-012**: `inspect rvabrep` MUST print one row per
  RVABREPDocument in the trigger's result set:
  `<txn_num>  <file_name>  <index7>  <total_pages>  <creation_date>`.
- **REQ-013**: `inspect mapping` MUST print:
  ```
  ID RVI: <id_rvi>
  Document class: <clase_name>
  CM folder: <cm_folder>
  CM object type: <cm_object_type>
  Required metadata fields: <field_1>, <field_2>, ...
  ```
- **REQ-014**: `as400-query` MUST print column headers followed by
  one tab-separated row per result. Rows truncated at 80 chars
  per cell to avoid terminal explosion.

### Exit codes

- **REQ-015**: `batch list` / `batch show` / `inspect *` /
  `as400-query`: 0 on success, 2 on configuration error
  (`ConfigurationError`), 3 on unhandled exception.
- **REQ-016**: `batch retry-failed`: 0 even when 0 rows reset.
  Returning 0 reset is not an error.
- **REQ-017**: `batch show <unknown-id>`: print "Batch not
  found: <id>" to stderr and exit 1.

### Error handling

- **REQ-018**: `inspect rvabrep` with a shortname/system_id that
  has no RVABREP rows MUST print "No RVABREP records found" to
  stderr and exit 0 (informational, not an error).
- **REQ-019**: `inspect mapping` with an unknown `id_rvi` MUST
  print "No mapping found for ID RVI: <id_rvi>" to stderr and
  exit 0 (informational).
- **REQ-020**: `as400-query` MUST refuse to run when AS400
  credentials are absent (`AS400_USERNAME` / `AS400_PASSWORD`
  env vars not set). Print a clear error and exit 2.

### Observability

- **REQ-021**: New commands MUST call
  `observability.setup.configure(config.observability, log_level)`
  after `load_config()` (consistent with 020). The app log
  receives a record per command invocation.

### Tests

- **REQ-022**: ≥4 SQLite tracking-store unit tests cover the new
  methods (list with/without status filter, get_batch_details for
  known and unknown id, retry_failed all-stages and per-stage).
- **REQ-023**: ≥3 CLI tests per command (help, happy path,
  error path) for the 6 new commands.
- **REQ-024**: ≥1 integration test runs a real pipeline, lists
  batches, shows details, resets failures — the operator's
  expected flow end-to-end.

### Verification

- **REQ-025**: `pytest` MUST report ≥520 tests passing (current
  502 baseline + ~20 net new).
- **REQ-026**: `mypy src/cmcourier/` MUST report zero errors.
- **REQ-027**: Coverage on `cli/commands/` (or wherever new
  commands live) MUST be ≥85%.

---

## 5. Acceptance scenarios

1. **Empty store**: `cmcourier batch list` on a fresh DB prints a
   "No batches recorded." line and exits 0.
2. **List with batches**: After 3 pipeline runs, `batch list`
   shows 3 rows ordered by `started_at` DESC, with `STATUS`
   reflecting completion.
3. **List filtered**: `batch list --status in_progress` shows
   only batches whose `completed_at` is NULL.
4. **Show known batch**: `batch show <id>` after a successful
   run shows S1..S5 all at `DONE=N, FAILED=0, PENDING=0`.
5. **Show unknown batch**: `batch show ghost-123` exits 1 with
   "Batch not found".
6. **Show batch with failures**: `batch show <id>` after a run
   that had S5 failures lists the failed txn_nums + truncated
   errors.
7. **Retry-failed all**: `batch retry-failed --batch <id>` resets
   every `*_FAILED` row to `*_PENDING`. Output reports the count.
8. **Retry-failed scoped**: `batch retry-failed --batch <id>
   --stage S5` resets only `S5_FAILED` rows. Other stages
   untouched.
9. **Retry-failed empty**: A batch with no failures returns 0
   reset and exits 0.
10. **Inspect rvabrep match**: `inspect rvabrep TESTCLIENT01 1`
    prints the rows that S1 would produce for this trigger.
11. **Inspect rvabrep no-match**: `inspect rvabrep GHOST 99`
    prints "No RVABREP records found" to stderr, exits 0.
12. **Inspect mapping known**: `inspect mapping FF17` prints the
    CM folder + object type + required fields.
13. **Inspect mapping unknown**: `inspect mapping FFXX` prints
    "No mapping found", exits 0.
14. **as400-query success**: With AS400 creds set, `as400-query
    "SELECT * FROM RVILIB.RVABREP FETCH FIRST 3 ROWS ONLY"`
    prints headers + 3 rows.
15. **as400-query missing creds**: Without `AS400_USERNAME`,
    `as400-query "..."` exits 2 with a clear error.
16. **Logging**: After any new command, the file
    `./logs/app-{date}.log` (or configured) contains a JSON line
    recording the invocation. PII discipline still holds.

---

## 6. Out of scope (explicit)

- TUI, background runner, export-report.
- Pipeline `--from / --resume / --skip-doctor / --no-tui` flags.
- `doctor --check <name>` selective flag.
- `inspect trigger`, `inspect mapping-stats`.
- JSON output for the new commands.
- Pagination / sort options.
- Streaming `as400-query` for huge result sets.

---

## 7. References

- the spec — CLI Surface
- the spec / §10.3 — Tracking store + per-stage state
- 007 — SQLite tracking store
- 020 — Observability setup
- Constitution Principle I (ports & adapters) — extension via the
  port, not via direct SQLite access from CLI

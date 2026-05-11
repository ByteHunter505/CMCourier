# Spec — 022-pipeline-safety-flags

**Status**: Draft
**Owner**: bitBreaker
**Date**: 2026-05-10
**Predecessors**: 013 (doctor), 020 (observability), 021 (CLI essentials)
**Successors**: TBD (background runner, TUI, remaining §11 commands)

---

## 1. Problem

The MVP can run end-to-end and the operator surface is wide enough
to be useful, but three pre-dry-run safety gaps remain:

1. **Pipelines bypass pre-flight.** REBIRTH §11 explicitly says
   "doctor is invoked automatically before any pipeline run
   unless `--skip-doctor` is passed." Today every pipeline
   command happily runs against a broken config — the operator
   only learns about a CMIS auth bug 30 seconds in.
2. **Resuming after a failure requires guesswork.** Today an
   operator who wants to retry a batch after partial failure
   must (a) read `batch show` to figure out the lowest stage
   that still has FAILED/PENDING work, (b) compute the right
   `--from-stage` number, and (c) type both flags. A single
   `--resume` flag would do the discovery automatically.
3. **`doctor` is all-or-nothing.** During triage an operator
   already knows the CMIS endpoint is fine but suspects the
   Modelo Documental — running every check (~10 s including dry
   run) just to confirm wastes time. REBIRTH §11 specifies
   `doctor --check connections|mapping|metadata|cm-types|all`.

022 closes those three gaps. No new commands; just safety polish
on what already ships.

---

## 2. Goals

- **G1**: Every pipeline command (`csv-trigger`, `rvabrep`,
  `as400-trigger`, `local-scan`, `single-doc`) runs `doctor`
  before constructing the pipeline. FAIL aborts with exit 2 and
  prints the doctor report. PASS/WARN proceeds.
- **G2**: Pipeline commands accept `--skip-doctor` to bypass the
  pre-flight (kept for dev iteration and trusted-config
  scenarios).
- **G3**: Pipeline commands accept `--resume`. With `--batch-id`
  set, queries the tracking store, finds the lowest stage with
  FAILED or PENDING work, and uses that as `--from-stage`. With
  no work pending, prints "Nothing to resume" and exits 0.
- **G4**: `cmcourier doctor --check <name>` runs only the named
  group:
  - `connections` → cmis_connectivity, as400_connectivity,
    tracking_openable, log_dir_writable
  - `mapping` → mapping_completeness
  - `metadata` → metadata_sources, sample_dry_run
  - `cm-types` → cm_type_alignment
  - `all` (default) → every check (current behavior)
- **G5**: Backwards-compatible. Existing YAMLs, existing CLI
  invocations, existing tests all keep working unchanged.

## 3. Non-goals

- **NG1**: `--no-tui` / `--tui` flags. There is no TUI yet
  (REBIRTH §10.6, separate change).
- **NG2**: `background --pipeline` runner. Separate change.
- **NG3**: Renaming `--from-stage` to `--from Sn` (the README
  shows the latter; we keep the existing flag name to avoid a
  break — they're semantic synonyms).
- **NG4**: Selective check groups beyond the four REBIRTH names.
  Adding new groups is a future change.
- **NG5**: Parallelizing doctor checks. They run serially today;
  optimizing comes later if measured.
- **NG6**: Caching doctor results across pipeline runs.

---

## 4. Requirements (RFC 2119)

### Auto-doctor before pipelines

- **REQ-001**: `_run_pipeline_command` (in `cli/app.py`) MUST
  call `run_doctor(config, secrets)` after observability is
  configured and before `build_pipeline(...)`.
- **REQ-002**: The doctor report MUST be emitted via the
  existing `_emit_doctor_report` helper unless `--skip-doctor`
  was passed (then no doctor output at all).
- **REQ-003**: If `report.has_failures` is True, the pipeline
  command MUST exit 2 BEFORE constructing the pipeline.
- **REQ-004**: WARN/SKIP results MUST NOT block. PASS-only +
  WARN/SKIP proceeds normally.
- **REQ-005**: `--skip-doctor` MUST be a top-level flag on every
  pipeline run command (`csv-trigger-pipeline run`,
  `rvabrep-pipeline run`, `as400-trigger-pipeline run`,
  `local-scan-pipeline run`, `single-doc run`).

### Pipeline `--resume`

- **REQ-006**: All five pipeline run commands MUST accept
  `--resume` (a boolean flag, default False).
- **REQ-007**: `--resume` without `--batch-id` MUST exit 2 with
  a clear "ConfigurationError: --resume requires --batch-id"
  message.
- **REQ-008**: With `--batch-id X --resume`, the command MUST
  call `tracking_store.get_batch_details(X)`. If `None`, exit 1
  with "Batch not found: X". Otherwise inspect the
  `stage_counts` and pick the lowest stage where
  `FAILED + PENDING > 0`.
- **REQ-009**: If every stage shows zero FAILED+PENDING, the
  command MUST print "Nothing to resume — batch <X> is clean"
  and exit 0.
- **REQ-010**: When `--resume` and `--from-stage` are both
  provided, `--from-stage` wins (explicit beats implicit). A
  WARNING log line surfaces the override.

### `doctor --check <name>`

- **REQ-011**: `cmcourier doctor` MUST accept
  `--check <connections|mapping|metadata|cm-types|all>`,
  defaulting to `all`.
- **REQ-012**: When a non-`all` name is passed, the doctor MUST
  run ONLY the checks belonging to that group (see G4).
- **REQ-013**: The report header MUST mention the active filter
  ("Selected checks: <name>") so operators don't mistake a
  partial report for a full one.
- **REQ-014**: Auto-doctor (REQ-001) MUST always run with
  `--check all` semantics (no shortcut from inside the pipeline
  command).
- **REQ-015**: An unknown `--check` value MUST be rejected by
  Click's `click.Choice` validation.

### Logging

- **REQ-016**: Every new branch (auto-doctor, --resume,
  selective doctor) MUST emit a structured app-log event
  describing the decision (with `extra={...}` for `batch_id`,
  `resolved_from_stage`, `selected_checks`, etc.). Constitution
  VIII still holds.

### Tests

- **REQ-017**: ≥6 integration tests cover auto-doctor: 5
  pipelines × happy path + 1 happy path with `--skip-doctor`.
- **REQ-018**: ≥4 integration tests cover `--resume`: missing
  batch_id, unknown batch, mid-pipeline (work pending), clean
  batch (nothing to resume).
- **REQ-019**: ≥4 integration tests cover `doctor --check`:
  each of `connections`, `mapping`, `metadata`, `cm-types`
  runs only its members; `all` matches current behavior.
- **REQ-020**: ≥1 e2e test runs a pipeline with a synthetic
  doctor failure (e.g., unwritable log_dir) → confirms the
  pipeline exits 2 before doing any work.

### Verification

- **REQ-021**: `pytest` MUST report ≥550 passing.
- **REQ-022**: `mypy src/cmcourier/` MUST report zero errors.
- **REQ-023**: `ruff check` / `ruff format --check` clean.

---

## 5. Acceptance scenarios

1. **Auto-doctor happy path**: A YAML with a healthy CMIS stub
   passes doctor, the pipeline runs, exit 0.
2. **Auto-doctor catches CMIS down**: CMIS endpoint returns 503,
   doctor FAILs, pipeline exits 2 with the report.
3. **`--skip-doctor` works**: With `--skip-doctor`, even an
   unreachable CMIS doesn't block; the pipeline tries to run
   (and will fail at S5, but that's a different failure mode).
4. **`--resume` without batch_id**: exits 2 with the error
   message naming the missing flag.
5. **`--resume` with unknown batch_id**: exits 1 with "Batch
   not found".
6. **`--resume` on a clean batch**: exits 0 with "Nothing to
   resume".
7. **`--resume` on a batch with S5_FAILED rows**: the run uses
   `from_stage=5` automatically; output mentions
   `resolved_from_stage=5`.
8. **`--resume` + `--from-stage`**: `--from-stage` wins; a
   WARNING log says the explicit flag overrode --resume.
9. **`doctor --check connections`**: report contains only the 4
   connection checks; header says "Selected checks: connections".
10. **`doctor --check mapping`**: report contains only
    mapping_completeness.
11. **`doctor --check cm-types`**: only cm_type_alignment.
12. **`doctor --check all`** (default): every check (current
    behavior — regression).
13. **Unknown `--check` value**: Click rejects at parse time,
    exit 2.
14. **Logs reflect auto-doctor decisions**: app-log contains
    an event like `{"msg": "doctor_pass", "batch_id": ...}` or
    `doctor_fail` per run.

---

## 6. Out of scope (explicit)

- TUI; background runner; the remaining §11 commands
  (`inspect trigger`, `inspect mapping-stats`,
  `batch export-report`).
- Caching doctor results.
- New doctor check groups beyond the 4 in REBIRTH §11.
- `--from Sn` flag rename.
- Parallelizing doctor checks.

---

## 7. References

- REBIRTH §11 — CLI surface ("doctor is invoked automatically…")
- REBIRTH §10.3 — stage-by-stage resume
- REBIRTH §10.5 — doctor pre-flight checks
- 013 — doctor implementation
- 021 — `get_batch_details` port method (consumed by `--resume`)

# Plan — 022-pipeline-safety-flags

**Status**: Draft
**Spec**: `specs/022-pipeline-safety-flags/spec.md`

---

## 1. Architecture in one paragraph

Three additive features, all in `cli/app.py` + `cli/doctor.py`.
Auto-doctor is a `run_doctor` call inserted in
`_run_pipeline_command` (and the single-doc analogue) right before
`build_pipeline`. `--resume` is a new boolean flag whose handler
opens the tracking store, calls `get_batch_details(batch_id)` (the
port method shipped in 021), inspects `stage_counts`, and resolves
`from_stage` from the lowest stage with non-zero FAILED+PENDING.
`doctor --check <name>` is a new option on the existing doctor
command; it short-circuits the per-check list in `run_doctor` to a
subset. No new modules, no port additions, no schema changes.

---

## 2. Module layout

```
src/cmcourier/cli/app.py            # auto-doctor + --skip-doctor + --resume on 5 commands
src/cmcourier/cli/doctor.py         # run_doctor(check=...) selectivity + group mapping
tests/integration/cli/test_doctor.py        # +4 tests for --check
tests/integration/cli/test_cli.py           # +6 tests for auto-doctor
tests/integration/cli/test_pipeline_kinds.py # +4 tests for --resume
tests/integration/cli/test_operator_flow.py  # +1 e2e (doctor blocks pipeline)
```

The existing `_run_pipeline_command` helper grows by ~20 lines.
The single-doc command body grows similarly. The `doctor_command`
in `cli/app.py` grows by ~3 lines (the new `--check` option).

---

## 3. API contracts

### 3.1 `run_doctor` selectivity

```python
# cli/doctor.py
_CHECK_GROUPS: dict[str, frozenset[str]] = {
    "connections": frozenset({
        "log_dir_writable",
        "cmis_connectivity",
        "as400_connectivity",
        "tracking_openable",
    }),
    "mapping": frozenset({"mapping_completeness"}),
    "metadata": frozenset({"metadata_sources", "sample_dry_run"}),
    "cm-types": frozenset({"cm_type_alignment"}),
    "all": frozenset(),  # sentinel — empty means "every check"
}

def run_doctor(
    config: PipelineConfig,
    secrets: Secrets,
    *,
    selected: str = "all",
) -> DoctorReport:
    """Run pre-flight checks; ``selected`` filters by group."""
```

The existing `run_doctor` body keeps building the full result list,
but at the end filters by group membership when `selected != "all"`.

Wait — that builds every check even when filtered, wasting time.
Better: gate each `results.append(_check_X(...))` line behind a
membership test against the selected group's set.

### 3.2 `_run_pipeline_command` additions

```python
def _run_pipeline_command(
    config_path: Path,
    *,
    expected_kind: _TriggerKind,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    triggers_override: Path | None,
    log_level: str,
    skip_doctor: bool = False,
    resume: bool = False,
) -> None:
    ... # existing config/secrets load ...
    config = _apply_overrides(config, triggers_override, batch_size)
    configure_observability(config.observability, log_level)

    if not skip_doctor:
        try:
            report = run_doctor(config, secrets)
        except Exception:
            _log.exception("auto-doctor crashed unexpectedly")
            sys.exit(3)
        _emit_doctor_report(report)
        if report.has_failures:
            sys.exit(2)

    if resume:
        resolved_from_stage = _resolve_resume_stage(config, batch_id)
        if resolved_from_stage is None:
            # "Nothing to resume" already echoed.
            sys.exit(0)
        if from_stage != 1:
            _log.warning(
                "--from-stage explicit value overrides --resume",
                extra={"explicit_from_stage": from_stage, "resume_inferred": resolved_from_stage},
            )
        else:
            from_stage = resolved_from_stage

    ... # rest of build_pipeline + pipeline.run ...
```

### 3.3 `_resolve_resume_stage` helper

```python
def _resolve_resume_stage(config: PipelineConfig, batch_id: str | None) -> int | None:
    if batch_id is None:
        click.echo("ConfigurationError: --resume requires --batch-id", err=True)
        sys.exit(2)
    store = SQLiteTrackingStore(config.tracking.db_path)
    try:
        details = store.get_batch_details(batch_id)
    finally:
        store.close()
    if details is None:
        click.echo(f"Batch not found: {batch_id}", err=True)
        sys.exit(1)
    for n in (1, 2, 3, 4, 5):
        counts = details.stage_counts.get(f"S{n}", {})
        if counts.get("FAILED", 0) + counts.get("PENDING", 0) > 0:
            return n
    click.echo(f"Nothing to resume — batch {batch_id} is clean")
    return None
```

### 3.4 doctor command additions

```python
@main.command(name="doctor")
@click.option("--config", "-c", "config_path", required=True, type=click.Path(...))
@click.option("--log-level", ...)
@click.option(
    "--check",
    "selected_check",
    type=click.Choice(["connections", "mapping", "metadata", "cm-types", "all"]),
    default="all",
    help="Run only the named check group.",
)
def doctor_command(config_path, log_level, selected_check):
    ...
    report = run_doctor(config, secrets, selected=selected_check)
    ...
```

---

## 4. Algorithm sketches

### 4.1 run_doctor with group filter

Each `results.append(_check_X(...))` becomes:

```python
if _selected_includes("cmis_connectivity", selected):
    results.append(_check_cmis_connectivity(config, secrets))
```

`_selected_includes` returns True when `selected == "all"` OR when
the check name is in `_CHECK_GROUPS[selected]`.

The cm_type_alignment SKIP path stays — if cmis_connectivity wasn't
run (e.g., `--check mapping`), cm_type_alignment isn't run either.
Need to handle the case where `selected == "mapping"` and the user
didn't ask for cmis. In that case we just don't run cm_type_alignment
at all (it's not in the mapping group).

### 4.2 --resume decision tree

```
--resume passed?
├── --batch-id absent  → exit 2 (ConfigurationError)
├── get_batch_details returns None  → exit 1 (Batch not found)
├── stage_counts all clean  → exit 0 ("Nothing to resume")
└── pick lowest S where FAILED+PENDING > 0  → from_stage = N
```

Then if the user ALSO passed --from-stage with a non-default value,
their explicit value wins, log a WARNING.

### 4.3 Auto-doctor placement

Before the existing block:
```python
try:
    pipeline = build_pipeline(config, secrets, pipeline_name=...)
except ConfigurationError as exc:
    ...
```

Insert (when `not skip_doctor`):
```python
try:
    report = run_doctor(config, secrets)
except Exception:
    _log.exception("auto-doctor crashed unexpectedly")
    sys.exit(3)
_emit_doctor_report(report)
if report.has_failures:
    sys.exit(2)
```

---

## 5. Test plan

### 5.1 `tests/integration/cli/test_cli.py` — +6 tests

- Auto-doctor blocks when CMIS down (csv-trigger).
- Auto-doctor blocks when log_dir not writable.
- `--skip-doctor` bypasses (csv-trigger).
- App log records `doctor_pass` event on success.
- App log records `doctor_fail` event on failure.
- Single-doc inherits auto-doctor.

### 5.2 `tests/integration/cli/test_pipeline_kinds.py` — +4 tests

- `--resume` without `--batch-id` exits 2.
- `--resume` with unknown batch_id exits 1.
- `--resume` on clean batch prints "Nothing to resume" + exits 0.
- `--resume` on mid-flight batch (synthetic S2_FAILED) resolves
  `from_stage=2` and re-runs.

### 5.3 `tests/integration/cli/test_doctor.py` — +5 tests

- `doctor --check connections` runs only connection checks (4
  results).
- `doctor --check mapping` runs only mapping_completeness.
- `doctor --check metadata` runs metadata_sources + sample_dry_run.
- `doctor --check cm-types` runs only cm_type_alignment.
- `doctor --check all` is the regression — same as bare doctor.

### 5.4 e2e operator-flow test

In `tests/integration/cli/test_pipeline_kinds.py` or new file:
synthetic config with unwritable log_dir → pipeline run aborts at
auto-doctor → exit 2 → no tracking_log row created.

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..005 (auto-doctor) | §3.2 | §5.1 |
| REQ-006..010 (--resume) | §3.3 | §5.2 |
| REQ-011..015 (doctor --check) | §3.1, §3.4 | §5.3 |
| REQ-016 (logging) | every section | §5.1, §5.2 |
| REQ-017..020 (test counts) | §5 | all |
| REQ-021..023 (verification) | — | pytest/mypy |

---

## 7. Files touched

```
EDIT  src/cmcourier/cli/app.py
EDIT  src/cmcourier/cli/doctor.py
EDIT  tests/integration/cli/test_cli.py
EDIT  tests/integration/cli/test_pipeline_kinds.py
EDIT  tests/integration/cli/test_doctor.py
EDIT  CHANGELOG.md
EDIT  README.md
NEW   specs/022-pipeline-safety-flags/{spec,plan,tasks}.md
```

No new modules, no schema, no port, no dependencies.

---

## 8. Risks

- **R1**: Auto-doctor adds 5–10 s to every pipeline run. Mitigation:
  `--skip-doctor` is the documented escape hatch for dev iteration.
  Production runs run doctor by default — that's the whole point.
- **R2**: Doctor's `sample_dry_run` does S1..S4 on the first doc.
  Auto-doctor before a pipeline means we do S1..S4 twice on the
  first doc (once in doctor, once in the real run). Idempotent
  but wasteful. Acceptable for MVP; optimizing later if measured.
- **R3**: `--resume` with `--batch-id` and `--from-stage` together
  is ambiguous. The spec rules it (explicit `--from-stage` wins,
  WARNING log surfaces it) — implementation must not silently
  drop one or the other.
- **R4**: `doctor --check` selectivity has interaction with the
  cm_type_alignment SKIP fallback. The fallback only triggers if
  cmis_connectivity was run and FAILED. If cmis isn't in the
  selected group, cm_type_alignment isn't run at all — no SKIP
  fallback needed. Plan §4.1 handles this implicitly.
- **R5**: Existing tests that invoke pipelines might now hit
  auto-doctor and fail because their mocked CMIS isn't perfect
  enough for the full doctor checklist. Mitigation: add
  `--skip-doctor` to tests that exercise pipeline behavior
  without setting up complete doctor scaffolding; preserve a
  subset that exercises the new auto-doctor path explicitly.

---

## 9. Estimated effort

- Spec / plan / tasks: 50 min (done)
- Phase 1 (auto-doctor + skip-doctor + 6 tests): 60 min
- Phase 2 (--resume + helper + 4 tests): 60 min
- Phase 3 (doctor --check + 5 tests): 60 min
- Phase 4 (verification + docs + commit + merge): 30 min
- **Total**: ~3 h 30 min

# Spec — 024-background-runner

**Status**: Draft
**Owner**: bitBreaker
**Date**: 2026-05-10
**Predecessors**: 020 (observability), 022 (safety flags), 023 (CLI menus)
**Successors**: TBD (TUI — the spec)

---

## 1. Problem

the spec commits to a `cmcourier background --pipeline <name>`
entry point designed for **unattended execution** (cron,
systemd-timer, supervised service). The MVP today only ships the
interactive `csv-trigger-pipeline run` / `rvabrep-pipeline run` /
… commands. Those work for hand-driven runs but expose two gaps
for scheduled execution:

1. **No instance lock.** Two overlapping cron runs would race
   on the tracking store. SQLite WAL would protect rows but the
   batch lifecycle (start_batch / mark_stage_* / close_batch)
   would interleave badly. Operators need a hard guarantee that
   only one pipeline instance runs per config at a time.
2. **Stdout chatter on success.** Cron's default behavior is
   "anything on stdout/stderr triggers an email". The current
   pipelines print a `_emit_summary` line on every successful
   run. With a daily cron that's a spam email a day. The
   structured logs (020) already capture everything an operator
   needs — stdout should be silent on success.

024 ships `cmcourier background --pipeline <kind>` with a
**file-based per-config lock** (fcntl + LOCK_EX | LOCK_NB) and a
**quiet-on-success output mode**. Both behaviors are isolated to
the new command — the existing pipeline run commands are
unchanged.

---

## 2. Goals

- **G1**: `cmcourier background --pipeline <kind>` dispatches to
  one of the four production pipelines (csv-trigger, rvabrep,
  as400-trigger, local-scan). `single-doc` is NOT supported
  because it requires `--shortname / --system / --cif` per
  invocation — that's not a cron use case.
- **G2**: Holds an exclusive per-config lock for the duration of
  the run. Second instance for the same config exits 75
  (EX_TEMPFAIL) without running.
- **G3**: Quiet on success: stdout silent, stderr only carries
  doctor failures (the spec quiet semantics for cron).
  Observability tiers (app log, metrics, network, slow-ops) keep
  recording.
- **G4**: Auto-doctor stays ON by default (cron NEEDS pre-flight
  more, not less). `--skip-doctor` opt-out available.
- **G5**: Lock file path is deterministic: same config path →
  same lock file → predictable cron behavior.
- **G6**: Lock released automatically on process exit (even on
  SIGKILL — kernel handles fd close).

## 3. Non-goals

- **NG1**: TUI integration / `--no-tui` flag — there is no TUI
  yet. (When the TUI lands, `background` is implicitly no-TUI.)
- **NG2**: Distributed locks (Redis, etcd, NFS-safe). The lock
  is per-host fcntl. Two hosts running the same config against
  the same tracking SQLite would NOT be blocked — but that's an
  operator misconfiguration, not a runner bug.
- **NG3**: Lock-retry logic. Second instance exits immediately
  with 75. Operators handle retries via cron / systemd.
- **NG4**: `single-doc` support. Out of scope (the spec
  positions `single-doc` as ad-hoc, not scheduled).
- **NG5**: Background-only flags (e.g., `--max-runtime`,
  `--checkpoint-interval`). The MVP runs to completion or
  exits.
- **NG6**: PID-file convention. The lock file does store the
  PID for debugging, but operators MUST NOT use it for process
  control — the fcntl lock is authoritative.
- **NG7**: Windows support. `fcntl` is POSIX. Project is
  Linux/macOS only.

---

## 4. Requirements (RFC 2119)

### Command surface

- **REQ-001**: A new top-level command
  `cmcourier background --pipeline <kind> --config <yaml>` MUST
  register on the root `main` group.
- **REQ-002**: `--pipeline` MUST be a Click `Choice` of exactly
  `csv-trigger | rvabrep | as400-trigger | local-scan`.
- **REQ-003**: The command MUST accept the same operational
  flags as the regular pipeline run commands: `--batch-id`,
  `--from-stage`, `--batch-size`, `--resume`, `--skip-doctor`.
- **REQ-004**: `--log-level` MUST default to `WARNING`
  (quieter than the interactive `INFO` default). INFO is still
  available with `--log-level INFO`.

### Lock semantics

- **REQ-005**: At command entry (BEFORE config load and
  observability setup), the command MUST attempt to acquire a
  per-config exclusive lock via the new
  `cmcourier.cli.commands._lock` module.
- **REQ-006**: Lock file path MUST be
  `<runtime-dir>/cmcourier/<digest>.lock` where:
  - `<runtime-dir>` is `$XDG_RUNTIME_DIR` if set and writable,
    else `/tmp` (POSIX always-writable).
  - `<digest>` is the first 12 hex chars of
    `sha256(str(config_path.resolve()))`.
- **REQ-007**: The lock MUST use `fcntl.flock(fd,
  LOCK_EX | LOCK_NB)`. On contention (`BlockingIOError`), the
  command MUST exit 75 (`os.EX_TEMPFAIL`) and print
  `Another instance is running: <lock_path>` to stderr.
- **REQ-008**: On acquisition, the command MUST write the
  current PID + ISO8601 UTC start timestamp to the lock file
  (overwrite, no rotation) for operator debugging.
- **REQ-009**: The lock MUST be released automatically on
  process exit (normal, exception, SIGTERM, SIGKILL — kernel
  semantics). Test coverage: a normal-exit path test confirms
  release.
- **REQ-010**: Lock file content MUST NOT contain PII.
  PID + ISO timestamp + config path are operator metadata,
  not customer data — explicitly safe.

### Quiet success

- **REQ-011**: On success (every doc reached S5_DONE,
  `report.s5_failed == 0`), the command MUST NOT print
  anything to stdout or stderr beyond what the doctor /
  observability layer would have already emitted.
- **REQ-012**: On failure (`report.s5_failed > 0`), the
  command MUST print a single-line error summary to stderr:
  `pipeline=<kind> batch_id=<id> s5_failed=<n> exit_code=1`.
  Exit code 1 (matches the interactive commands).
- **REQ-013**: On `ConfigurationError`, MUST print
  `ConfigurationError: <message>` to stderr and exit 2.
- **REQ-014**: On unhandled exception inside `pipeline.run`,
  MUST print `Unhandled error during pipeline.run — see logs`
  to stderr and exit 3 (the orchestrator log already captures
  the traceback).

### Dispatch + reuse

- **REQ-015**: The command's implementation MUST reuse the
  existing `_run_pipeline_command` helper from `cli/app.py`,
  extended with a `quiet: bool = False` keyword argument that
  suppresses the `_emit_summary` stdout line on success.
- **REQ-016**: The auto-doctor path (022) MUST execute
  identically to the interactive commands. `--skip-doctor`
  bypasses it.
- **REQ-017**: The `--resume` path (022) MUST execute
  identically. `_apply_resume`'s `Nothing to resume` exit-0
  message goes to stdout in interactive mode; in background
  mode the message MUST suppress (still exit 0) so cron
  emails stay silent.

### Observability

- **REQ-018**: The command MUST call
  `observability.setup.configure(config.observability, log_level)`
  after `load_config()`, identical to the regular pipelines.
- **REQ-019**: The command MUST log a `background_started`
  INFO event before `pipeline.run` with `extra={"pipeline":
  kind, "lock_path": str(lock_path), "pid": os.getpid()}`.
- **REQ-020**: On lock contention, the command MUST log a
  WARNING event `background_lock_held` with `extra={"lock_path":
  str(lock_path)}` before exiting 75.

### Tests

- **REQ-021**: ≥4 unit tests cover the lock module:
  acquire-release, contention-rejects, deterministic-path,
  PID written.
- **REQ-022**: ≥4 integration tests cover the background
  command: help, happy path (csv-trigger kind), lock-held
  exit 75, --skip-doctor + --resume passthrough.

### Verification

- **REQ-023**: `pytest` MUST report ≥580 passing.
- **REQ-024**: `mypy src/cmcourier/` MUST report zero errors.
- **REQ-025**: `ruff check` / `ruff format --check` clean.

---

## 5. Acceptance scenarios

1. **Help**: `cmcourier background --help` lists `--pipeline`,
   `--config`, `--batch-id`, `--from-stage`, `--batch-size`,
   `--resume`, `--skip-doctor`, `--log-level`.
2. **Pipeline choice enforced**: `--pipeline single-doc` is
   rejected by Click's Choice (exit 2).
3. **Happy path csv-trigger**: With a healthy config + CMIS
   stubs, `cmcourier background --pipeline csv-trigger -c y.yaml`
   exits 0 with empty stdout. The app log records the run.
4. **Lock contention**: Two processes calling `background`
   on the same config concurrently — second one exits 75
   without running. (Verified via subprocess race in tests.)
5. **Lock released on exit**: After a normal run completes,
   the same config can be invoked again immediately and
   acquires the lock fine.
6. **--skip-doctor passthrough**: With an unstubbed CMIS but
   `--skip-doctor`, the doctor block is bypassed (pipeline
   still fails at S5, exit 1 — but doctor never ran).
7. **--resume passthrough**: Background with `--resume` +
   `--batch-id` resolves the from-stage from tracking state,
   same as interactive.
8. **Quiet success**: A successful csv-trigger run produces
   zero stdout output (no `s5_done=N` summary line).
9. **Failure surface**: If s5_failed > 0, a single
   `pipeline=csv-trigger batch_id=... s5_failed=N exit_code=1`
   line goes to stderr; exit code 1.
10. **Config error**: `--config /no/such/file.yaml` exits 2
    (Click validation).
11. **Lock file contents**: After a run, the lock file
    contains a single line: `<pid> <iso-timestamp>`. No PII.

---

## 6. Out of scope (explicit)

- TUI / `--no-tui` flag.
- Distributed locks; cross-host coordination.
- Lock-retry policy inside the runner (cron's job).
- `--max-runtime` / hard timeout.
- `single-doc` support.
- Windows.
- Metrics for lock contention (could go to slow-ops in a
  future change).

---

## 7. References

- the spec — CLI Surface (`background` entry)
- POSIX `fcntl(2)` and `flock(2)` semantics
- `os.EX_TEMPFAIL` (75) — sysexits.h convention for
  "transient failure, retry later"
- 022 — auto-doctor + `--resume` (reused here)
- 023 — `cli/commands/` subpackage (home for the new module)

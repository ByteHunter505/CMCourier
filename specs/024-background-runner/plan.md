# Plan — 024-background-runner

**Status**: Draft
**Spec**: `specs/024-background-runner/spec.md`

---

## 1. Architecture in one paragraph

One new command (`background`) + one new helper module
(`_lock.py`). The command opens a per-config fcntl lock, then
dispatches into the existing `_run_pipeline_command` helper
(which already handles auto-doctor + --resume) with two new
behaviors: `quiet=True` (suppress _emit_summary on success) and
`failure_summary=True` (write a single stderr line on s5_failed).
The lock is held for the duration of the run via context manager;
release is automatic on any exit path.

---

## 2. Module layout

```
src/cmcourier/cli/commands/_lock.py        # NEW — fcntl per-config lock
src/cmcourier/cli/commands/background.py   # NEW — the new command
src/cmcourier/cli/app.py                   # register background; extend _run_pipeline_command with quiet kwarg
tests/unit/cli/commands/test_lock.py       # NEW — lock semantics
tests/integration/cli/test_background.py   # NEW — end-to-end
```

---

## 3. `_lock.py` contract

```python
class LockHeld(Exception):
    """Raised when another process holds the lock."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"another instance holds {path}")
        self.path = path


@contextlib.contextmanager
def acquire_config_lock(config_path: Path) -> Iterator[Path]:
    """Acquire an exclusive lock for ``config_path``; yield the lock file path.

    Lock file lives under ``<runtime>/cmcourier/<digest>.lock``,
    where ``<runtime>`` is ``$XDG_RUNTIME_DIR`` or ``/tmp``, and
    ``<digest>`` is the first 12 hex chars of
    ``sha256(str(config_path.resolve()))``.

    On entry:
      - Creates the lock directory if absent.
      - Opens the lock file (O_CREAT | O_RDWR).
      - ``fcntl.flock(fd, LOCK_EX | LOCK_NB)``.
      - Writes ``<pid> <iso-timestamp>\n`` to the file.

    On exit:
      - Releases the flock and closes the fd.

    Raises ``LockHeld`` on contention.
    """
```

Key implementation details:
- Use `os.open` rather than Python `open()` to control the
  flags precisely and avoid buffered I/O surprises.
- `LOCK_EX | LOCK_NB`: non-blocking exclusive. Without
  `LOCK_NB`, `flock` would block forever on contention — not
  what we want for cron.
- Truncate-then-write the lock file content (`os.ftruncate(fd, 0)`)
  so stale content from a previous run doesn't bleed through.
- Don't `unlink` the lock file on release. The file is just a
  bookkeeping anchor; presence on disk is harmless.

---

## 4. `background.py` skeleton

```python
@main.command(name="background")
@click.option("--pipeline", "pipeline_kind",
              type=click.Choice(["csv-trigger", "rvabrep", "as400-trigger", "local-scan"]),
              required=True)
@click.option("--config", "-c", "config_path",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              required=True)
@click.option("--batch-id", type=str, default=None)
@click.option("--from-stage", type=click.IntRange(1, 5), default=1)
@click.option("--batch-size", type=click.IntRange(min=1), default=None)
@click.option("--skip-doctor", is_flag=True, default=False)
@click.option("--resume", is_flag=True, default=False)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False),
              default="WARNING")
def background_command(
    pipeline_kind, config_path, batch_id, from_stage, batch_size,
    skip_doctor, resume, log_level,
) -> None:
    """Run a pipeline unattended (cron-friendly)."""
    try:
        with acquire_config_lock(config_path) as lock_path:
            _log.info("background_started",
                      extra={"pipeline": pipeline_kind,
                             "lock_path": str(lock_path)})
            kind_map = {
                "csv-trigger": "csv",
                "rvabrep": "rvabrep",
                "as400-trigger": "as400",
                "local-scan": "local_scan",
            }
            _run_pipeline_command(
                config_path,
                expected_kind=kind_map[pipeline_kind],
                batch_id=batch_id,
                from_stage=from_stage,
                batch_size=batch_size,
                triggers_override=None,
                skip_doctor=skip_doctor,
                resume=resume,
                log_level=log_level,
                quiet=True,
            )
    except LockHeld as exc:
        _log.warning("background_lock_held",
                     extra={"lock_path": str(exc.path)})
        click.echo(f"Another instance is running: {exc.path}", err=True)
        sys.exit(75)
```

`_run_pipeline_command` already calls `sys.exit(...)` so the
context manager unwinds via SystemExit. fcntl lock releases
when fd closes (in the `finally` of the cm).

---

## 5. `_run_pipeline_command` modification

Add a `quiet: bool = False` kwarg. The only effect:

```python
# inside _run_pipeline_command, near the end:
if not quiet:
    _emit_summary(report)
if report.s5_failed > 0:
    if quiet:
        click.echo(
            f"pipeline={expected_kind}-trigger batch_id={report.batch_id} "
            f"s5_failed={report.s5_failed} exit_code=1",
            err=True,
        )
    sys.exit(1)
sys.exit(0)
```

Existing callers (csv/rvabrep/as400/local-scan) pass nothing →
default `quiet=False` → behavior unchanged.

Similarly, `_apply_resume`'s `"Nothing to resume"` echo needs a
guard. Either pass `quiet` through or accept the small stdout
output even in background (it's a single line). I'll guard it
via a small refactor for symmetry.

---

## 6. Test plan

### 6.1 `tests/unit/cli/commands/test_lock.py` — 6 tests

- `test_acquire_release_roundtrip` — context manager works,
  same lock can be acquired again after exit.
- `test_contention_raises_LockHeld` — open a second fd in the
  same test, attempt LOCK_EX | LOCK_NB → ensure our wrapper
  raises LockHeld.
- `test_deterministic_path` — same config_path → same lock
  digest; different config_paths → different digests.
- `test_uses_xdg_runtime_dir` — monkeypatch
  `XDG_RUNTIME_DIR=tmp_path` → lock file under that.
- `test_falls_back_to_tmp` — XDG unset → /tmp.
- `test_pid_and_timestamp_written` — read the lock file content
  after acquisition.

### 6.2 `tests/integration/cli/test_background.py` — 5 tests

- `test_help` — `cmcourier background --help` lists every
  flag.
- `test_pipeline_choice_enforced` — `--pipeline single-doc`
  exits 2.
- `test_happy_path_csv_trigger_quiet` — with stubs, exit 0,
  stdout empty.
- `test_lock_contention_exits_75` — programmatically hold the
  lock, invoke CLI, expect 75.
- `test_skip_doctor_passthrough` — verify auto-doctor not
  invoked when --skip-doctor passed.

The lock-contention test holds the lock via the public helper
(`with acquire_config_lock(yaml_path):`) and invokes the CLI
from within. Since the helper uses fcntl, the CLI subprocess
opens a new fd → blocked → LockHeld → exit 75.

Wait — `CliRunner` runs in-process, NOT as subprocess. In-process
the second `acquire_config_lock` opens the same path but gets a
different fd, so flock should block. Let me confirm with a quick
sanity test.

Actually `fcntl.flock` is file-descriptor-based but treats locks
as per-PROCESS. Two flocks on the same file from the same
process do NOT block each other (Linux man flock(2) says "open
file description"). For Python's `fcntl.flock`, the lock IS
per-fd as of glibc 2.0+, but per-PROCESS semantics historically
held. Let me check.

Actually `flock(2)` Linux uses BSD semantics: locks held on open
file descriptors. Two fds from same process → independent
locks. So holding lock in test setup + CliRunner in-process
trying again → the CLI's fcntl.flock call should fail with
EWOULDBLOCK (LOCK_NB).

I'll write the test that way. If Linux quirks bite us, fall
back to a subprocess test.

---

## 7. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..004 (command surface) | §4 | §6.2 (help, choice) |
| REQ-005..010 (lock) | §3 | §6.1 |
| REQ-011..014 (quiet) | §5 | §6.2 |
| REQ-015..017 (dispatch) | §4, §5 | §6.2 |
| REQ-018..020 (observability) | §4 | §6.2 |
| REQ-021..022 (tests) | §6 | all |
| REQ-023..025 (verification) | — | pytest/mypy |

---

## 8. Files touched

```
NEW   src/cmcourier/cli/commands/_lock.py
NEW   src/cmcourier/cli/commands/background.py
EDIT  src/cmcourier/cli/app.py               # register cmd, +quiet kwarg on _run_pipeline_command
NEW   tests/unit/cli/commands/test_lock.py
NEW   tests/integration/cli/test_background.py
EDIT  CHANGELOG.md
EDIT  README.md
NEW   specs/024-background-runner/{spec,plan,tasks}.md
```

---

## 9. Risks

- **R1**: `fcntl.flock` per-process vs per-fd semantics. On
  Linux, BSD-style — per-fd. Our test will exercise this in a
  single process. If it doesn't work, switch the test to a
  subprocess.
- **R2**: `XDG_RUNTIME_DIR` not set in CI / test environments.
  Mitigation: fall back to `/tmp` (POSIX always-writable).
  Tests can monkeypatch `XDG_RUNTIME_DIR` to `tmp_path` for
  isolation.
- **R3**: Tests that share /tmp lock files might race. Mitigation:
  each test monkeypatches `XDG_RUNTIME_DIR` to its own
  `tmp_path` so digests collide across tests but the per-test
  lock dir is isolated.
- **R4**: `_run_pipeline_command` is a long helper; adding a
  `quiet` kwarg is mechanical but touches ~3 lines. Existing
  signatures (csv/rvabrep/as400/local-scan dispatch) need
  updating to pass `quiet=False` explicitly OR rely on the
  default. Default is cleaner — no callsite changes.
- **R5**: The `_apply_resume` "Nothing to resume" exit echoes to
  stdout regardless. For background mode I'll guard that echo
  behind a `quiet` parameter passed through. Small surface
  growth on `_apply_resume`.
- **R6**: Lock contention test in-process. If fcntl.flock has
  unexpected semantics on macOS vs Linux, the test fails on
  one platform. The project targets Linux for production but
  developers run macOS. Decision: keep the in-process test; if
  it fails on macOS, fall back to a `subprocess.Popen` test
  that's slower but portable.

---

## 10. Estimated effort

- Spec / plan / tasks: 40 min (done)
- Phase 1 (`_lock.py` + 6 unit tests): 50 min
- Phase 2 (`background.py` + `_run_pipeline_command` quiet
  kwarg): 40 min
- Phase 3 (integration tests + iterate): 60 min
- Phase 4 (verification + docs + commit + merge): 30 min
- **Total**: ~3 h 20 min

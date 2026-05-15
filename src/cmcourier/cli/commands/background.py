"""``cmcourier background --pipeline <kind>`` — cron-friendly runner.

Same machinery as the interactive pipelines but with three
unattended-mode behaviors:

1. **Per-config lock** (POSIX ``fcntl.flock`` / Windows
   ``msvcrt.locking``). Two overlapping invocations on the same
   config exit immediately — the second one with status ``75``
   (cron-canonical ``EX_TEMPFAIL`` "transient failure, retry later";
   Windows Task Scheduler treats any non-zero exit as failure).
2. **Quiet success**. No stdout summary line. Cron emails only
   fire when something is wrong.
3. **WARNING-by-default log level**. Operators can ``--log-level
   INFO`` if they want chatty stderr, but cron's mailer stays
   quiet otherwise.

Auto-doctor stays ON unless ``--skip-doctor`` is passed — cron
benefits from pre-flight, not less.

This command, named ``background``, dispatches into the same
``_run_pipeline_command`` helper the four interactive run
commands use, with ``quiet=True``.
"""

from __future__ import annotations

__all__ = ["background_command"]

import logging
import sys
from pathlib import Path

import click

from cmcourier.cli.commands._lock import LockHeldError, acquire_config_lock

_log = logging.getLogger(__name__)

_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
# POSIX ``os.EX_TEMPFAIL`` literal — the constant only exists on Unix
# Python builds, so hardcode it to keep the module importable on Windows.
_EXIT_TEMPFAIL = 75
_PIPELINE_CHOICES = ("csv-trigger", "rvabrep", "as400-trigger", "local-scan")
# Maps the CLI's pipeline name onto the internal ``trigger.kind`` value.
_KIND_MAP: dict[str, str] = {
    "csv-trigger": "csv",
    "rvabrep": "rvabrep",
    "as400-trigger": "as400",
    "local-scan": "local_scan",
}


@click.command(name="background")
@click.option(
    "--pipeline",
    "pipeline_kind",
    type=click.Choice(_PIPELINE_CHOICES),
    required=True,
    help="Which production pipeline to run.",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--batch-id", type=str, default=None)
@click.option("--from-stage", type=click.IntRange(1, 5), default=1)
@click.option("--batch-size", type=click.IntRange(min=1), default=None)
@click.option("--skip-doctor", is_flag=True, default=False)
@click.option("--resume", is_flag=True, default=False)
@click.option(
    "--log-level",
    type=click.Choice(_LOG_LEVELS, case_sensitive=False),
    default="WARNING",
    help="stderr verbosity (default: WARNING — cron stays quiet on success).",
)
def background_command(
    pipeline_kind: str,
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    skip_doctor: bool,
    resume: bool,
    log_level: str,
) -> None:
    """Run a production pipeline unattended (cron / systemd-friendly)."""
    # Late import to break the cycle: cli/app.py imports this module.
    from cmcourier.cli.app import _run_pipeline_command  # noqa: PLC0415

    try:
        with acquire_config_lock(config_path) as lock_path:
            _log.info(
                "background_started",
                extra={
                    "pipeline": pipeline_kind,
                    "url_prefix": str(lock_path)[:80],
                },
            )
            _run_pipeline_command(
                config_path,
                expected_kind=_KIND_MAP[pipeline_kind],  # type: ignore[arg-type]
                batch_id=batch_id,
                from_stage=from_stage,
                batch_size=batch_size,
                triggers_override=None,
                skip_doctor=skip_doctor,
                resume=resume,
                log_level=log_level,
                quiet=True,
            )
    except LockHeldError as exc:
        _log.warning(
            "background_lock_held",
            extra={"url_prefix": str(exc.path)[:80]},
        )
        click.echo(f"Another instance is running: {exc.path}", err=True)
        sys.exit(_EXIT_TEMPFAIL)

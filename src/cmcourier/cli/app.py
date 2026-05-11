"""CMCourier CLI entry point.

Root Click group ``cmcourier`` with three pipeline sub-groups
(``csv-trigger-pipeline``, ``rvabrep-pipeline``, ``as400-trigger-pipeline``)
plus the top-level ``doctor`` pre-flight command. Each pipeline command
expects a config whose ``trigger.kind`` matches; mismatches exit 2.

Exit codes per spec REQ-020:
    0 = success (every doc reached S5_DONE)
    1 = pipeline ran but had stage failures (s5_failed > 0 OR any upstream)
    2 = configuration error (bad YAML, missing env vars, mismatched kind, etc.)
    3 = unhandled exception from inside ``pipeline.run``
"""

from __future__ import annotations

__all__ = ["main"]

import logging
import sys
from pathlib import Path
from typing import Literal

import click

from cmcourier import __version__
from cmcourier.cli.doctor import DoctorReport, run_doctor
from cmcourier.cli.logging_setup import configure as configure_logging
from cmcourier.config.loader import load_config, load_secrets
from cmcourier.config.schema import CsvTriggerConfig, PipelineConfig
from cmcourier.config.wiring import build_pipeline
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.orchestrators.staged import RunReport

_log = logging.getLogger(__name__)

_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]

_TriggerKind = Literal["csv", "rvabrep", "as400", "local_scan"]


# ---------------------------------------------------------------------------
# Root group + version
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(__version__, prog_name="cmcourier")
def main() -> None:
    """CMCourier - RVI -> IBM Content Manager migration tool."""


# ---------------------------------------------------------------------------
# csv-trigger-pipeline
# ---------------------------------------------------------------------------


@main.group(name="csv-trigger-pipeline")
def csv_trigger_pipeline_group() -> None:
    """csv-trigger-pipeline subcommands (REBIRTH §10.2)."""


@csv_trigger_pipeline_group.command(name="run")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the pipeline YAML config file.",
)
@click.option("--batch-id", type=str, default=None)
@click.option("--from-stage", type=click.IntRange(1, 5), default=1)
@click.option("--batch-size", type=click.IntRange(min=1), default=None)
@click.option(
    "--triggers",
    "triggers_override",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Override the config's trigger CSV path (csv kind only).",
)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def csv_run_command(
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    triggers_override: Path | None,
    log_level: str,
) -> None:
    """Run the csv-trigger pipeline end-to-end."""
    _run_pipeline_command(
        config_path,
        expected_kind="csv",
        batch_id=batch_id,
        from_stage=from_stage,
        batch_size=batch_size,
        triggers_override=triggers_override,
        log_level=log_level,
    )


# ---------------------------------------------------------------------------
# rvabrep-pipeline
# ---------------------------------------------------------------------------


@main.group(name="rvabrep-pipeline")
def rvabrep_pipeline_group() -> None:
    """rvabrep-pipeline subcommands (REBIRTH §10.2)."""


@rvabrep_pipeline_group.command(name="run")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--batch-id", type=str, default=None)
@click.option("--from-stage", type=click.IntRange(1, 5), default=1)
@click.option("--batch-size", type=click.IntRange(min=1), default=None)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def rvabrep_run_command(
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    log_level: str,
) -> None:
    """Run the rvabrep-pipeline end-to-end."""
    _run_pipeline_command(
        config_path,
        expected_kind="rvabrep",
        batch_id=batch_id,
        from_stage=from_stage,
        batch_size=batch_size,
        triggers_override=None,
        log_level=log_level,
    )


# ---------------------------------------------------------------------------
# as400-trigger-pipeline
# ---------------------------------------------------------------------------


@main.group(name="as400-trigger-pipeline")
def as400_trigger_pipeline_group() -> None:
    """as400-trigger-pipeline subcommands (REBIRTH §10.2)."""


@as400_trigger_pipeline_group.command(name="run")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--batch-id", type=str, default=None)
@click.option("--from-stage", type=click.IntRange(1, 5), default=1)
@click.option("--batch-size", type=click.IntRange(min=1), default=None)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def as400_run_command(
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    log_level: str,
) -> None:
    """Run the as400-trigger-pipeline end-to-end."""
    _run_pipeline_command(
        config_path,
        expected_kind="as400",
        batch_id=batch_id,
        from_stage=from_stage,
        batch_size=batch_size,
        triggers_override=None,
        log_level=log_level,
    )


# ---------------------------------------------------------------------------
# local-scan-pipeline
# ---------------------------------------------------------------------------


@main.group(name="local-scan-pipeline")
def local_scan_pipeline_group() -> None:
    """local-scan-pipeline subcommands (REBIRTH §10.2)."""


@local_scan_pipeline_group.command(name="run")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--batch-id", type=str, default=None)
@click.option("--from-stage", type=click.IntRange(1, 5), default=1)
@click.option("--batch-size", type=click.IntRange(min=1), default=None)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def local_scan_run_command(
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    log_level: str,
) -> None:
    """Run the local-scan-pipeline end-to-end."""
    _run_pipeline_command(
        config_path,
        expected_kind="local_scan",
        batch_id=batch_id,
        from_stage=from_stage,
        batch_size=batch_size,
        triggers_override=None,
        log_level=log_level,
    )


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


@main.command(name="doctor")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the pipeline YAML config file.",
)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def doctor_command(config_path: Path, log_level: str) -> None:
    """Run pre-flight validation (REBIRTH §10.5)."""
    configure_logging(log_level)
    try:
        config = load_config(config_path)
        secrets = load_secrets()
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)
    try:
        report = run_doctor(config, secrets)
    except Exception:
        _log.exception("doctor crashed unexpectedly")
        sys.exit(3)
    _emit_doctor_report(report)
    sys.exit(1 if report.has_failures else 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_pipeline_command(
    config_path: Path,
    *,
    expected_kind: _TriggerKind,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    triggers_override: Path | None,
    log_level: str,
) -> None:
    configure_logging(log_level)
    try:
        config = load_config(config_path)
        secrets = load_secrets()
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

    actual_kind = getattr(config.trigger, "kind", "<unknown>")
    if actual_kind != expected_kind:
        click.echo(
            f"ConfigurationError: this command expects trigger.kind={expected_kind!r}; "
            f"config has kind={actual_kind!r}",
            err=True,
        )
        sys.exit(2)

    config = _apply_overrides(config, triggers_override, batch_size)

    try:
        pipeline = build_pipeline(config, secrets)
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

    source_descriptor = (
        str(config.trigger.csv_path)
        if isinstance(config.trigger, CsvTriggerConfig)
        else ""  # rvabrep / as400 strategies ignore source_descriptor
    )
    try:
        report = pipeline.run(
            source_descriptor=source_descriptor,
            batch_size=config.batch_size,
            batch_id=batch_id,
            from_stage=from_stage,
        )
    except Exception:
        _log.exception("pipeline run failed unexpectedly")
        sys.exit(3)

    _emit_summary(report)
    sys.exit(0 if report.s5_failed == 0 else 1)


def _apply_overrides(
    config: PipelineConfig,
    triggers_override: Path | None,
    batch_size: int | None,
) -> PipelineConfig:
    updates: dict[str, object] = {}
    if triggers_override is not None and isinstance(config.trigger, CsvTriggerConfig):
        updates["trigger"] = CsvTriggerConfig(
            kind="csv",
            csv_path=triggers_override,
            shortname_column=config.trigger.shortname_column,
            cif_column=config.trigger.cif_column,
            system_id_column=config.trigger.system_id_column,
        )
    if batch_size is not None:
        updates["batch_size"] = batch_size
    if updates:
        return config.model_copy(update=updates)
    return config


def _emit_summary(report: RunReport) -> None:
    click.echo(
        f"batch_id={report.batch_id} "
        f"total_triggers={report.total_triggers} "
        f"total_docs={report.total_docs} "
        f"s5_done={report.s5_done} "
        f"s5_failed={report.s5_failed} "
        f"elapsed_seconds={report.elapsed_seconds:.2f}"
    )


def _emit_doctor_report(report: DoctorReport) -> None:
    for result in report.results:
        click.echo(f"[{result.status.value}] {result.name} — {result.message}")
        for key in sorted(result.details.keys()):
            click.echo(f"    {key}={result.details[key]}")
    click.echo(
        f"{report.passed_count} passed, "
        f"{report.failed_count} failed, "
        f"{report.warn_count} warnings, "
        f"{report.skip_count} skipped "
        f"in {report.elapsed_seconds:.2f}s"
    )


if __name__ == "__main__":
    main()

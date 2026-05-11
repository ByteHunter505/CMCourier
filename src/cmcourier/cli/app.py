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
from typing import Any, Literal

import click

from cmcourier import __version__
from cmcourier.cli.commands.analyze import analyze_group
from cmcourier.cli.commands.as400_query import as400_query_command
from cmcourier.cli.commands.background import background_command
from cmcourier.cli.commands.batch import batch_group
from cmcourier.cli.commands.inspect import inspect_group
from cmcourier.cli.doctor import DoctorReport, run_doctor
from cmcourier.cli.logging_setup import configure as configure_logging
from cmcourier.config.loader import load_config, load_secrets
from cmcourier.config.schema import CsvTriggerConfig, PipelineConfig
from cmcourier.config.wiring import build_pipeline
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.observability.setup import configure as configure_observability
from cmcourier.orchestrators.staged import RunReport, StagedPipeline
from cmcourier.services.triggers import SingleDocTriggerStrategy

_log = logging.getLogger(__name__)

_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]

_TriggerKind = Literal["csv", "rvabrep", "as400", "local_scan", "single_doc"]


# ---------------------------------------------------------------------------
# Root group + version
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(__version__, prog_name="cmcourier")
def main() -> None:
    """CMCourier - RVI -> IBM Content Manager migration tool."""


main.add_command(batch_group)
main.add_command(inspect_group)
main.add_command(as400_query_command)
main.add_command(background_command)
main.add_command(analyze_group)


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
@click.option(
    "--skip-doctor",
    is_flag=True,
    default=False,
    help="Bypass the automatic doctor pre-flight (dev iteration).",
)
@click.option(
    "--resume",
    is_flag=True,
    default=False,
    help="Auto-detect from-stage by reading batch state. Requires --batch-id.",
)
@click.option(
    "--tui/--no-tui",
    "tui",
    default=True,
    help="Start the live two-tab TUI. Default ON; --no-tui for headless shells.",
)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def csv_run_command(
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    triggers_override: Path | None,
    skip_doctor: bool,
    resume: bool,
    tui: bool,
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
        skip_doctor=skip_doctor,
        resume=resume,
        log_level=log_level,
        tui=tui,
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
@click.option("--skip-doctor", is_flag=True, default=False)
@click.option("--resume", is_flag=True, default=False)
@click.option("--tui/--no-tui", "tui", default=True)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def rvabrep_run_command(
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    skip_doctor: bool,
    resume: bool,
    tui: bool,
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
        skip_doctor=skip_doctor,
        resume=resume,
        log_level=log_level,
        tui=tui,
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
@click.option("--skip-doctor", is_flag=True, default=False)
@click.option("--resume", is_flag=True, default=False)
@click.option("--tui/--no-tui", "tui", default=True)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def as400_run_command(
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    skip_doctor: bool,
    resume: bool,
    tui: bool,
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
        skip_doctor=skip_doctor,
        resume=resume,
        log_level=log_level,
        tui=tui,
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
@click.option("--skip-doctor", is_flag=True, default=False)
@click.option("--resume", is_flag=True, default=False)
@click.option("--tui/--no-tui", "tui", default=True)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def local_scan_run_command(
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    skip_doctor: bool,
    resume: bool,
    tui: bool,
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
        skip_doctor=skip_doctor,
        resume=resume,
        log_level=log_level,
        tui=tui,
    )


# ---------------------------------------------------------------------------
# single-doc (REBIRTH §10.2 diagnostic pipeline)
# ---------------------------------------------------------------------------


@main.group(name="single-doc")
def single_doc_group() -> None:
    """single-doc subcommands (REBIRTH §10.2 — debug / ad-hoc)."""


@single_doc_group.command(name="run")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the pipeline YAML config file (trigger.kind must be 'single_doc').",
)
@click.option("--shortname", type=str, required=True, help="Target document shortname.")
@click.option("--system", type=str, required=True, help="Source system identifier.")
@click.option("--cif", type=str, default=None, help="Optional CIF (resolved if blank).")
@click.option("--batch-id", type=str, default=None)
@click.option("--from-stage", type=click.IntRange(1, 5), default=1)
@click.option("--batch-size", type=click.IntRange(min=1), default=None)
@click.option("--skip-doctor", is_flag=True, default=False)
@click.option("--resume", is_flag=True, default=False)
@click.option("--tui/--no-tui", "tui", default=True)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def single_doc_run_command(
    config_path: Path,
    shortname: str,
    system: str,
    cif: str | None,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    skip_doctor: bool,
    resume: bool,
    tui: bool,
    log_level: str,
) -> None:
    """Run a one-shot pipeline for a single document."""
    configure_logging(log_level)
    try:
        config = load_config(config_path)
        secrets = load_secrets()
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

    actual_kind = getattr(config.trigger, "kind", "<unknown>")
    if actual_kind != "single_doc":
        click.echo(
            f"ConfigurationError: single-doc run expects trigger.kind='single_doc'; "
            f"config has kind={actual_kind!r}",
            err=True,
        )
        sys.exit(2)

    config = _apply_overrides(config, triggers_override=None, batch_size=batch_size)
    configure_observability(config.observability, log_level)

    if not skip_doctor:
        _run_auto_doctor(config, secrets)
    if resume:
        from_stage = _apply_resume(config, batch_id, from_stage)

    strategy = SingleDocTriggerStrategy(
        shortname=shortname,
        system_id=system,
        cif=cif or None,
    )
    try:
        pipeline = build_pipeline(
            config,
            secrets,
            trigger_strategy_override=strategy,
            pipeline_name="single-doc",
        )
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

    pipeline_kwargs = {
        "source_descriptor": "",
        "batch_size": config.batch_size,
        "batch_id": batch_id,
        "from_stage": from_stage,
    }
    report = _run_with_optional_tui(
        pipeline=pipeline,
        config=config,
        pipeline_kwargs=pipeline_kwargs,
        tui=tui,
    )
    _emit_outcome(
        report=report,
        expected_kind="single-doc",
        quiet=False,
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
@click.option(
    "--check",
    "selected_check",
    type=click.Choice(["connections", "mapping", "metadata", "cm-types", "all"]),
    default="all",
    help="Run only the named REBIRTH §11 check group (default: all).",
)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def doctor_command(config_path: Path, selected_check: str, log_level: str) -> None:
    """Run pre-flight validation (REBIRTH §10.5)."""
    configure_logging(log_level)
    try:
        config = load_config(config_path)
        secrets = load_secrets()
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)
    configure_observability(config.observability, log_level)
    try:
        report = run_doctor(config, secrets, selected=selected_check)
    except Exception:
        _log.exception("doctor crashed unexpectedly")
        sys.exit(3)
    if selected_check != "all":
        click.echo(f"Selected checks: {selected_check}")
    _emit_doctor_report(report)
    _log.info(
        "doctor_invoked",
        extra={"reason": selected_check},
    )
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
    skip_doctor: bool,
    resume: bool,
    log_level: str,
    quiet: bool = False,
    tui: bool = False,
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
    configure_observability(config.observability, log_level)

    if not skip_doctor:
        _run_auto_doctor(config, secrets)
    if resume:
        from_stage = _apply_resume(config, batch_id, from_stage, quiet=quiet)

    try:
        pipeline = build_pipeline(config, secrets, pipeline_name=f"{expected_kind}-trigger")
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

    source_descriptor = (
        str(config.trigger.csv_path)
        if isinstance(config.trigger, CsvTriggerConfig)
        else ""  # rvabrep / as400 strategies ignore source_descriptor
    )
    pipeline_kwargs = {
        "source_descriptor": source_descriptor,
        "batch_size": config.batch_size,
        "batch_id": batch_id,
        "from_stage": from_stage,
    }
    report = _run_with_optional_tui(
        pipeline=pipeline,
        config=config,
        pipeline_kwargs=pipeline_kwargs,
        tui=tui,
    )
    _emit_outcome(
        report=report,
        expected_kind=expected_kind,
        quiet=quiet,
    )


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


def _run_with_optional_tui(
    *,
    pipeline: StagedPipeline,
    config: PipelineConfig,
    pipeline_kwargs: dict[str, Any],
    tui: bool,
) -> RunReport:
    """Run ``pipeline.run(**kwargs)`` with or without the live TUI.

    Returns the :class:`RunReport`. Exits 2/3 on misuse / unhandled errors,
    matching the headless path's exit codes. When ``tui`` is the default
    value (not user-supplied) and stderr is not a TTY, the TUI is
    silently auto-disabled (REQ-034) so cron/CI keep working.
    """
    from cmcourier.cli._tui_runner import (  # noqa: PLC0415
        run_pipeline_with_tui,
        tty_available,
    )
    from cmcourier.tui import TUIDataProvider  # noqa: PLC0415

    if tui and not tty_available():
        ctx = click.get_current_context(silent=True)
        explicit = False
        if ctx is not None:
            source = ctx.get_parameter_source("tui")
            explicit = source is not None and source.name != "DEFAULT"
        if explicit:
            click.echo(
                "ConfigurationError: --tui requires a TTY; use --no-tui for headless runs",
                err=True,
            )
            sys.exit(2)
        tui = False

    if not tui:
        try:
            return pipeline.run(**pipeline_kwargs)
        except Exception:
            _log.exception("pipeline run failed unexpectedly")
            sys.exit(3)

    data_provider = TUIDataProvider(
        pipeline_name=pipeline.pipeline_name,
        metrics_recorder=pipeline.metrics_recorder,
        pool_stats=pipeline.pool_stats,
        concurrency_limit=pipeline.concurrency_limit,
        cmis_config=config.cmis,
        uploader=pipeline.uploader,
        auto_tune=pipeline.auto_tune_controller,
    )
    outcome = run_pipeline_with_tui(
        pipeline=pipeline,
        data_provider=data_provider,
        pipeline_kwargs=pipeline_kwargs,
    )
    if outcome.exception is not None:
        _log.exception(
            "pipeline run failed unexpectedly",
            exc_info=outcome.exception,
        )
        sys.exit(3)
    assert outcome.report is not None
    return outcome.report


def _emit_outcome(
    *,
    report: RunReport,
    expected_kind: str,
    quiet: bool,
) -> None:
    """Emit the per-run summary line + ``sys.exit`` with the right code."""
    if not quiet:
        _emit_summary(report)
    elif report.s5_failed > 0:
        click.echo(
            f"pipeline={expected_kind}-trigger batch_id={report.batch_id} "
            f"s5_failed={report.s5_failed} exit_code=1",
            err=True,
        )
    sys.exit(0 if report.s5_failed == 0 else 1)


def _run_auto_doctor(config: PipelineConfig, secrets) -> None:  # type: ignore[no-untyped-def]
    """Run pre-flight checks; abort the caller (sys.exit) on FAIL."""
    try:
        report = run_doctor(config, secrets)
    except Exception:
        _log.exception("auto-doctor crashed unexpectedly")
        sys.exit(3)
    _emit_doctor_report(report)
    if report.has_failures:
        _log.error(
            "doctor_fail",
            extra={"failed_count": report.failed_count},
        )
        sys.exit(2)
    _log.info(
        "doctor_pass",
        extra={
            "passed_count": report.passed_count,
            "warn_count": report.warn_count,
            "skip_count": report.skip_count,
        },
    )


def _apply_resume(
    config: PipelineConfig,
    batch_id: str | None,
    explicit_from_stage: int,
    *,
    quiet: bool = False,
) -> int:
    """Resolve ``--resume`` into a concrete ``from_stage`` int.

    Calls ``sys.exit`` on misuse (no batch_id, unknown batch, clean batch).
    When ``explicit_from_stage`` is non-default, it WINS and emits a
    WARNING — explicit beats inferred. ``quiet=True`` suppresses the
    "Nothing to resume" stdout echo (still exits 0); used by the
    background runner.
    """
    from cmcourier.adapters.tracking import SQLiteTrackingStore  # noqa: PLC0415

    if batch_id is None:
        click.echo(
            "ConfigurationError: --resume requires --batch-id",
            err=True,
        )
        sys.exit(2)
    store = SQLiteTrackingStore(config.tracking.db_path)
    try:
        details = store.get_batch_details(batch_id)
    finally:
        store.close()
    if details is None:
        click.echo(f"Batch not found: {batch_id}", err=True)
        sys.exit(1)
    resolved: int | None = None
    for n in (1, 2, 3, 4, 5):
        counts = details.stage_counts.get(f"S{n}", {})
        if counts.get("FAILED", 0) + counts.get("PENDING", 0) > 0:
            resolved = n
            break
    if resolved is None:
        if not quiet:
            click.echo(f"Nothing to resume — batch {batch_id} is clean")
        sys.exit(0)
    if explicit_from_stage != 1:
        _log.warning(
            "--from-stage explicit value overrides --resume",
            extra={
                "explicit_from_stage": explicit_from_stage,
                "resume_inferred": resolved,
            },
        )
        return explicit_from_stage
    _log.info(
        "resume_resolved",
        extra={"batch_id": batch_id, "resume_inferred": resolved},
    )
    return resolved


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

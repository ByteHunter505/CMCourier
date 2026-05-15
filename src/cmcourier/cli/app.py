"""CMCourier CLI entry point.

Root Click group ``cmcourier`` with three pipeline sub-groups
(``csv-trigger-pipeline``, ``rvabrep-pipeline``, ``local-scan-pipeline``)
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
from cmcourier.cli.commands.cache import cache_group
from cmcourier.cli.commands.completion import completion_command
from cmcourier.cli.commands.inspect import inspect_group
from cmcourier.cli.commands.mock import mock_group
from cmcourier.cli.commands.sync import sync_group
from cmcourier.cli.doctor import DoctorReport, run_doctor
from cmcourier.cli.logging_setup import configure as configure_logging
from cmcourier.config.loader import load_config, load_secrets
from cmcourier.config.schema import CsvTriggerConfig, PipelineConfig
from cmcourier.config.wiring import build_pipeline
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.observability.setup import configure as configure_observability
from cmcourier.orchestrators.multi_batch import MultiBatchOrchestrator, MultiBatchRunReport
from cmcourier.orchestrators.staged import RunReport, StagedPipeline
from cmcourier.orchestrators.streaming import StreamingOrchestrator
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
main.add_command(completion_command)
main.add_command(sync_group)
main.add_command(mock_group)
main.add_command(cache_group)


# ---------------------------------------------------------------------------
# csv-trigger-pipeline
# ---------------------------------------------------------------------------


@main.group(name="csv-trigger-pipeline")
def csv_trigger_pipeline_group() -> None:
    """csv-trigger-pipeline subcommands."""


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
@click.option(
    "--batches-in-flight",
    "batches_in_flight",
    type=click.IntRange(1, 2),
    default=None,
    help="Override processing.batches_in_flight (1 or 2). Default reads YAML.",
)
@click.option(
    "--total",
    "total",
    type=click.IntRange(min=1),
    default=None,
    help="Process at most N triggers from the source (for validation runs).",
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
    batches_in_flight: int | None,
    total: int | None,
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
        batches_in_flight=batches_in_flight,
        total=total,
    )


# ---------------------------------------------------------------------------
# rvabrep-pipeline
# ---------------------------------------------------------------------------


@main.group(name="rvabrep-pipeline")
def rvabrep_pipeline_group() -> None:
    """rvabrep-pipeline subcommands."""


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
@click.option(
    "--batches-in-flight",
    "batches_in_flight",
    type=click.IntRange(1, 2),
    default=None,
)
@click.option(
    "--total",
    "total",
    type=click.IntRange(min=1),
    default=None,
    help="Process at most N triggers from the source (for validation runs).",
)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def rvabrep_run_command(
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    skip_doctor: bool,
    resume: bool,
    tui: bool,
    batches_in_flight: int | None,
    total: int | None,
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
        batches_in_flight=batches_in_flight,
        total=total,
    )


# ---------------------------------------------------------------------------
# local-scan-pipeline
# ---------------------------------------------------------------------------


@main.group(name="local-scan-pipeline")
def local_scan_pipeline_group() -> None:
    """local-scan-pipeline subcommands."""


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
@click.option(
    "--batches-in-flight",
    "batches_in_flight",
    type=click.IntRange(1, 2),
    default=None,
)
@click.option(
    "--total",
    "total",
    type=click.IntRange(min=1),
    default=None,
    help="Process at most N triggers from the source (for validation runs).",
)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def local_scan_run_command(
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    skip_doctor: bool,
    resume: bool,
    tui: bool,
    batches_in_flight: int | None,
    total: int | None,
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
        batches_in_flight=batches_in_flight,
        total=total,
    )


# ---------------------------------------------------------------------------
# single-doc (diagnostic pipeline)
# ---------------------------------------------------------------------------


@main.group(name="single-doc")
def single_doc_group() -> None:
    """single-doc subcommands (debug / ad-hoc)."""


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
@click.option(
    "--batches-in-flight",
    "batches_in_flight",
    type=click.IntRange(1, 2),
    default=None,
)
@click.option(
    "--total",
    "total",
    type=click.IntRange(min=1),
    default=None,
    help="Process at most N triggers from the source (for validation runs).",
)
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
    batches_in_flight: int | None,
    total: int | None,
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
        "batches_in_flight": batches_in_flight or config.processing.batches_in_flight,
        "resume": resume,
        "total": total,
    }
    report = _run_with_optional_tui(
        pipeline=pipeline,
        config=config,
        pipeline_kwargs=pipeline_kwargs,
        tui=tui,
        log_level=log_level,
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
    type=click.Choice(["connections", "mapping", "metadata", "cm-types", "cm-targets", "all"]),
    default="all",
    help="Run only the named check group (default: all).",
)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def doctor_command(config_path: Path, selected_check: str, log_level: str) -> None:
    """Run pre-flight validation."""
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
    batches_in_flight: int | None = None,
    total: int | None = None,
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
        "batches_in_flight": batches_in_flight or config.processing.batches_in_flight,
        "resume": resume,
        "total": total,
    }
    report = _run_with_optional_tui(
        pipeline=pipeline,
        config=config,
        pipeline_kwargs=pipeline_kwargs,
        tui=tui,
        log_level=log_level,
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
    log_level: str,
) -> MultiBatchRunReport:
    """Route the run through the multi-batch orchestrator (028 + 030).

    Exit codes (2/3) match the pre-028 headless contract. When
    ``tui=True`` and stderr is non-TTY, the TUI is auto-disabled
    (REQ-034). The TUI is live-bound to the orchestrator's active
    chunk recorder, so N=2 runs render coherent per-chunk data
    plus a CHUNKS tab listing every chunk's status.
    """
    from cmcourier.cli._tui_runner import (  # noqa: PLC0415
        run_orchestrator_with_tui,
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

    # Extract orchestrator-specific kwargs and drop them from the dict.
    batches_in_flight = int(pipeline_kwargs.pop("batches_in_flight", 1))
    resume_flag = bool(pipeline_kwargs.pop("resume", False))
    total = pipeline_kwargs.pop("total", None)
    if resume_flag:
        # Resume is inherently single-batch — the operator named a specific
        # batch_id; orchestrator chunking doesn't apply.
        batches_in_flight = 1
    # 044: any operator-provided ``--batch-id`` is the batch_id this run
    # operates on (resume OR fresh-named OR ``--from-stage`` replay). The
    # orchestrator routes through ``_run_single`` whenever batch_id is set
    # and the pipeline validates existence. Pre-044 this assignment only
    # honored batch_id when ``--resume`` was also passed, which dropped the
    # flag silently on ``--from-stage`` replay paths and produced the
    # ``ValueError("from_stage > 1 requires batch_id")`` further down.
    resume_batch_id = pipeline_kwargs.get("batch_id")
    if resume_batch_id is not None:
        # Operator-named batches go through the single-batch path so the
        # batch_id is honored verbatim (multi-batch overlap auto-generates
        # per-chunk ids and would ignore the user's name).
        batches_in_flight = 1

    # 063: streaming mode selector. Both orchestrators expose the same
    # ``.run(...)`` signature and return a MultiBatchRunReport, so the
    # rest of this function (TUI wiring, _emit_outcome) is unchanged.
    orchestrator: MultiBatchOrchestrator | StreamingOrchestrator
    if config.processing.mode == "streaming":
        if int(pipeline_kwargs.get("from_stage", 1)) > 1 or resume_batch_id is not None:
            _log.warning(
                "streaming mode rejects resume args; the orchestrator will "
                "raise ValueError. Re-run with --from-stage 1 and no --batch-id."
            )
        orchestrator = StreamingOrchestrator(
            pipeline=pipeline,
            config=config,
            log_dir=config.observability.log_dir,
        )
    else:
        orchestrator = MultiBatchOrchestrator(
            pipeline=pipeline,
            config=config,
            log_dir=config.observability.log_dir,
        )
    orchestrator_kwargs: dict[str, Any] = {
        "source_descriptor": pipeline_kwargs["source_descriptor"],
        "batch_size": int(pipeline_kwargs["batch_size"]),
        "batches_in_flight": batches_in_flight,
        "from_stage": int(pipeline_kwargs.get("from_stage", 1)),
        "resume_batch_id": resume_batch_id,
        "total": total,
    }

    if not tui:
        try:
            return orchestrator.run(**orchestrator_kwargs)
        except Exception:
            _log.exception("pipeline run failed unexpectedly")
            sys.exit(3)

    # 041: once we're committed to launching the Textual TUI, re-install
    # observability handlers WITHOUT a stderr StreamHandler so the dashboard
    # frame is not torn by log lines. configure() is idempotent — it resets
    # all handlers before re-attaching, so the rotating FileHandler keeps
    # logging every event to disk.
    configure_observability(config.observability, log_level, tui_active=True)

    # 064: streaming mode plumbs the bucket snapshot into the BUCKET tab.
    bucket_provider = (
        orchestrator.streaming_snapshot if isinstance(orchestrator, StreamingOrchestrator) else None
    )
    data_provider = TUIDataProvider(
        pipeline_name=pipeline.pipeline_name,
        metrics_recorder=pipeline.metrics_recorder,
        pool_stats=pipeline.pool_stats,
        concurrency_limit=pipeline.concurrency_limit,
        cmis_config=config.cmis,
        uploader=pipeline.uploader,
        auto_tune=pipeline.auto_tune_controller,
        # 030: live-bind the active chunk's recorder + chunk-state list.
        recorder_provider=orchestrator.active_recorder,
        # 042: independent UPLOAD-tab binding so PREP-side flips don't
        # stomp the S5 percentile / MB display mid-upload.
        upload_recorder_provider=orchestrator.upload_recorder,
        chunks_provider=orchestrator.chunks_snapshot,
        # 036: surface heavy/light lane stats when dual mode is enabled.
        lane_controller=pipeline.lane_controller,
        # 052: tracking store for the DETAIL tab's per-chunk drill-down.
        tracking_store=pipeline.tracking_store,
        # 064: orchestration mode + BUCKET-tab data source.
        mode=config.processing.mode,
        bucket_provider=bucket_provider,
    )
    outcome = run_orchestrator_with_tui(
        orchestrator=orchestrator,
        data_provider=data_provider,
        orchestrator_kwargs=orchestrator_kwargs,
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
    report: MultiBatchRunReport,
    expected_kind: str,
    quiet: bool,
) -> None:
    """Emit the per-chunk + totals summary and ``sys.exit`` with the right code.

    For the legacy single-chunk path the output is byte-identical to
    pre-028. When more than one chunk ran, prints one line per chunk
    followed by a TOTALS line.
    """
    if not quiet:
        if len(report.chunks) <= 1:
            # Legacy single-batch output preserved verbatim.
            if report.chunks:
                _emit_summary(report.chunks[0])
        else:
            for idx, chunk in enumerate(report.chunks, start=1):
                click.echo(
                    f"chunk {idx}/{len(report.chunks)}  "
                    f"batch_id={chunk.batch_id} "
                    f"total_docs={chunk.total_docs} "
                    f"s1_filtered={chunk.s1_filtered} "
                    f"s5_done={chunk.s5_done} "
                    f"s5_failed={chunk.s5_failed} "
                    f"elapsed_seconds={chunk.elapsed_seconds:.2f}"
                )
            click.echo(
                f"TOTALS batch_count={len(report.chunks)} "
                f"total_docs={report.total_docs} "
                f"s1_filtered={report.s1_filtered} "
                f"s5_done={report.s5_done} "
                f"s5_failed={report.s5_failed} "
                f"failed_chunks={len(report.failed_chunks)} "
                f"elapsed_seconds={report.elapsed_seconds:.2f}"
            )
    elif report.s5_failed > 0 or report.failed_chunks:
        click.echo(
            f"pipeline={expected_kind}-trigger "
            f"batch_count={len(report.chunks)} "
            f"s5_failed={report.s5_failed} "
            f"failed_chunks={len(report.failed_chunks)} exit_code=1",
            err=True,
        )
    exit_code = 1 if (report.s5_failed > 0 or report.failed_chunks) else 0
    sys.exit(exit_code)


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

    # 044: explicit ``--from-stage`` wins regardless of detection. The
    # operator named a specific replay point and provided a batch_id —
    # honor it even if auto-detection would say "clean". Moved BEFORE
    # the clean-exit so a user can force a replay of an outwardly-
    # complete batch (typical after a config change that wants S3+ rerun).
    if explicit_from_stage != 1:
        _log.info(
            "resume_explicit_from_stage",
            extra={
                "batch_id": batch_id,
                "explicit_from_stage": explicit_from_stage,
            },
        )
        return explicit_from_stage

    resolved: int | None = None
    for n in (1, 2, 3, 4, 5):
        counts = details.stage_counts.get(f"S{n}", {})
        # FAILED / PENDING at this stage takes priority — same-stage
        # retry path is more conservative than skipping ahead.
        if counts.get("FAILED", 0) + counts.get("PENDING", 0) > 0:
            resolved = n
            break
        # 044: docs at ``S{N}_DONE`` with N<5 are completed at stage N
        # but never picked up for stage N+1. With a worker pool sized
        # smaller than the batch, most kill-mid-S5 scenarios leave the
        # bulk of docs at S4_DONE — pre-044 this looked "clean" to
        # ``_apply_resume`` because neither FAILED nor PENDING marker
        # was set. Detect the gap and resume from N+1.
        if n < 5 and counts.get("DONE", 0) > 0:
            resolved = n + 1
            break
    if resolved is None:
        if not quiet:
            click.echo(f"Nothing to resume — batch {batch_id} is clean")
        sys.exit(0)
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
        f"s1_filtered={report.s1_filtered} "
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

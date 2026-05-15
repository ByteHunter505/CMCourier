"""Suite del subcomando `cmcourier analyze` (027, POST-MVP, seccion 3).

Tres subcomandos:

* ``analyze batch <batch_id>``: reporte completo de un batch.
* ``analyze compare <a> <b>``: delta de a pares.
* ``analyze trends [--last N] [--pipeline <name>]``: serie temporal.

Cada subcomando acepta ``--config <path>`` (para derivar `log_dir` +
techo de CMIS + cantidad de workers desde el YAML) o
``--log-dir <path>`` (para leer crudo sin pasar por la config). El
flag ``--format`` togglea entre salida legible para humanos en
terminal (default) y JSON.
"""

from __future__ import annotations

__all__ = ["analyze_group"]

import logging
import sys
from pathlib import Path

import click

from cmcourier.config.loader import load_config
from cmcourier.config.schema import PipelineConfig
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.services.analyze import (
    LogReader,
    build_batch_report,
    compare_batches,
    compute_trends,
    format_compare_json,
    format_compare_terminal,
    format_json,
    format_terminal,
    format_trends_json,
    format_trends_terminal,
)

_log = logging.getLogger(__name__)


@click.group(name="analyze")
def analyze_group() -> None:
    """Tooling de analisis offline de logs (tier 5 + tiers 1-4 de observabilidad)."""


# ---------------------------------------------------------------------------
# Resolutor compartido de opciones
# ---------------------------------------------------------------------------


def _resolve_context(
    config_path: Path | None,
    log_dir_override: Path | None,
) -> tuple[Path, int, int]:
    """Devuelve ``(log_dir, cmis_max_bandwidth_mbps, pool_capacity)``."""
    if log_dir_override is not None:
        return log_dir_override, 0, 0
    if config_path is None:
        click.echo(
            "ConfigurationError: --config or --log-dir is required",
            err=True,
        )
        sys.exit(2)
    try:
        cfg: PipelineConfig = load_config(config_path)
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)
    return (
        cfg.observability.log_dir,
        int(cfg.cmis.max_bandwidth_mbps or 0),
        int(cfg.cmis.workers or 0),
    )


# ---------------------------------------------------------------------------
# analyze batch
# ---------------------------------------------------------------------------


@analyze_group.command(name="batch")
@click.argument("batch_id", type=str)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Pipeline YAML — used to derive log_dir + cmis ceiling.",
)
@click.option(
    "--log-dir",
    "log_dir_override",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Override log_dir directly (skip the YAML).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
)
def batch_command(
    batch_id: str,
    config_path: Path | None,
    log_dir_override: Path | None,
    output_format: str,
) -> None:
    """Produce un reporte completo de un batch terminado."""
    log_dir, max_bw, pool_capacity = _resolve_context(config_path, log_dir_override)
    reader = LogReader(log_dir=log_dir)
    try:
        records = reader.read_batch(batch_id)
        report = build_batch_report(
            batch_id=batch_id,
            records=records,
            cmis_max_bandwidth_mbps=max_bw,
            pool_capacity=pool_capacity,
        )
    except Exception:
        _log.exception("analyze batch failed unexpectedly")
        sys.exit(3)
    rendered = format_json(report) if output_format == "json" else format_terminal(report)
    click.echo(rendered, nl=output_format == "json")


# ---------------------------------------------------------------------------
# analyze compare
# ---------------------------------------------------------------------------


@analyze_group.command(name="compare")
@click.argument("batch_a", type=str)
@click.argument("batch_b", type=str)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
@click.option(
    "--log-dir",
    "log_dir_override",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
)
def compare_command(
    batch_a: str,
    batch_b: str,
    config_path: Path | None,
    log_dir_override: Path | None,
    output_format: str,
) -> None:
    """Hace el diff de dos batches lado a lado."""
    log_dir, max_bw, pool_capacity = _resolve_context(config_path, log_dir_override)
    reader = LogReader(log_dir=log_dir)
    try:
        report_a = build_batch_report(
            batch_id=batch_a,
            records=reader.read_batch(batch_a),
            cmis_max_bandwidth_mbps=max_bw,
            pool_capacity=pool_capacity,
        )
        report_b = build_batch_report(
            batch_id=batch_b,
            records=reader.read_batch(batch_b),
            cmis_max_bandwidth_mbps=max_bw,
            pool_capacity=pool_capacity,
        )
        cmp = compare_batches(report_a, report_b)
    except Exception:
        _log.exception("analyze compare failed unexpectedly")
        sys.exit(3)
    rendered = format_compare_json(cmp) if output_format == "json" else format_compare_terminal(cmp)
    click.echo(rendered, nl=output_format == "json")


# ---------------------------------------------------------------------------
# analyze trends
# ---------------------------------------------------------------------------


@analyze_group.command(name="trends")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
@click.option(
    "--log-dir",
    "log_dir_override",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
)
@click.option(
    "--last",
    "last_n",
    type=click.IntRange(min=1),
    default=10,
    help="Show the last N batches (default 10).",
)
@click.option(
    "--pipeline",
    "pipeline_filter",
    type=str,
    default=None,
    help="Restrict to batches whose pipeline matches.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
)
def trends_command(
    config_path: Path | None,
    log_dir_override: Path | None,
    last_n: int,
    pipeline_filter: str | None,
    output_format: str,
) -> None:
    """Tendencia de throughput + p95 sobre los ultimos N batches."""
    log_dir, _max_bw, _pool = _resolve_context(config_path, log_dir_override)
    try:
        rows = compute_trends(
            log_dir=log_dir,
            last_n=last_n,
            pipeline_filter=pipeline_filter,
        )
    except Exception:
        _log.exception("analyze trends failed unexpectedly")
        sys.exit(3)
    rendered = format_trends_json(rows) if output_format == "json" else format_trends_terminal(rows)
    click.echo(rendered, nl=output_format == "json")

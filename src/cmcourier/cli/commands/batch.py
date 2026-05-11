"""``cmcourier batch ...`` subcommands (REBIRTH §11).

* ``batch list`` — enumerate batches with status + counts.
* ``batch show <id>`` — per-stage counts + failed records.
* ``batch retry-failed --batch <id> [--stage Sn]`` — reset failures.

All commands open the tracking store via the wiring layer (so the
SQLite-specific concerns stay behind ``ITrackingStore``).
"""

from __future__ import annotations

__all__ = ["batch_group"]

import logging
import sys
from pathlib import Path

import click

from cmcourier.adapters.tracking import SQLiteTrackingStore
from cmcourier.cli.commands._formatting import render_table, truncate
from cmcourier.config.loader import load_config
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.models import StageStatus
from cmcourier.observability.setup import configure as configure_observability

_log = logging.getLogger(__name__)

_STAGES_FOR_RETRY = ("S1", "S2", "S3", "S4", "S5")
_STAGES_FOR_TABLE = ("S0", "S1", "S2", "S3", "S4", "S5")


@click.group(name="batch")
def batch_group() -> None:
    """Batch lifecycle commands (REBIRTH §11)."""


# ---------------------------------------------------------------------------
# batch list
# ---------------------------------------------------------------------------


@batch_group.command(name="list")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the pipeline YAML config file.",
)
@click.option(
    "--status",
    type=click.Choice(["in_progress", "completed"]),
    default=None,
    help="Filter by batch lifecycle state.",
)
def batch_list_command(config_path: Path, status: str | None) -> None:
    """Enumerate batches with status + counts (newest first)."""
    config = _load(config_path)
    configure_observability(config.observability, "INFO")
    store = SQLiteTrackingStore(config.tracking.db_path)
    try:
        batches = store.list_batches(status=status)  # type: ignore[arg-type]
    finally:
        store.close()
    if not batches:
        click.echo("No batches recorded.")
        return
    rows = [
        [
            b.batch_id,
            b.status,
            b.started_at.isoformat(timespec="seconds"),
            b.completed_at.isoformat(timespec="seconds") if b.completed_at else "-",
            str(b.total_records),
        ]
        for b in batches
    ]
    click.echo(render_table(["BATCH_ID", "STATUS", "STARTED", "COMPLETED", "TOTAL"], rows))


# ---------------------------------------------------------------------------
# batch show
# ---------------------------------------------------------------------------


@batch_group.command(name="show")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.argument("batch_id", type=str)
def batch_show_command(config_path: Path, batch_id: str) -> None:
    """Detailed per-stage state + failed records for one batch."""
    config = _load(config_path)
    configure_observability(config.observability, "INFO")
    store = SQLiteTrackingStore(config.tracking.db_path)
    try:
        details = store.get_batch_details(batch_id)
    finally:
        store.close()
    if details is None:
        click.echo(f"Batch not found: {batch_id}", err=True)
        sys.exit(1)
    info = details.info
    click.echo(f"Batch: {info.batch_id}")
    click.echo(f"Status: {info.status}")
    click.echo(f"Started: {info.started_at.isoformat(timespec='seconds')}")
    completed_str = (
        info.completed_at.isoformat(timespec="seconds") if info.completed_at is not None else "-"
    )
    click.echo(f"Completed: {completed_str}")
    click.echo(f"Total records: {info.total_records}")
    click.echo("")
    stage_rows = [
        [
            stage,
            str(details.stage_counts[stage]["DONE"]),
            str(details.stage_counts[stage]["FAILED"]),
            str(details.stage_counts[stage]["PENDING"]),
        ]
        for stage in _STAGES_FOR_TABLE
    ]
    click.echo(render_table(["STAGE", "DONE", "FAILED", "PENDING"], stage_rows))
    if details.failed_records:
        click.echo("")
        click.echo("FAILED records:")
        failure_rows = [
            [f.txn_num, f.status, truncate(f.error_message, 80)] for f in details.failed_records
        ]
        click.echo(render_table(["TXN_NUM", "STAGE", "ERROR"], failure_rows))


# ---------------------------------------------------------------------------
# batch retry-failed
# ---------------------------------------------------------------------------


@batch_group.command(name="retry-failed")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--batch",
    "batch_id",
    type=str,
    required=True,
    help="Batch ID to scan for failed records.",
)
@click.option(
    "--stage",
    type=click.Choice(_STAGES_FOR_RETRY),
    default=None,
    help="If given, only reset failures in this stage.",
)
def batch_retry_failed_command(config_path: Path, batch_id: str, stage: str | None) -> None:
    """Reset ``*_FAILED`` rows to ``*_PENDING`` for retry."""
    config = _load(config_path)
    configure_observability(config.observability, "INFO")
    stage_status = StageStatus(f"{stage}_FAILED") if stage is not None else None
    store = SQLiteTrackingStore(config.tracking.db_path)
    try:
        reset = store.retry_failed(batch_id, stage=stage_status)
    finally:
        store.close()
    click.echo(f"Reset {reset} FAILED rows to PENDING (batch={batch_id}, stage={stage or 'all'})")


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _load(config_path: Path):  # type: ignore[no-untyped-def]
    try:
        return load_config(config_path)
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

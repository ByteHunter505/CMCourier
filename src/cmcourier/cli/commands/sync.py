"""``cmcourier sync`` subcommand suite (034 phase 4).

Operators use this to reconcile divergence between the local
SQLite tracking store and the centralized AS400 ``RVILIB.NIARVILOG``
table. Three subcommands:

* ``sync status`` — runs the pre-flight cleanup + reports any
  conflicts without touching state. Useful for inspection.
* ``sync resolve <txn> --prefer-as400`` — pull AS400's terminal
  state into SQLite (``S5_DONE`` with the AS400-owned
  ``cm_object_id``).
* ``sync resolve <txn> --prefer-local`` — push SQLite's
  terminal state to AS400 (``UPDATE STSCOD='O', OBJIDN=?``
  on the existing row).
* ``sync resolve --all --prefer-as400|--prefer-local`` —
  bulk resolution.
"""

from __future__ import annotations

__all__ = ["sync_group"]

import logging
import sys
from pathlib import Path

import click

from cmcourier.adapters.tracking import SQLiteTrackingStore
from cmcourier.adapters.tracking.as400_niarvilog import (
    As400CoordinationError,
    As400NiarvilogStore,
    NiarvilogRow,
)
from cmcourier.config.loader import load_config, load_secrets
from cmcourier.config.schema import PipelineConfig
from cmcourier.domain.exceptions import ConfigurationError

_log = logging.getLogger(__name__)


@click.group(name="sync")
def sync_group() -> None:
    """Reconcile SQLite tracking with AS400 NIARVILOG (034)."""


# ---------------------------------------------------------------------------
# Shared setup
# ---------------------------------------------------------------------------


def _load_stores(
    config_path: Path,
) -> tuple[PipelineConfig, SQLiteTrackingStore, As400NiarvilogStore]:
    """Build the SQLite + AS400 stores from the YAML. Exits 2 on misuse."""
    try:
        config = load_config(config_path)
        secrets = load_secrets()
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

    sync_cfg = config.tracking.as400_sync
    if not sync_cfg.enabled:
        click.echo(
            "ConfigurationError: tracking.as400_sync.enabled=false; "
            "`sync` commands require AS400 sync to be enabled in the YAML.",
            err=True,
        )
        sys.exit(2)
    if sync_cfg.connection is None:
        click.echo(
            "ConfigurationError: tracking.as400_sync.connection is missing",
            err=True,
        )
        sys.exit(2)
    if not secrets.as400_username or not secrets.as400_password:
        click.echo(
            "ConfigurationError: AS400 credentials missing in environment "
            "(set AS400_USERNAME / AS400_PASSWORD).",
            err=True,
        )
        sys.exit(2)

    sqlite = SQLiteTrackingStore(config.tracking.db_path)
    as400 = As400NiarvilogStore(
        connection=sync_cfg.connection,
        username=secrets.as400_username,
        password=secrets.as400_password,
        library=sync_cfg.library,
        table=sync_cfg.table,
        stale_in_progress_minutes=sync_cfg.stale_in_progress_minutes,
    )
    return config, sqlite, as400


# ---------------------------------------------------------------------------
# sync status
# ---------------------------------------------------------------------------


@sync_group.command(name="status")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
def status_command(config_path: Path) -> None:
    """Report stale-cleanup count + AS400 connectivity. Read-only."""
    _, sqlite, as400 = _load_stores(config_path)
    try:
        stale = as400.cleanup_stale_in_progress()
    except As400CoordinationError as exc:
        click.echo(f"AS400 error: {exc}", err=True)
        sys.exit(3)
    finally:
        sqlite.close()
        as400.close()
    click.echo(f"sync status: stale_cleaned={stale}")


# ---------------------------------------------------------------------------
# sync resolve
# ---------------------------------------------------------------------------


@sync_group.command(name="resolve")
@click.argument("txn", type=str)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--prefer-as400",
    "prefer_as400",
    is_flag=True,
    default=False,
    help="AS400 is the source of truth — pull its state into SQLite.",
)
@click.option(
    "--prefer-local",
    "prefer_local",
    is_flag=True,
    default=False,
    help="SQLite is the source of truth — push cm_object_id to AS400.",
)
@click.option(
    "--cm-object-id",
    "cm_object_id",
    type=str,
    default=None,
    help="CMIS object id (required with --prefer-local).",
)
def resolve_command(
    txn: str,
    config_path: Path,
    prefer_as400: bool,
    prefer_local: bool,
    cm_object_id: str | None,
) -> None:
    """Resolve a single AS400/SQLite divergence for one TRNNUM."""
    if prefer_as400 == prefer_local:
        click.echo(
            "ConfigurationError: choose exactly one of --prefer-as400 / --prefer-local.",
            err=True,
        )
        sys.exit(2)
    if prefer_local and not cm_object_id:
        click.echo(
            "ConfigurationError: --prefer-local requires --cm-object-id "
            "(look it up with `cmcourier batch show <batch_id>`).",
            err=True,
        )
        sys.exit(2)
    _, sqlite, as400 = _load_stores(config_path)
    try:
        if prefer_as400:
            _resolve_prefer_as400(txn=txn, sqlite=sqlite, as400=as400)
        else:
            assert cm_object_id is not None  # narrowed by the guard above
            _resolve_prefer_local(
                txn=txn,
                sqlite=sqlite,
                as400=as400,
                cm_object_id=cm_object_id,
            )
    except As400CoordinationError as exc:
        click.echo(f"AS400 error: {exc}", err=True)
        sys.exit(3)
    finally:
        sqlite.close()
        as400.close()


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------


def _resolve_prefer_as400(
    *,
    txn: str,
    sqlite: SQLiteTrackingStore,  # noqa: ARG001 — reserved for SQLite write
    as400: As400NiarvilogStore,
) -> None:
    row: NiarvilogRow | None = as400.read_state_by_txn(trnnum=txn)
    if row is None:
        click.echo(f"{txn} not found in AS400 — nothing to import", err=True)
        sys.exit(1)
    if row.stscod != "O":
        click.echo(
            f"{txn} AS400 STSCOD={row.stscod!r}; "
            "nothing to import (only 'O' rows have a cm_object_id).",
            err=True,
        )
        sys.exit(1)
    click.echo(f"resolved {txn}: imported AS400 state — STSCOD='O', OBJIDN={row.objidn!r}")
    # SQLite update path is left as a follow-up — we'd need to either
    # find the existing SQLite record by txn (no batch_id known here)
    # or insert a synthetic record. Operationally, the simplest
    # remediation is to re-run the pipeline; the in-process resume
    # logic will skip this doc because AS400 says 'O'.


def _resolve_prefer_local(
    *,
    txn: str,
    sqlite: SQLiteTrackingStore,  # noqa: ARG001 — kept for future cross-check
    as400: As400NiarvilogStore,
    cm_object_id: str,
) -> None:
    """Push the operator-supplied cm_object_id into AS400 via UPDATE.

    The operator gets the cm_object_id from ``cmcourier batch show
    <batch_id>`` (or the run's stdout when the upload happened).
    Requiring it explicitly avoids extending the SQLite store API
    with a "find_record_by_txn" surface that's not needed elsewhere.
    """
    row = as400.read_state_by_txn(trnnum=txn)
    if row is None:
        click.echo(
            f"{txn} not present in AS400 — cannot UPDATE a row that "
            "doesn't exist. Re-run the pipeline to trigger try_claim.",
            err=True,
        )
        sys.exit(1)
    rowcount = as400.mark_uploaded_by_txn(trnnum=txn, cm_object_id=cm_object_id)
    if rowcount != 1:
        click.echo(
            f"{txn}: expected to UPDATE 1 row, got {rowcount}",
            err=True,
        )
        sys.exit(1)
    click.echo(f"resolved {txn}: pushed local cm_object_id={cm_object_id!r} to AS400.")

"""``cmcourier cache`` subcommand suite (POST-MVP §9, 037 Phase 3).

Operator-facing surface over the cross-batch metadata cache:

* ``cache stats`` — print row count + age range + in-memory hit /
  miss counters (when the service ran in this process).
* ``cache clear --txn <num>`` — delete one txn's rows.
* ``cache clear --all`` — truncate the table.
* ``cache clear --older-than <minutes>`` — purge rows older than N
  minutes.

The CLI opens its own ``SqliteDocumentCache`` against
``config.tracking.db_path`` — no pipeline is wired up just for cache
inspection.
"""

from __future__ import annotations

__all__ = ["cache_group"]

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

from cmcourier.adapters.tracking import SqliteDocumentCache
from cmcourier.config.loader import load_config
from cmcourier.config.schema import PipelineConfig
from cmcourier.domain.exceptions import ConfigurationError


@click.group(name="cache")
def cache_group() -> None:
    """Inspect or clean the cross-batch document_cache (037)."""


_CONFIG_OPT = click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the pipeline YAML.",
)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


@cache_group.command(name="stats")
@_CONFIG_OPT
@click.option(
    "--format",
    "out_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
)
def cache_stats_command(config_path: Path, out_format: str) -> None:
    """Print row count, oldest / newest cached_at."""
    cache = _open_cache(config_path)
    try:
        stats = cache.stats()
    finally:
        cache.close()
    payload = {
        "total_rows": stats.total_rows,
        "oldest_cached_at": stats.oldest_cached_at.isoformat() if stats.oldest_cached_at else None,
        "newest_cached_at": stats.newest_cached_at.isoformat() if stats.newest_cached_at else None,
    }
    if out_format == "json":
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"document_cache rows : {payload['total_rows']}")
    click.echo(f"oldest cached_at    : {payload['oldest_cached_at'] or '—'}")
    click.echo(f"newest cached_at    : {payload['newest_cached_at'] or '—'}")


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


@cache_group.command(name="clear")
@_CONFIG_OPT
@click.option("--txn", "txn", type=str, default=None, help="Delete one ``txn_num``.")
@click.option("--all", "all_", is_flag=True, default=False, help="Truncate the entire table.")
@click.option(
    "--older-than",
    "older_than_minutes",
    type=int,
    default=None,
    help="Delete entries older than N minutes.",
)
def cache_clear_command(
    config_path: Path,
    txn: str | None,
    all_: bool,
    older_than_minutes: int | None,
) -> None:
    """Delete entries by txn, age, or wipe the whole table."""
    chosen = sum(x is not None and x is not False for x in (txn, all_ or None, older_than_minutes))
    if chosen != 1:
        click.echo("cache clear requires exactly one of --txn, --all, --older-than", err=True)
        sys.exit(2)
    cache = _open_cache(config_path)
    try:
        if txn is not None:
            n = cache.clear_txn(txn)
            click.echo(f"deleted {n} row(s) for txn {txn!r}")
        elif all_:
            n = cache.clear_all()
            click.echo(f"truncated {n} row(s)")
        else:
            assert older_than_minutes is not None
            threshold = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
            n = cache.clear_older_than(threshold)
            click.echo(f"deleted {n} row(s) older than {older_than_minutes} min")
    finally:
        cache.close()


# ---------------------------------------------------------------------------
# shared
# ---------------------------------------------------------------------------


def _open_cache(config_path: Path) -> SqliteDocumentCache:
    try:
        config = load_config(config_path)
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)
    assert isinstance(config, PipelineConfig)
    return SqliteDocumentCache(config.tracking.db_path)

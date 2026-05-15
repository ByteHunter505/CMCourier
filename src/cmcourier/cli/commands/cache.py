"""Suite del subcomando ``cmcourier cache`` (POST-MVP seccion 9, 037 Fase 3).

Superficie hacia el operador sobre el cache de metadata cross-batch:

* ``cache stats``: imprime cantidad de filas + rango de edad +
  contadores de hit / miss en memoria (cuando el servicio corrio en
  este proceso).
* ``cache clear --txn <num>``: borra las filas de un txn.
* ``cache clear --all``: truncea la tabla.
* ``cache clear --older-than <minutes>``: purga filas mas viejas que
  N minutos.

El CLI abre su propio ``SqliteDocumentCache`` contra
``config.tracking.db_path``: no se cablea un pipeline solo para
inspeccionar el cache.
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
    """Inspecciona o limpia el `document_cache` cross-batch (037)."""


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
    """Imprime cantidad de filas y los `cached_at` mas viejo / mas nuevo."""
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
    """Borra entradas por txn, por edad, o limpia la tabla entera."""
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
# compartido
# ---------------------------------------------------------------------------


def _open_cache(config_path: Path) -> SqliteDocumentCache:
    try:
        config = load_config(config_path)
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)
    assert isinstance(config, PipelineConfig)
    return SqliteDocumentCache(config.tracking.db_path)

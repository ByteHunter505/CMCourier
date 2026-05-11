"""``cmcourier as400-query "<SQL>"`` — raw AS400 debug query.

Debug-only. Runs the supplied SQL against the AS400 connection
configured in YAML (preferring ``trigger.as400_connection``,
falling back to the first ``metadata.sources[*]`` of kind ``as400``).
Refuses to run without AS400 credentials in the environment.

PII discipline: result rows are echoed verbatim to stdout, with
per-cell truncation at 80 characters. The operator is responsible
for what they query.
"""

from __future__ import annotations

__all__ = ["as400_query_command"]

import logging
import sys
from pathlib import Path

import click

from cmcourier.adapters.sources import As400DataSource
from cmcourier.cli.commands._formatting import render_table, truncate
from cmcourier.config.loader import load_config, load_secrets
from cmcourier.config.schema import (
    As400ConnectionConfig,
    As400MetadataSourceConfig,
    As400TriggerConfig,
    PipelineConfig,
)
from cmcourier.domain.exceptions import ConfigurationError, IndexingError
from cmcourier.observability.setup import configure as configure_observability

_log = logging.getLogger(__name__)


@click.command(name="as400-query")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.argument("sql", type=str)
def as400_query_command(config_path: Path, sql: str) -> None:
    """Run a raw SQL query against AS400 (debug only)."""
    try:
        config = load_config(config_path)
        secrets = load_secrets()
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

    configure_observability(config.observability, "INFO")

    connection = _select_as400_connection(config)
    if connection is None:
        click.echo(
            "ConfigurationError: no AS400 connection configured (need trigger.as400_connection "
            "or a metadata.sources[*] of kind=as400)",
            err=True,
        )
        sys.exit(2)
    if not secrets.as400_username or not secrets.as400_password:
        click.echo(
            "ConfigurationError: AS400_USERNAME and AS400_PASSWORD must be set in the environment",
            err=True,
        )
        sys.exit(2)

    _log.warning(
        "as400-query: raw SQL execution requested; result cells may contain PII",
        extra={"sql_prefix": sql[:80]},
    )

    source = As400DataSource(
        host=connection.host,
        port=connection.port,
        database=connection.database,
        driver=connection.driver,
        username=secrets.as400_username,
        password=secrets.as400_password,
    )
    try:
        try:
            rows = source.query(sql, [])
        except IndexingError as exc:
            click.echo(f"AS400 error: {exc}", err=True)
            sys.exit(1)
    finally:
        source.close()

    if not rows:
        click.echo("(0 rows)")
        return
    headers = list(rows[0].keys())
    body = [[truncate(str(row.get(h, "")), 80) for h in headers] for row in rows]
    click.echo(render_table(headers, body))
    click.echo(f"({len(rows)} rows)")


def _select_as400_connection(
    config: PipelineConfig,
) -> As400ConnectionConfig | None:
    if isinstance(config.trigger, As400TriggerConfig):
        return config.trigger.as400_connection
    for source in config.metadata.sources:
        if isinstance(source, As400MetadataSourceConfig):
            return source.as400_connection
    return None

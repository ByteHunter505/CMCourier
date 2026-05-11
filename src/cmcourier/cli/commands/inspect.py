"""``cmcourier inspect ...`` subcommands (REBIRTH §11).

* ``inspect rvabrep <shortname> <system_id>`` — preview the
  RVABREPDocuments stage S1 would produce for one trigger.
* ``inspect mapping <id_rvi>`` — preview the CM mapping for one
  ID RVI.

Both commands build only the minimal services they need (no
uploader, no assembler, no metadata layer) so they exit fast and
avoid touching CMIS / the file server.
"""

from __future__ import annotations

__all__ = ["inspect_group"]

import sys
from pathlib import Path

import click

from cmcourier.adapters.sources import TabularDataSource
from cmcourier.cli.commands._formatting import render_table, truncate
from cmcourier.config.loader import load_config
from cmcourier.config.wiring import (
    _indexing_columns_from_schema,
    _mapping_columns_from_schema,
)
from cmcourier.domain.exceptions import (
    ConfigurationError,
    IDRViNotMappedError,
    RVABREPDeletedError,
    RVABREPNotFoundError,
)
from cmcourier.domain.models import TriggerRecord
from cmcourier.observability.setup import configure as configure_observability
from cmcourier.services.indexing import IndexingService
from cmcourier.services.mapping import MappingService


@click.group(name="inspect")
def inspect_group() -> None:
    """Read-only previews of pipeline state (REBIRTH §11)."""


@inspect_group.command(name="rvabrep")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.argument("shortname", type=str)
@click.argument("system_id", type=str)
def inspect_rvabrep_command(config_path: Path, shortname: str, system_id: str) -> None:
    """Print RVABREP rows that S1 would produce for the trigger."""
    config = _load(config_path)
    configure_observability(config.observability, "INFO")
    rvabrep_src = TabularDataSource(config.indexing.csv_path)
    try:
        indexing = IndexingService(
            rvabrep_src,
            _indexing_columns_from_schema(config.indexing.columns),
            batch_size=config.indexing.batch_size,
        )
        trigger = TriggerRecord(shortname=shortname, cif=None, system_id=system_id)
        try:
            docs = indexing.find_documents(trigger)
        except (RVABREPNotFoundError, RVABREPDeletedError):
            docs = []
    finally:
        rvabrep_src.close()
    if not docs:
        click.echo("No RVABREP records found", err=True)
        return
    rows = [
        [
            doc.txn_num,
            truncate(doc.file_name, 30),
            doc.index7,
            str(doc.total_pages),
            doc.creation_date.isoformat() if doc.creation_date else "-",
        ]
        for doc in docs
    ]
    click.echo(render_table(["TXN_NUM", "FILE_NAME", "ID_RVI", "PAGES", "CREATED"], rows))


@inspect_group.command(name="mapping")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.argument("id_rvi", type=str)
def inspect_mapping_command(config_path: Path, id_rvi: str) -> None:
    """Print the CM mapping (folder, type, fields) for one ID RVI."""
    config = _load(config_path)
    configure_observability(config.observability, "INFO")
    mapping_src = TabularDataSource(config.mapping.csv_path)
    try:
        mapping_service = MappingService(mapping_src, _mapping_columns_from_schema(config.mapping))
        try:
            mapping = mapping_service.get_mapping(id_rvi)
        except IDRViNotMappedError:
            click.echo(f"No mapping found for ID RVI: {id_rvi}", err=True)
            return
    finally:
        mapping_src.close()
    click.echo(f"ID RVI: {mapping.id_rvi}")
    click.echo(f"Document class: {mapping.clase_name}")
    click.echo(f"CM folder: {mapping.cm_folder}")
    click.echo(f"CM object type: {mapping.cm_object_type}")
    fields = ", ".join(mapping.required_metadata_fields) or "(none)"
    click.echo(f"Required metadata fields: {fields}")


def _load(config_path: Path):  # type: ignore[no-untyped-def]
    try:
        return load_config(config_path)
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

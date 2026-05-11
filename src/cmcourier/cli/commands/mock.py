"""``cmcourier mock generate`` — synthetic RVABREP file-tree generator (031).

Operator-facing front end for :mod:`cmcourier.services.mock`. Reads RVABREP
rows from CSV (:class:`cmcourier.adapters.sources.TabularDataSource`) or
AS400 (:class:`cmcourier.adapters.sources.As400DataSource`), translates
them into :class:`cmcourier.services.mock.types.FilePlan` objects via the
pure planner, and writes valid PDF/TIFF/JPEG bytes via
:class:`cmcourier.services.mock.content.MockContentWriter`.

Exit codes (match the rest of the CLI, REQ-032):
    0 = success
    2 = configuration error (bad size suffix, inverted band, no source, ...)
    3 = unhandled exception
"""

from __future__ import annotations

__all__ = ["mock_group"]

import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import click

from cmcourier.adapters.sources import As400DataSource, TabularDataSource
from cmcourier.config.loader import load_config, load_secrets
from cmcourier.config.schema import (
    As400ConnectionConfig,
    As400TriggerConfig,
    IndexingColumnsModel,
    PipelineConfig,
)
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.ports import IDataSource
from cmcourier.services.mock.content import MockContentWriter
from cmcourier.services.mock.planner import (
    PlannerFilters,
    SizeBounds,
    plan_files,
)
from cmcourier.services.mock.sizing import parse_size
from cmcourier.services.mock.types import FilePlan

_log = logging.getLogger(__name__)


@click.group(name="mock")
def mock_group() -> None:
    """Synthetic file-tree generator for dry runs and integration tests (031)."""


@mock_group.command(name="generate")
@click.option(
    "--rvabrep-csv",
    "rvabrep_csv",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to a CSV file with RVABREP rows.",
)
@click.option(
    "--rvabrep-as400",
    "rvabrep_as400",
    is_flag=True,
    default=False,
    help="Read RVABREP rows from AS400 (requires --config with as400_connection).",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to a pipeline YAML config (required for --rvabrep-as400; "
    "optional for CSV to honor column overrides).",
)
@click.option(
    "--root",
    "root",
    type=click.Path(path_type=Path),
    required=True,
    help="Root directory under which the mock tree is materialized.",
)
@click.option("--pdf-min", "pdf_min", required=True, help="PDF min size, e.g. 10kb.")
@click.option("--pdf-max", "pdf_max", required=True, help="PDF max size, e.g. 2mb.")
@click.option("--img-min", "img_min", required=True, help="Image min size, e.g. 5kb.")
@click.option("--img-max", "img_max", required=True, help="Image max size, e.g. 500kb.")
@click.option("--limit", type=int, default=None, help="Cap on planned files.")
@click.option(
    "--system",
    "systems",
    multiple=True,
    help="Filter on ABAACD (system_code); repeatable.",
)
@click.option(
    "--document-type",
    "document_types",
    multiple=True,
    help="Filter on ABAHCD (id_rvi); repeatable.",
)
@click.option("--seed", type=int, default=None, help="Seed for deterministic randomness.")
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    default=False,
    help="Print the plan; write nothing.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing files (default skips when all targets exist).",
)
@click.option(
    "--include-deleted",
    "include_deleted",
    is_flag=True,
    default=False,
    help="Include RVABREP rows with non-empty delete_code (ABACST).",
)
def generate_command(  # noqa: PLR0913 — Click options dictate the signature
    rvabrep_csv: Path | None,
    rvabrep_as400: bool,
    config_path: Path | None,
    root: Path,
    pdf_min: str,
    pdf_max: str,
    img_min: str,
    img_max: str,
    limit: int | None,
    systems: tuple[str, ...],
    document_types: tuple[str, ...],
    seed: int | None,
    dry_run: bool,
    force: bool,
    include_deleted: bool,
) -> None:
    """Materialize a valid mock file tree from an RVABREP source."""
    try:
        bounds = _parse_bounds(pdf_min, pdf_max, img_min, img_max)
        config = _load_config_optional(config_path)
        columns = config.indexing.columns if config is not None else IndexingColumnsModel()
        source = _build_source(rvabrep_csv, rvabrep_as400, config)
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)
    except ValueError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)
    except FileNotFoundError as exc:
        click.echo(f"FileNotFoundError: {exc}", err=True)
        sys.exit(2)

    filters = PlannerFilters(
        systems=tuple(systems),
        document_types=tuple(document_types),
        limit=limit,
    )

    try:
        plans = plan_files(
            source.get_all(),
            columns,
            filters,
            bounds,
            include_deleted=include_deleted,
        )
        if dry_run:
            _emit_plan(plans, root)
            return
        created, skipped, total_bytes = _materialize(plans, root, seed=seed, force=force)
        click.echo(f"wrote {created} files ({skipped} skipped, {total_bytes} total)")
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)
    except Exception:  # noqa: BLE001 — top-level CLI handler
        _log.exception("mock generate failed")
        sys.exit(3)
    finally:
        source.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_bounds(
    pdf_min_text: str, pdf_max_text: str, img_min_text: str, img_max_text: str
) -> SizeBounds:
    pdf_min = parse_size(pdf_min_text)
    pdf_max = parse_size(pdf_max_text)
    img_min = parse_size(img_min_text)
    img_max = parse_size(img_max_text)
    if pdf_min > pdf_max:
        raise ConfigurationError(
            "--pdf-min must be <= --pdf-max",
            pdf_min=pdf_min,
            pdf_max=pdf_max,
        )
    if img_min > img_max:
        raise ConfigurationError(
            "--img-min must be <= --img-max",
            img_min=img_min,
            img_max=img_max,
        )
    return SizeBounds(pdf_min=pdf_min, pdf_max=pdf_max, img_min=img_min, img_max=img_max)


def _load_config_optional(config_path: Path | None) -> PipelineConfig | None:
    if config_path is None:
        return None
    return load_config(config_path)


def _build_source(
    rvabrep_csv: Path | None,
    rvabrep_as400: bool,
    config: PipelineConfig | None,
) -> IDataSource:
    if rvabrep_csv is None and not rvabrep_as400:
        raise ConfigurationError(
            "exactly one of --rvabrep-csv or --rvabrep-as400 is required",
        )
    if rvabrep_csv is not None and rvabrep_as400:
        raise ConfigurationError(
            "--rvabrep-csv and --rvabrep-as400 are mutually exclusive",
        )
    if rvabrep_csv is not None:
        return TabularDataSource(rvabrep_csv)
    # --rvabrep-as400 path
    if config is None:
        raise ConfigurationError(
            "--rvabrep-as400 requires --config with an AS400 connection",
        )
    conn = _extract_as400_connection(config)
    secrets = load_secrets()
    if not secrets.as400_username or not secrets.as400_password:
        raise ConfigurationError(
            "AS400 source requires AS400_USERNAME and AS400_PASSWORD env vars",
            missing_vars=[
                name
                for name, value in (
                    ("AS400_USERNAME", secrets.as400_username),
                    ("AS400_PASSWORD", secrets.as400_password),
                )
                if not value
            ],
        )
    return As400DataSource(
        host=conn.host,
        port=conn.port,
        database=conn.database,
        driver=conn.driver,
        username=secrets.as400_username,
        password=secrets.as400_password,
        table=conn.table or "RVABREP",
    )


def _extract_as400_connection(config: PipelineConfig) -> As400ConnectionConfig:
    trigger = config.trigger
    if isinstance(trigger, As400TriggerConfig):
        return trigger.as400_connection
    raise ConfigurationError(
        "config does not define an AS400 connection for the indexing source",
        trigger_kind=getattr(trigger, "kind", "<unknown>"),
    )


def _emit_plan(plans: Iterator[FilePlan], root: Path) -> None:
    for plan in plans:
        for ext in plan.extensions:
            rel = plan.dir_path / f"{plan.file_code}{ext}"
            click.echo(
                f"[plan] {root / rel}  kind={plan.kind}  pages={plan.pages}  "
                f"size={plan.size_min}..{plan.size_max}"
            )


def _materialize(
    plans: Iterator[FilePlan],
    root: Path,
    *,
    seed: int | None,
    force: bool,
) -> tuple[int, int, int]:
    writer = MockContentWriter(seed=seed)
    created = 0
    skipped = 0
    total_bytes = 0
    for plan in plans:
        target_dir = root / plan.dir_path
        written = writer.write(plan, target_dir, force=force)
        if not written:
            skipped += len(plan.extensions)
            continue
        created += len(written)
        total_bytes += sum(p.stat().st_size for p in written)
    return created, skipped, total_bytes

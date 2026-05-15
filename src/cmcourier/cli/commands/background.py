"""``cmcourier background --pipeline <kind>``: runner amigable con cron.

Misma maquinaria que los pipelines interactivos pero con tres
comportamientos de modo desatendido:

1. **Lock por config** (POSIX ``fcntl.flock`` / Windows
   ``msvcrt.locking``). Dos invocaciones superpuestas sobre la misma
   config salen al toque: la segunda con status ``75`` (el
   ``EX_TEMPFAIL`` canonico de cron, "falla transitoria, reintenta
   despues"; el `Task Scheduler` de Windows trata cualquier exit
   distinto de cero como falla).
2. **Exito silencioso**. Sin linea de resumen en stdout. Los mails
   de cron solo se disparan cuando algo anda mal.
3. **Log level por defecto WARNING**. Los operadores pueden poner
   ``--log-level INFO`` si quieren stderr verborragico, pero por
   default el mailer de cron se queda calladito.

El auto-doctor queda ON salvo que se pase ``--skip-doctor``: cron
se beneficia del pre-flight, no al reves.

Este comando, llamado ``background``, dispatcha hacia el mismo
helper ``_run_pipeline_command`` que usan los cuatro comandos
interactivos de `run`, con ``quiet=True``.
"""

from __future__ import annotations

__all__ = ["background_command"]

import logging
import sys
from pathlib import Path

import click

from cmcourier.cli.commands._lock import LockHeldError, acquire_config_lock

_log = logging.getLogger(__name__)

_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
# Literal POSIX ``os.EX_TEMPFAIL``: la constante solo existe en builds
# Python de Unix, asi que la hardcodeamos para mantener el modulo
# importable en Windows.
_EXIT_TEMPFAIL = 75
_PIPELINE_CHOICES = ("csv-trigger", "rvabrep", "as400-trigger", "local-scan")
# Mapea el nombre de pipeline del CLI al valor interno de ``trigger.kind``.
_KIND_MAP: dict[str, str] = {
    "csv-trigger": "csv",
    "rvabrep": "rvabrep",
    "as400-trigger": "as400",
    "local-scan": "local_scan",
}


@click.command(name="background")
@click.option(
    "--pipeline",
    "pipeline_kind",
    type=click.Choice(_PIPELINE_CHOICES),
    required=True,
    help="Which production pipeline to run.",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--batch-id", type=str, default=None)
@click.option("--from-stage", type=click.IntRange(1, 5), default=1)
@click.option("--batch-size", type=click.IntRange(min=1), default=None)
@click.option("--skip-doctor", is_flag=True, default=False)
@click.option("--resume", is_flag=True, default=False)
@click.option(
    "--log-level",
    type=click.Choice(_LOG_LEVELS, case_sensitive=False),
    default="WARNING",
    help="stderr verbosity (default: WARNING — cron stays quiet on success).",
)
def background_command(
    pipeline_kind: str,
    config_path: Path,
    batch_id: str | None,
    from_stage: int,
    batch_size: int | None,
    skip_doctor: bool,
    resume: bool,
    log_level: str,
) -> None:
    """Corre un pipeline productivo desatendido (amigable con cron / systemd)."""
    # Import tardio para romper el ciclo: `cli/app.py` importa este modulo.
    from cmcourier.cli.app import _run_pipeline_command  # noqa: PLC0415

    try:
        with acquire_config_lock(config_path) as lock_path:
            _log.info(
                "background_started",
                extra={
                    "pipeline": pipeline_kind,
                    "url_prefix": str(lock_path)[:80],
                },
            )
            _run_pipeline_command(
                config_path,
                expected_kind=_KIND_MAP[pipeline_kind],  # type: ignore[arg-type]
                batch_id=batch_id,
                from_stage=from_stage,
                batch_size=batch_size,
                triggers_override=None,
                skip_doctor=skip_doctor,
                resume=resume,
                log_level=log_level,
                quiet=True,
            )
    except LockHeldError as exc:
        _log.warning(
            "background_lock_held",
            extra={"url_prefix": str(exc.path)[:80]},
        )
        click.echo(f"Another instance is running: {exc.path}", err=True)
        sys.exit(_EXIT_TEMPFAIL)

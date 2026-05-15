"""Subcomando ``cmcourier completion <shell>`` (032).

Envuelve el modulo built-in de Click :mod:`click.shell_completion` para
que los operadores no tengan que acordarse del baile con la env-var
``_CMCOURIER_COMPLETE``.

Instalar el completion en el rc del shell (una sola vez):

* bash, agregar al ``~/.bashrc``:
  ``eval "$(cmcourier completion bash)"``
* zsh, agregar al ``~/.zshrc``:
  ``eval "$(cmcourier completion zsh)"``
* fish, escribir en un path de completion:
  ``cmcourier completion fish > ~/.config/fish/completions/cmcourier.fish``

Despues de reiniciar el shell, el tab-completion queda disponible para
cada subcomando, grupo y opcion declarada en el app Click, sin
mantenimiento manual.
"""

from __future__ import annotations

__all__ = ["completion_command"]

import sys

import click
from click.shell_completion import get_completion_class

_PROG_NAME = "cmcourier"
_COMPLETE_VAR = "_CMCOURIER_COMPLETE"


@click.command(name="completion")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion_command(shell: str) -> None:
    """Emite por stdout el script de shell-completion para SHELL."""
    # Import tardio para evitar el loop circular `cli/app.py` <-> `commands/*`.
    from cmcourier.cli.app import main  # noqa: PLC0415

    comp_cls = get_completion_class(shell)
    if comp_cls is None:  # pragma: no cover — ya lo protege el `Choice` de Click
        click.echo(f"Unsupported shell: {shell}", err=True)
        sys.exit(2)

    comp = comp_cls(main, {}, _PROG_NAME, _COMPLETE_VAR)
    click.echo(comp.source())

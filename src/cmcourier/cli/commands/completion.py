"""``cmcourier completion <shell>`` subcommand (032).

Wraps Click's built-in :mod:`click.shell_completion` so operators
don't have to remember the ``_CMCOURIER_COMPLETE`` env-var dance.

Install the completion in your shell rc (one-time):

* bash — append to ``~/.bashrc``:
  ``eval "$(cmcourier completion bash)"``
* zsh — append to ``~/.zshrc``:
  ``eval "$(cmcourier completion zsh)"``
* fish — write to a completion path:
  ``cmcourier completion fish > ~/.config/fish/completions/cmcourier.fish``

After restarting the shell, tab-completion is available for every
subcommand, group, and option declared on the Click app — no
manual maintenance needed.
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
    """Emit the shell-completion script for SHELL on stdout."""
    # Late import to avoid the circular cli/app.py ↔ commands/* loop.
    from cmcourier.cli.app import main  # noqa: PLC0415

    comp_cls = get_completion_class(shell)
    if comp_cls is None:  # pragma: no cover — guarded by Click's Choice
        click.echo(f"Unsupported shell: {shell}", err=True)
        sys.exit(2)

    comp = comp_cls(main, {}, _PROG_NAME, _COMPLETE_VAR)
    click.echo(comp.source())

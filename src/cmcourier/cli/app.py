"""CMCourier CLI entry point - Click group root.

Subcommands (``rvabrep-pipeline``, ``doctor``, ``inspect``, ``batch``, etc.) are
attached in subsequent changes. This module reserves the binary name and the
top-level group structure from day one.
"""

import click

from cmcourier import __version__


@click.group()
@click.version_option(__version__, prog_name="cmcourier")
def main() -> None:
    """CMCourier - RVI -> IBM Content Manager migration tool."""


if __name__ == "__main__":
    main()

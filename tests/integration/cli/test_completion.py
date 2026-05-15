"""Tests de integración para el subcomando ``cmcourier completion <shell>`` (032)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from cmcourier.cli.app import main

pytestmark = [pytest.mark.integration]


class TestCompletionCommand:
    def test_bash_emits_completion_script(self) -> None:
        result = CliRunner().invoke(main, ["completion", "bash"])
        assert result.exit_code == 0, result.stderr
        out = result.stdout
        # El script de completion de bash de Click siempre setea
        # _CMCOURIER_COMPLETE y registra vía ``complete``.
        assert "_CMCOURIER_COMPLETE" in out
        assert "complete " in out

    def test_zsh_emits_completion_script(self) -> None:
        result = CliRunner().invoke(main, ["completion", "zsh"])
        assert result.exit_code == 0, result.stderr
        out = result.stdout
        assert "_CMCOURIER_COMPLETE" in out
        # El script de zsh usa compdef.
        assert "compdef" in out

    def test_fish_emits_completion_script(self) -> None:
        result = CliRunner().invoke(main, ["completion", "fish"])
        assert result.exit_code == 0, result.stderr
        out = result.stdout
        assert "_CMCOURIER_COMPLETE" in out
        # El script de fish usa ``complete -c cmcourier``.
        assert "complete" in out

    def test_unknown_shell_rejected_by_choice(self) -> None:
        result = CliRunner().invoke(main, ["completion", "powershell"])
        # El Choice de Click rechaza con su propio exit code 2.
        assert result.exit_code == 2
        # Confirma que los shells soportados aparecen en el error.
        for shell in ("bash", "zsh", "fish"):
            assert shell in result.stderr or shell in result.stdout

    def test_help_lists_subcommand(self) -> None:
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "completion" in result.stdout

    def test_completion_help_lists_shells(self) -> None:
        result = CliRunner().invoke(main, ["completion", "--help"])
        assert result.exit_code == 0
        # Las opciones de shell aparecen documentadas en --help.
        for shell in ("bash", "zsh", "fish"):
            assert shell in result.stdout

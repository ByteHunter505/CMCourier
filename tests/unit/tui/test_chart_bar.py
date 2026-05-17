"""Tests del gráfico de barras vertical multi-línea (078)."""

from __future__ import annotations

import pytest

from cmcourier.tui.chart import render_bar_chart

pytestmark = pytest.mark.unit


def _strip_markup(line: str) -> str:
    """Quita los wrappers ``[color]`` / ``[/color]`` para inspeccionar el contenido."""
    if line.startswith("[") and "]" in line:
        line = line[line.index("]") + 1 :]
    end_marker = "[/"
    if end_marker in line:
        line = line[: line.index(end_marker)]
    return line


class TestEmptyAndZeroData:
    def test_empty_values_returns_height_blank_lines(self) -> None:
        out = render_bar_chart([], y_max=10.0, height=8, width_chars=60)
        lines = out.split("\n")
        assert len(lines) == 8
        for line in lines:
            assert line.strip() == ""

    def test_all_zero_with_ceiling_returns_blank(self) -> None:
        out = render_bar_chart([0.0] * 5, y_max=10.0, height=8, width_chars=60)
        lines = out.split("\n")
        assert len(lines) == 8
        for line in lines:
            content = _strip_markup(line)
            assert all(c == " " for c in content)

    def test_ceiling_zero_and_all_zero_returns_blank(self) -> None:
        out = render_bar_chart([0.0] * 5, y_max=0.0, height=4, width_chars=20)
        lines = out.split("\n")
        assert len(lines) == 4


class TestProportionalRendering:
    def test_full_value_fills_all_rows(self) -> None:
        out = render_bar_chart([10.0], y_max=10.0, height=4, width_chars=4)
        lines = [_strip_markup(line) for line in out.split("\n")]
        for line in lines:
            assert line[0] == "█"

    def test_half_value_fills_lower_half(self) -> None:
        out = render_bar_chart([5.0], y_max=10.0, height=8, width_chars=4)
        lines = [_strip_markup(line) for line in out.split("\n")]
        for i in range(4):
            assert lines[i][0] == " "
        for i in range(4, 8):
            assert lines[i][0] == "█"

    def test_quarter_value_fills_lower_quarter(self) -> None:
        out = render_bar_chart([2.5], y_max=10.0, height=8, width_chars=4)
        lines = [_strip_markup(line) for line in out.split("\n")]
        for i in range(6):
            assert lines[i][0] == " "
        assert lines[6][0] == "█"
        assert lines[7][0] == "█"


class TestBarSpacing:
    def test_bars_are_separated_by_space(self) -> None:
        out = render_bar_chart([10.0, 10.0, 10.0], y_max=10.0, height=2, width_chars=20)
        lines = [_strip_markup(line) for line in out.split("\n")]
        bottom = lines[-1]
        assert bottom[0] == "█"
        assert bottom[1] == " "
        assert bottom[2] == "█"
        assert bottom[3] == " "
        assert bottom[4] == "█"


class TestSubSampling:
    def test_values_exceeding_max_bars_get_grouped(self) -> None:
        values = [0.0, 100.0] * 30
        out = render_bar_chart(values, y_max=100.0, height=8, width_chars=20)
        lines = [_strip_markup(line) for line in out.split("\n")]
        bottom = lines[-1]
        bar_chars = sum(1 for c in bottom if c in "▁▂▃▄▅▆▇█")
        assert bar_chars == 10

    def test_values_at_max_bars_not_subsampled(self) -> None:
        out = render_bar_chart([10.0] * 10, y_max=10.0, height=2, width_chars=20)
        lines = [_strip_markup(line) for line in out.split("\n")]
        bottom = lines[-1]
        bar_chars = sum(1 for c in bottom if c == "█")
        assert bar_chars == 10


class TestColorMarkup:
    def test_each_line_wrapped_in_color_markup(self) -> None:
        out = render_bar_chart([5.0, 10.0], y_max=10.0, height=4, width_chars=8, color="green")
        for line in out.split("\n"):
            assert line.startswith("[green]")
            assert line.endswith("[/green]")

    def test_custom_color_propagates(self) -> None:
        out = render_bar_chart([5.0], y_max=10.0, height=2, width_chars=4, color="cyan")
        for line in out.split("\n"):
            assert line.startswith("[cyan]")
            assert line.endswith("[/cyan]")


class TestMinVisible:
    def test_nonzero_small_value_shows_minimum_block(self) -> None:
        out = render_bar_chart([0.01], y_max=100.0, height=8, width_chars=4)
        lines = [_strip_markup(line) for line in out.split("\n")]
        assert lines[-1][0] in "▁▂▃▄▅▆▇█"

    def test_zero_value_stays_empty(self) -> None:
        out = render_bar_chart([0.0], y_max=100.0, height=8, width_chars=4)
        lines = [_strip_markup(line) for line in out.split("\n")]
        for line in lines:
            assert "█" not in line and "▁" not in line


class TestLineAlignment:
    def test_all_lines_have_same_width(self) -> None:
        out = render_bar_chart([10.0, 5.0, 1.0], y_max=10.0, height=8, width_chars=60)
        for line in out.split("\n"):
            content = _strip_markup(line)
            assert len(content) == 60

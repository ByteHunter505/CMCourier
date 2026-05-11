"""Unit tests for the sparkline chart (025 phase 3)."""

from __future__ import annotations

import pytest

from cmcourier.tui.chart import render_sparkline

pytestmark = pytest.mark.unit


class TestRenderSparkline:
    def test_empty_values(self) -> None:
        assert render_sparkline([], y_max=10.0) == ""

    def test_all_zero_with_ceiling(self) -> None:
        out = render_sparkline([0.0] * 5, y_max=10.0)
        assert out == " " * 5

    def test_ceiling_zero_falls_back_to_auto_scale(self) -> None:
        # Without a ceiling, the peak value maps to the top block.
        out = render_sparkline([1.0, 2.0, 5.0], y_max=0.0)
        assert "█" in out
        assert len(out) == 3

    def test_proportional_mapping(self) -> None:
        out = render_sparkline([0.0, 5.0, 10.0], y_max=10.0)
        # 0 → space, 10 → full block.
        assert out[0] == " "
        assert out[-1] == "█"
        assert out[1] in "▁▂▃▄▅"  # midrange somewhere

    def test_values_above_ceiling_cap_at_full(self) -> None:
        out = render_sparkline([15.0, 20.0], y_max=10.0)
        assert out == "██"

    def test_negative_values_clamp_to_zero(self) -> None:
        out = render_sparkline([-3.0, 0.0, 5.0], y_max=10.0)
        assert out[0] == " "

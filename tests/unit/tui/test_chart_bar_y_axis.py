"""Tests del eje Y con etiquetas en ``render_bar_chart`` (079)."""

from __future__ import annotations

import pytest

from cmcourier.tui.chart import render_bar_chart

pytestmark = pytest.mark.unit


def _strip_markup(line: str) -> str:
    if "[" in line and "]" in line:
        # Saca todos los wrappers de markup (prefix antes del primer
        # ``[`` se preserva — son los labels del eje Y).
        out = ""
        i = 0
        while i < len(line):
            if line[i] == "[":
                end = line.find("]", i)
                if end == -1:
                    out += line[i:]
                    break
                i = end + 1
            else:
                out += line[i]
                i += 1
        return out
    return line


class TestYAxisLabelsAtCorrectRows:
    """079: con height=8 y default tick distribution, los labels caen
    en rows 0, 2, 4, 6 (top, 75%, 50%, 25%). Rows 1, 3, 5, 7 quedan
    con padding."""

    def test_height_8_cap_100_has_4_labels(self) -> None:
        out = render_bar_chart([50.0], y_max=100.0, height=8, width_chars=20)
        lines = out.split("\n")
        # Cada line empieza con "<label> │ <chart>".
        # Row 0 (top): label = 100
        assert " 100 │" in lines[0]
        # Row 1: padding
        assert lines[1].startswith("     │")
        # Row 2: 75
        assert "  75 │" in lines[2]
        # Row 4: 50
        assert "  50 │" in lines[4]
        # Row 6: 25
        assert "  25 │" in lines[6]

    def test_cap_125_labels_compute_proportionally(self) -> None:
        # Cap = 125 → labels 125 (top), 93.75 → 94, 62.5 → 62, 31.25 → 31.
        out = render_bar_chart([50.0], y_max=125.0, height=8, width_chars=20)
        lines = out.split("\n")
        assert " 125 │" in lines[0]
        assert "  94 │" in lines[2]
        assert "  62 │" in lines[4]
        assert "  31 │" in lines[6]


class TestYAxisLabelFormatting:
    """079: el label se formatea según magnitud — int para grandes,
    1 decimal para pequeños."""

    def test_small_cap_uses_one_decimal(self) -> None:
        out = render_bar_chart([1.0], y_max=4.0, height=8, width_chars=10)
        lines = out.split("\n")
        # Top label = 4.0, 75% = 3.0, 50% = 2.0, 25% = 1.0
        assert " 4.0 │" in lines[0]
        assert " 3.0 │" in lines[2]
        assert " 2.0 │" in lines[4]
        assert " 1.0 │" in lines[6]

    def test_large_cap_uses_int(self) -> None:
        out = render_bar_chart([500.0], y_max=1000.0, height=8, width_chars=10)
        lines = out.split("\n")
        assert "1000 │" in lines[0]
        assert " 750 │" in lines[2]
        assert " 500 │" in lines[4]
        assert " 250 │" in lines[6]


class TestYAxisToggleable:
    """079: ``show_y_axis=False`` quita el prefix; útil para tests
    del core del chart o para callers que ya tienen su propio eje."""

    def test_disabled_returns_chart_without_label_prefix(self) -> None:
        out = render_bar_chart([50.0], y_max=100.0, height=4, width_chars=10, show_y_axis=False)
        for line in out.split("\n"):
            # Sin prefix: cada line arranca con el markup [color]
            assert line.startswith("[")

    def test_enabled_each_line_has_7_char_prefix(self) -> None:
        # 4 label + " │ " = 7 chars.
        out = render_bar_chart([50.0], y_max=100.0, height=4, width_chars=10)
        for line in out.split("\n"):
            # El primer "[" aparece después del prefix (7 chars).
            bracket = line.index("[")
            assert bracket == 7


class TestBarsArePackedAdjacent:
    """079: las barras ahora están pegadas sin espacio entre ellas
    (cambio de comportamiento vs 078). Verificamos directamente."""

    def test_three_full_bars_are_contiguous(self) -> None:
        out = render_bar_chart(
            [10.0, 10.0, 10.0],
            y_max=10.0,
            height=2,
            width_chars=10,
            show_y_axis=False,
        )
        lines = out.split("\n")
        # Saca el markup, queda el chart raw.
        bottom = _strip_markup(lines[-1])
        # Las primeras 3 columnas deben ser todas '█' adyacentes.
        assert bottom.startswith("███")
        # No hay espacio entre barras.
        assert " " not in bottom[:3]

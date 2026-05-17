# 078 — Plan

## `render_bar_chart`

Algoritmo:

1. Si `values` vacío → devolver `height` líneas vacías de
   `width_chars` espacios.
2. `cap = y_max if y_max > 0 else max(values)` (auto-scale).
3. Sub-sampling: si `len(values) > max_bars`, agrupar en chunks
   y promediar. `max_bars = width_chars // 2` (cada barra ocupa
   2 chars).
4. Para cada barra, calcular `level = round(ratio * height * 8)`
   donde `ratio = clamp(v / cap, 0, 1)`.
5. Para cada `row` de 0 a `height-1` (top to bottom):
   - Para cada barra, calcular cuánto de su `level` cae en esta
     fila usando `rows_from_bottom = height - 1 - row`.
   - `in_row = clamp(level - rows_from_bottom * 8, 0, 8)`.
   - Pickear `_BLOCKS[in_row]`.
   - Min visibility: si `ratio > 0` y `row == height - 1` (línea
     inferior) y `in_row == 0`, usar `▁` (asegurar barra visible).
   - Append bloque + " " (espacio).
6. Trim trailing whitespace de cada línea.
7. Envolver cada línea en `[color]...[/color]` rich markup.
8. Join con `"\n"`.

Firma:

```python
def render_bar_chart(
    values: list[float],
    *,
    y_max: float,
    height: int = 8,
    width_chars: int = 60,
    color: str = "green",
) -> str:
```

## Cambio en `upload_tab.py`

Localizar:

```python
series_values = [v for _, v in snap.bandwidth_series]
if not series_values:
    lines.append("  " + " " * 60)
else:
    lines.append("  " + render_sparkline(series_values, y_max=snap.bandwidth_ceiling_mbps))
    lines.append("  " + " " * 0 + "└" + "─" * 58 + "┘  -60s ............. now")
```

Reemplazar por:

```python
series_values = [v for _, v in snap.bandwidth_series]
if not series_values:
    lines.extend(["  " + " " * 60] * 8)
else:
    chart = render_bar_chart(
        series_values,
        y_max=snap.bandwidth_ceiling_mbps,
        height=8,
        width_chars=60,
        color="green",
    )
    for line in chart.split("\n"):
        lines.append("  " + line)
lines.append("  └" + "─" * 58 + "┘  -60s ............. now")
```

Y agregar el import:

```python
from cmcourier.tui.chart import render_bar_chart
```

(El import existente de `render_sparkline` se mantiene si otro lado
del código lo usa; si no, se saca.)

## Tests

`tests/unit/tui/test_chart_bar.py` nuevo:

1. `test_empty_values_returns_height_blank_lines`
2. `test_all_zero_with_ceiling`
3. `test_full_value_fills_all_rows`
4. `test_half_value_fills_lower_half`
5. `test_sub_sampling_when_values_exceed_max_bars`
6. `test_color_markup_wraps_each_line`
7. `test_min_visible_for_nonzero_small_ratio`

## Phased commits

1. `feat: add 078 spec, plan, tasks`
2. `feat(tui): add render_bar_chart with sub-level vertical resolution (078)`
3. `feat(tui): wire bar chart into UPLOAD speed widget (078)`
4. `test: cover render_bar_chart (078)`
5. `docs(078): CHANGELOG 0.80.0 + version bump`

## Verificación

```bash
pytest -m unit
cmcourier --version    # 0.80.0
```

Smoke productivo: correr cualquier pipeline con TUI activa, tab
UPLOAD muestra el chart 8 líneas de altura, barras separadas,
color verde.

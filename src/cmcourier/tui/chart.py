"""`Sparkline` ASCII compacto para el gráfico de `bandwidth` del tab UPLOAD (025).

Sin dependencias externas — sólo caracteres de bloque mapeados a un
rango 0..1. El eje y se capa en ``y_max`` (provisto por el operador
vía ``cmis.max_bandwidth_mbps``) o auto-escala al pico cuando es 0.
"""

from __future__ import annotations

__all__ = ["render_bar_chart", "render_sparkline"]

# 8 niveles de resolución vertical por columna (más el espacio).
_BLOCKS: tuple[str, ...] = (" ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")


def render_sparkline(values: list[float], *, y_max: float) -> str:
    """Devuelve un `sparkline` Unicode de una fila.

    Data vacía o toda en cero renderiza como espacios del largo
    correcto para que los callers puedan seguir alineando el texto
    de alrededor.
    """
    if not values:
        return ""
    cap = y_max if y_max > 0 else max(values, default=0.0)
    if cap <= 0:
        return " " * len(values)
    cells: list[str] = []
    for v in values:
        ratio = max(0.0, min(1.0, v / cap))
        idx = int(round(ratio * (len(_BLOCKS) - 1)))
        cells.append(_BLOCKS[idx])
    return "".join(cells)


# 079: ancho del label del eje Y (4 chars right-aligned + " │ " separator).
_Y_AXIS_LABEL_WIDTH = 4
_Y_AXIS_PREFIX = " │ "


def _format_y_label(value: float) -> str:
    """4-char right-aligned numeric label para el eje Y."""
    if value >= 100:
        return f"{int(round(value)):>4}"
    if value >= 10:
        return f"{value:>4.0f}"
    return f"{value:>4.1f}"


def _y_axis_label_for_row(row: int, height: int, cap: float) -> str:
    """Devuelve la etiqueta de eje Y para la row dada (top=0, bottom=height-1).

    Pone etiquetas en 4 ticks distribuidos sobre el alto del chart:
    top (100%), 75%, 50%, 25%. Otras rows reciben spaces para mantener
    el alineamiento.
    """
    step = max(1, height // 4)
    if row % step != 0:
        return " " * _Y_AXIS_LABEL_WIDTH
    rows_from_bottom = height - 1 - row
    fraction = (rows_from_bottom + 1) / height
    return _format_y_label(cap * fraction)


def render_bar_chart(
    values: list[float],
    *,
    y_max: float,
    height: int = 8,
    width_chars: int = 60,
    color: str = "green",
    show_y_axis: bool = True,
) -> str:
    """078/079: gráfico de barras vertical multi-línea con rich markup.

    Cada barra ocupa 1 columna (barras pegadas — convención chart).
    Resolución vertical: ``height`` filas × 8 sub-niveles por celda
    = ``height * 8`` niveles totales.

    Si ``show_y_axis=True`` (default), cada row se prefijia con una
    etiqueta numérica derecha-alineada de 4 chars + `` │ ``, con
    ticks en 100%/75%/50%/25% del cap. La línea de eje inferior
    (rendered por el caller debajo del chart) debería alinearse
    con el ``│`` para que el layout quede limpio.

    Sub-sampling: si ``len(values) > width_chars``, agrupa
    promediando para encajar.

    Devuelve un string multi-línea ya envuelto en ``[color]...[/color]``
    rich markup. Textual ``Static`` lo renderiza con el color.

    Casos edge:
    * ``values`` vacío → devuelve ``height`` líneas en blanco con
      el prefix de eje (si aplica) — preserva alineamiento del caller.
    * ``y_max == 0`` + todos en cero → mismo blank fill.
    * ``y_max == 0`` con valores > 0 → auto-scale al max.
    * Si un valor con ratio > 0 cae en sub-nivel 0 por redondeo,
      forzamos un ``▁`` en la línea inferior (asegura visibilidad
      mínima de barras chiquitas).
    """
    prefix_width = _Y_AXIS_LABEL_WIDTH + len(_Y_AXIS_PREFIX) if show_y_axis else 0
    blank_chart = " " * width_chars
    if not values:
        lines: list[str] = []
        for row in range(height):
            if show_y_axis:
                label = _y_axis_label_for_row(row, height, 0.0)
                lines.append(label + _Y_AXIS_PREFIX + blank_chart)
            else:
                lines.append(blank_chart)
        return "\n".join(lines)
    cap = y_max if y_max > 0 else max(values, default=0.0)
    if cap <= 0:
        lines = []
        for _row in range(height):
            if show_y_axis:
                lines.append(" " * prefix_width + blank_chart)
            else:
                lines.append(blank_chart)
        return "\n".join(lines)

    # Sub-sampling: cada barra es 1 char, cabemos hasta ``width_chars`` barras.
    if len(values) > width_chars:
        chunk_size = len(values) / width_chars
        sampled: list[float] = []
        for i in range(width_chars):
            start = int(i * chunk_size)
            end = int((i + 1) * chunk_size)
            window = values[start:end] or [values[min(start, len(values) - 1)]]
            sampled.append(sum(window) / len(window))
        bars = sampled
    else:
        bars = list(values)

    # Calcular el nivel sub-celda para cada barra.
    total_sub_levels = height * 8
    levels: list[int] = []
    for v in bars:
        ratio = max(0.0, min(1.0, v / cap))
        level = int(round(ratio * total_sub_levels))
        # Mínimo visible: si ratio > 0 pero el redondeo dio 0, mostramos
        # al menos el sub-nivel 1 (un ``▁`` en la línea inferior).
        if ratio > 0 and level == 0:
            level = 1
        levels.append(level)

    # Renderizar de top a bottom.
    lines = []
    for row in range(height):
        rows_from_bottom = height - 1 - row
        row_start = rows_from_bottom * 8
        chars: list[str] = []
        for level in levels:
            in_row = max(0, min(8, level - row_start))
            chars.append(_BLOCKS[in_row])
        # Pad a ``width_chars`` para que todas las filas tengan el
        # mismo ancho.
        bar_line = "".join(chars).ljust(width_chars)
        if show_y_axis:
            label = _y_axis_label_for_row(row, height, cap)
            line = f"{label}{_Y_AXIS_PREFIX}[{color}]{bar_line}[/{color}]"
        else:
            line = f"[{color}]{bar_line}[/{color}]"
        lines.append(line)
    return "\n".join(lines)

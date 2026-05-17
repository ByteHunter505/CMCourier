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


def render_bar_chart(
    values: list[float],
    *,
    y_max: float,
    height: int = 8,
    width_chars: int = 60,
    color: str = "green",
) -> str:
    """078: gráfico de barras vertical multi-línea con rich markup.

    Cada barra ocupa 2 columnas (bloque + espacio) para verse
    "delgada" con aire entre barras. Resolución vertical:
    ``height`` filas × 8 sub-niveles por celda = ``height * 8``
    niveles totales — mucho mejor que los 8 del sparkline.

    Sub-sampling: si ``len(values)`` excede el ancho disponible
    (``width_chars // 2`` barras), agrupa promediando.

    Devuelve un string multi-línea ya envuelto en ``[color]...[/color]``
    rich markup. Textual ``Static`` lo renderiza con el color
    correspondiente sin más config.

    Casos edge:
    * ``values`` vacío → devuelve ``height`` líneas en blanco del
      ancho ``width_chars`` (preserva el layout del caller).
    * ``y_max == 0`` + todos en cero → mismo blank fill.
    * ``y_max == 0`` con valores > 0 → auto-scale al max.
    * Si un valor con ratio > 0 cae en sub-nivel 0 por redondeo,
      forzamos un ``▁`` en la línea inferior (asegura visibilidad
      mínima de barras chiquitas).
    """
    blank_line = " " * width_chars
    if not values:
        return "\n".join([blank_line] * height)
    cap = y_max if y_max > 0 else max(values, default=0.0)
    if cap <= 0:
        return "\n".join([blank_line] * height)

    # Sub-sampling: cada barra son 2 chars, así que cabemos
    # ``width_chars // 2`` barras.
    max_bars = max(1, width_chars // 2)
    if len(values) > max_bars:
        chunk_size = len(values) / max_bars
        sampled: list[float] = []
        for i in range(max_bars):
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
    lines: list[str] = []
    for row in range(height):
        rows_from_bottom = height - 1 - row
        row_start = rows_from_bottom * 8
        chars: list[str] = []
        for level in levels:
            in_row = max(0, min(8, level - row_start))
            chars.append(_BLOCKS[in_row])
            chars.append(" ")
        # Pad a ``width_chars`` para que todas las filas tengan el
        # mismo ancho (preserva el footer alineado debajo).
        line = "".join(chars).rstrip()
        line = line.ljust(width_chars)
        lines.append(f"[{color}]{line}[/{color}]")
    return "\n".join(lines)

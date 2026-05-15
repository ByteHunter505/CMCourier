"""`Sparkline` ASCII compacto para el gráfico de `bandwidth` del tab UPLOAD (025).

Sin dependencias externas — sólo caracteres de bloque mapeados a un
rango 0..1. El eje y se capa en ``y_max`` (provisto por el operador
vía ``cmis.max_bandwidth_mbps``) o auto-escala al pico cuando es 0.
"""

from __future__ import annotations

__all__ = ["render_sparkline"]

# 8 niveles de resolución vertical por columna.
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

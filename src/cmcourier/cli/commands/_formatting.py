"""Formateador chiquito de tablas de texto para la salida CLI hacia el operador.

Evita agregar la dependencia `tabulate`. Dos helpers, ambos puros:

* :func:`render_table`: tabla de texto de ancho fijo con padding por columna.
* :func:`truncate`: truncado de una celda con puntos suspensivos.
"""

from __future__ import annotations

__all__ = ["render_table", "truncate"]

_DEFAULT_CELL_WIDTH = 80


def truncate(value: str, width: int = _DEFAULT_CELL_WIDTH) -> str:
    """Devuelve ``value`` recortado a ``width`` caracteres con un ``...`` al final."""
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "…"


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Renderiza una tabla de texto simple.

    Los anchos de columna ajustan a la celda mas ancha de esa columna.
    La fila de header se separa del cuerpo por una unica linea en
    blanco asi la salida funciona con `grep`, `awk` y los ojos humanos
    por igual.
    """
    if not headers:
        return ""
    columns = max(len(headers), max((len(r) for r in rows), default=0))
    padded_rows = [[*row, *([""] * (columns - len(row)))][:columns] for row in rows]
    padded_headers = [*headers, *([""] * (columns - len(headers)))][:columns]
    widths = [
        max(
            len(padded_headers[i]),
            max((len(row[i]) for row in padded_rows), default=0),
        )
        for i in range(columns)
    ]
    header_line = "  ".join(padded_headers[i].ljust(widths[i]) for i in range(columns)).rstrip()
    body_lines = [
        "  ".join(row[i].ljust(widths[i]) for i in range(columns)).rstrip() for row in padded_rows
    ]
    return "\n".join([header_line, *body_lines])

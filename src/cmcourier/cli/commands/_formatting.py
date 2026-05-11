"""Tiny text-table formatter for operator-facing CLI output.

Avoids adding a `tabulate` dependency. Two helpers, both pure:

* :func:`render_table` — fixed-width text table with column padding.
* :func:`truncate` — single-cell truncation with ellipsis.
"""

from __future__ import annotations

__all__ = ["render_table", "truncate"]

_DEFAULT_CELL_WIDTH = 80


def truncate(value: str, width: int = _DEFAULT_CELL_WIDTH) -> str:
    """Return ``value`` clipped to ``width`` characters with a trailing ``…``."""
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "…"


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a simple text table.

    Column widths fit the widest cell in that column. Header row is
    separated from the body by a single blank line so the output works
    with grep, awk, and human eyes alike.
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

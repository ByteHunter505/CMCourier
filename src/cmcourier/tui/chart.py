"""Compact ASCII sparkline for the UPLOAD-tab bandwidth chart (025).

No external dependencies — just block characters mapped to a 0..1
range. The y-axis caps at ``y_max`` (operator-supplied via
``cmis.max_bandwidth_mbps``) or auto-scales to the peak when 0.
"""

from __future__ import annotations

__all__ = ["render_sparkline"]

# 8 levels of vertical resolution per column.
_BLOCKS: tuple[str, ...] = (" ", "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")


def render_sparkline(values: list[float], *, y_max: float) -> str:
    """Return a single-row Unicode sparkline.

    Empty or all-zero data renders as spaces of the right length so
    callers can still align surrounding text.
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

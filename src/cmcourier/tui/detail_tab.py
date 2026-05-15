"""Renderer del tab DETAIL — drill-down por `chunk` (052).

Dado el `chunk` que seleccionó el operador (con el cursor ``[`` /
``]``) y las filas por-doc leídas del `tracking store`, renderiza
una tabla con el name / size / status / razón de fail o skip de
cada doc. El detalle se lee bajo demanda del store — nunca se
mantiene en memoria para todos los `chunk`s (garantía de memoria
acotada de la spec 050).
"""

from __future__ import annotations

__all__ = ["render_detail"]

from cmcourier.domain.models import DocDetail

# Un `chunk` está capado a ``batch_size`` docs (por defecto 1000).
# 058 hizo el panel DETAIL scrolleable, así que el operador puede
# leer más allá del fold de pantalla — el cap previo de 100 filas
# era un workaround por la falta de scroll. 2000 es un techo de
# seguridad generoso por encima del ``batch_size`` por defecto de
# 1000; el hint ``… N more — full list`` igual se dispara para
# `chunk`s genuinamente enormes para que el operador sea apuntado
# al CLI.
_MAX_ROWS = 2000
_DASH = "—"


def render_detail(
    chunk: dict[str, object] | None,
    docs: list[DocDetail],
    *,
    width: int = 92,
) -> str:
    """Construye el cuerpo del tab DETAIL para el `chunk` seleccionado."""
    lines: list[str] = []
    lines.append("DETAIL — per-chunk drill-down")
    lines.append("─" * width)

    if chunk is None:
        lines.append("")
        lines.append("  (no chunk selected)")
        lines.append("  press  [  /  ]  to move the chunk cursor, then  d  to view")
        lines.append("")
        return "\n".join(lines)

    idx = chunk.get("chunk_idx", "?")
    batch_id = str(chunk.get("batch_id", "")) or _DASH
    status = str(chunk.get("status", "?"))
    lines.append(f"  chunk {idx}   batch {batch_id}   state {status}   docs {len(docs)}")
    lines.append("")

    if not docs:
        lines.append("  (no per-doc rows yet — docs appear here as they reach a terminal state)")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"  {'txn_num':<16}  {'file_name':<22}  {'size':>10}  {'status':<12}  reason")
    lines.append("  " + "─" * (width - 2))
    reason_width = max(10, width - 70)
    for doc in docs[:_MAX_ROWS]:
        reason = doc.error_message or _DASH
        lines.append(
            f"  {doc.txn_num[:16]:<16}  {doc.file_name[:22]:<22}  "
            f"{_human_size(doc.file_size_bytes):>10}  {doc.status:<12}  "
            f"{reason[:reason_width]}"
        )
    if len(docs) > _MAX_ROWS:
        lines.append("")
        lines.append(
            f"  … {len(docs) - _MAX_ROWS} more — full list: cmcourier batch show {batch_id}"
        )
    lines.append("")
    return "\n".join(lines)


def _human_size(n: int) -> str:
    if n <= 0:
        return _DASH
    if n < 1024:
        return f"{n} B"
    if n < 1_048_576:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1_048_576:.1f} MB"

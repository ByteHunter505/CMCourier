"""DETAIL tab renderer — per-chunk drill-down (052).

Given the chunk the operator selected (with the ``[`` / ``]`` cursor)
and the per-doc rows read from the tracking store, render a table of
every doc's name / size / status / fail-or-skip reason. The detail is
read on demand from the store — never held in memory for every chunk
(spec 050's bounded-memory guarantee).
"""

from __future__ import annotations

__all__ = ["render_detail"]

from cmcourier.domain.models import DocDetail

# A chunk is capped at ``batch_size`` docs (default 1000); the live
# dashboard shows the head and points at the CLI for the full list.
_MAX_ROWS = 100
_DASH = "—"


def render_detail(
    chunk: dict[str, object] | None,
    docs: list[DocDetail],
    *,
    width: int = 92,
) -> str:
    """Build the DETAIL tab body for the selected chunk."""
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

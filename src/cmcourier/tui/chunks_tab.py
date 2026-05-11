"""CHUNKS tab renderer (030 — multi-batch live view).

For single-batch runs (``batches_in_flight=1``) shows one row. For
``batches_in_flight=2`` shows every chunk's status as it progresses
through QUEUED → PREP → UPLOAD → DONE (or FAILED).
"""

from __future__ import annotations

__all__ = ["render_chunks"]

from cmcourier.tui.data_provider import TUISnapshot

_STATUS_GLYPH: dict[str, str] = {
    "QUEUED": "·",
    "PREP": "▶",
    "UPLOAD": "▲",
    "DONE": "✓",
    "FAILED": "✗",
}


def render_chunks(snap: TUISnapshot, *, width: int = 76) -> str:
    """Return a multi-line string describing every chunk's current status."""
    lines: list[str] = []
    lines.append(f"CHUNKS — pipeline {snap.pipeline}")
    lines.append("─" * width)
    chunks = snap.chunks_state
    if not chunks:
        lines.append("  (no chunks yet — orchestrator hasn't acquired triggers)")
        lines.append("")
        return "\n".join(lines)

    counts = {"DONE": 0, "PREP": 0, "UPLOAD": 0, "QUEUED": 0, "FAILED": 0}
    for chunk in chunks:
        status = str(chunk.get("status", "QUEUED"))
        if status in counts:
            counts[status] += 1

    total = len(chunks)
    lines.append(
        f"  total {total}   done {counts['DONE']}   "
        f"prep {counts['PREP']}   upload {counts['UPLOAD']}   "
        f"queued {counts['QUEUED']}   failed {counts['FAILED']}"
    )
    lines.append("")
    lines.append(f"  {'idx':>4}  {'batch_id':<14}  {'state':<8}  {'s5_done':>8}  {'s5_failed':>10}")
    lines.append("  " + "─" * (width - 2))

    for chunk in chunks:
        idx_val = chunk.get("chunk_idx", -1)
        idx = int(idx_val) if isinstance(idx_val, int) else -1
        batch_id = str(chunk.get("batch_id", ""))[:14] or "—"
        status = str(chunk.get("status", "?"))
        glyph = _STATUS_GLYPH.get(status, "?")
        done_val = chunk.get("s5_done", 0)
        s5_done = int(done_val) if isinstance(done_val, int) else 0
        failed_val = chunk.get("s5_failed", 0)
        s5_failed = int(failed_val) if isinstance(failed_val, int) else 0
        lines.append(
            f"  {idx:>4}  {batch_id:<14}  {glyph} {status:<6}  {s5_done:>8}  {s5_failed:>10}"
        )

    lines.append("")
    return "\n".join(lines)

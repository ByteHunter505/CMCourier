"""CHUNKS tab renderer (030 — multi-batch live view, 041 — full breakdown).

For single-batch runs (``batches_in_flight=1``) the tab is empty (no
chunks). For ``batches_in_flight=2`` every chunk lights up as it moves
through QUEUED → PREP → UPLOAD → DONE (or FAILED), with per-stage
done/skip/fail counts + elapsed wall-clock + an aggregate TOTAL row.
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

# A stage that hasn't started yet renders all its slots as this dash so the
# table reads as "we haven't done that work yet" rather than "we did it,
# zero outcomes".
_DASH = "—"


def render_chunks(snap: TUISnapshot, *, width: int = 92) -> str:
    """Return a multi-line string describing every chunk's per-stage state.

    The default ``width`` of 92 cols is wider than the rest of the TUI
    (~80) because the breakdown table needs both PREP and UPLOAD blocks
    side-by-side. Operators viewing the TUI on a standard 80-col terminal
    see the table wrap visually — that's acceptable: the CHUNKS tab is a
    "lean closer" view, not a glance view.
    """
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

    lines.append(
        f"  total {len(chunks)}   done {counts['DONE']}   "
        f"prep {counts['PREP']}   upload {counts['UPLOAD']}   "
        f"queued {counts['QUEUED']}   failed {counts['FAILED']}"
    )
    lines.append("")
    lines.append(
        f"  {'idx':>3}  {'batch_id':<14}  {'docs':>5}  {'MB':>7}  "
        f"{'PREP d/s/f (elap)':<22}  {'UPLOAD d/s/f (elap)':<22}  {'state':<10}"
    )
    lines.append("  " + "─" * (width - 2))

    totals = {
        "docs": 0,
        "bytes": 0,
        "prep_done": 0,
        "prep_skipped": 0,
        "prep_failed": 0,
        "prep_elapsed_s": 0.0,
        "upload_done": 0,
        "upload_skipped": 0,
        "upload_failed": 0,
        "upload_elapsed_s": 0.0,
    }
    for chunk in chunks:
        idx = _int(chunk.get("chunk_idx"), -1)
        batch_id = str(chunk.get("batch_id", ""))[:14] or _DASH
        status = str(chunk.get("status", "?"))
        glyph = _STATUS_GLYPH.get(status, "?")
        doc_count = _int(chunk.get("doc_count"), 0)
        total_bytes = _int(chunk.get("total_bytes"), 0)
        mb = total_bytes / 1_048_576.0
        prep_done = _int(chunk.get("prep_done"), 0)
        prep_skipped = _int(chunk.get("prep_skipped"), 0)
        prep_failed = _int(chunk.get("prep_failed"), 0)
        prep_elapsed = _float(chunk.get("prep_elapsed_s"), 0.0)
        upload_done = _int(chunk.get("s5_done"), 0)
        upload_skipped = _int(chunk.get("upload_skipped"), 0)
        upload_failed = _int(chunk.get("s5_failed"), 0)
        upload_elapsed = _float(chunk.get("upload_elapsed_s"), 0.0)

        prep_cell = _stage_cell(
            done=prep_done,
            skipped=prep_skipped,
            failed=prep_failed,
            elapsed_s=prep_elapsed,
            has_started=status in ("PREP", "UPLOAD", "DONE", "FAILED"),
        )
        upload_cell = _stage_cell(
            done=upload_done,
            skipped=upload_skipped,
            failed=upload_failed,
            elapsed_s=upload_elapsed,
            has_started=status in ("UPLOAD", "DONE", "FAILED"),
        )

        lines.append(
            f"  {idx:>3}  {batch_id:<14}  {doc_count:>5}  {mb:>7.1f}  "
            f"{prep_cell:<22}  {upload_cell:<22}  {glyph} {status:<8}"
        )

        # Aggregate. QUEUED rows contribute their plan (docs/bytes) but no
        # outcomes — matches what the operator expects from the TOTAL row.
        totals["docs"] += doc_count
        totals["bytes"] += total_bytes
        totals["prep_done"] += prep_done
        totals["prep_skipped"] += prep_skipped
        totals["prep_failed"] += prep_failed
        totals["prep_elapsed_s"] += prep_elapsed
        totals["upload_done"] += upload_done
        totals["upload_skipped"] += upload_skipped
        totals["upload_failed"] += upload_failed
        totals["upload_elapsed_s"] += upload_elapsed

    lines.append("  " + "─" * (width - 2))
    total_mb = totals["bytes"] / 1_048_576.0
    prep_total_cell = _stage_cell(
        done=int(totals["prep_done"]),
        skipped=int(totals["prep_skipped"]),
        failed=int(totals["prep_failed"]),
        elapsed_s=float(totals["prep_elapsed_s"]),
        has_started=any(int(totals[k]) > 0 for k in ("prep_done", "prep_skipped", "prep_failed")),
    )
    upload_total_cell = _stage_cell(
        done=int(totals["upload_done"]),
        skipped=int(totals["upload_skipped"]),
        failed=int(totals["upload_failed"]),
        elapsed_s=float(totals["upload_elapsed_s"]),
        has_started=any(
            int(totals[k]) > 0 for k in ("upload_done", "upload_skipped", "upload_failed")
        ),
    )
    label = f"TOTAL ({len(chunks)} chunks)"
    lines.append(
        f"  {label:<19}  {int(totals['docs']):>5}  {total_mb:>7.1f}  "
        f"{prep_total_cell:<22}  {upload_total_cell:<22}"
    )
    lines.append("")
    return "\n".join(lines)


def _stage_cell(
    *,
    done: int,
    skipped: int,
    failed: int,
    elapsed_s: float,
    has_started: bool,
) -> str:
    """Format one ``done/skip/fail (elapsed)`` cell.

    When ``has_started`` is False (e.g. QUEUED rows for the UPLOAD stage),
    renders dashes so an operator does not mistake "not yet" for "zero".
    """
    if not has_started:
        return f"{_DASH}/{_DASH}/{_DASH}   {_DASH}"
    elapsed_str = f"{elapsed_s:.1f}s" if elapsed_s > 0 else _DASH
    return f"{done}/{skipped}/{failed}   ({elapsed_str})"


def _int(v: object, default: int) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    return default


def _float(v: object, default: float) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    return default

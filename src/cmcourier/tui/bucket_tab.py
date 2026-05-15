"""BUCKET tab renderer (064 — streaming mode).

In streaming mode the pipeline is one continuous producer-consumer
loop: PREP workers (S1-S4) push prepared docs into a bounded
**bucket** that S5 workers drain. The BUCKET tab gives the operator
a live view of:

* bucket level vs cap (back-pressure indicator)
* peak bucket level since run start
* PREP throughput (docs/s entering the bucket, 5s sliding window)
* S5 throughput (docs/s leaving the bucket, 5s sliding window)
* live worker counts (PREP busy/configured, S5 configured)
* cumulative per-status counts (S5_DONE, S5_FAILED, S1_FILTERED,
  S1_SKIPPED)

In batched mode the renderer prints a one-line stub directing the
operator to the CHUNKS tab.
"""

from __future__ import annotations

__all__ = ["render_bucket"]

from cmcourier.tui.data_provider import TUISnapshot


def _int_or_zero(value: object) -> int:
    return value if isinstance(value, int) else 0


def _bar(level: int, cap: int, width: int = 30) -> str:
    if cap <= 0:
        return "[" + " " * width + "]"
    filled = max(0, min(width, round((level / cap) * width)))
    return "[" + ("█" * filled) + (" " * (width - filled)) + "]"


def render_bucket(snap: TUISnapshot) -> str:
    if snap.mode != "streaming" or snap.bucket is None:
        return "BUCKET tab is active in streaming mode only — see CHUNKS for batched runs."

    b = snap.bucket
    cumulative = _summarise_chunks(snap)

    return "\n".join(
        [
            "BUCKET",
            "──────",
            (
                f"  level  {b.bucket_level:>5d} / {b.bucket_cap:<5d}  "
                f"{_bar(b.bucket_level, b.bucket_cap)}"
            ),
            f"  peak   {b.bucket_peak:>5d} / {b.bucket_cap:<5d}",
            "",
            "THROUGHPUT (5s window)",
            "──────────────────────",
            f"  PREP   {b.prep_docs_per_s:>7.2f} docs/s",
            f"  S5     {b.upload_docs_per_s:>7.2f} docs/s",
            "",
            "WORKERS",
            "───────",
            f"  PREP   {b.prep_in_flight:>3d} in-flight / {b.prep_workers:<3d} configured",
            f"  S5     up to {b.upload_workers:<3d} consumer threads",
            "",
            "OUTCOMES (cumulative)",
            "─────────────────────",
            f"  S5_DONE     {cumulative['s5_done']:>6d}",
            f"  S5_FAILED   {cumulative['s5_failed']:>6d}",
            f"  S1_FILTERED {cumulative['s1_filtered']:>6d}",
            f"  S1_SKIPPED  {cumulative['s1_skipped']:>6d}",
        ]
    )


def _summarise_chunks(snap: TUISnapshot) -> dict[str, int]:
    """Read cumulative outcomes from the single synthetic chunk row."""
    s5_done = 0
    s5_failed = 0
    s1_filtered = snap.s1_filtered
    s1_skipped = 0
    for chunk in snap.chunks_state:
        s5_done += _int_or_zero(chunk.get("s5_done"))
        s5_failed += _int_or_zero(chunk.get("s5_failed"))
        s1_skipped += _int_or_zero(chunk.get("prep_skipped"))
    return {
        "s5_done": s5_done,
        "s5_failed": s5_failed,
        "s1_filtered": s1_filtered,
        "s1_skipped": s1_skipped,
    }

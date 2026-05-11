"""PREP tab renderer (025 phase 3)."""

from __future__ import annotations

__all__ = ["render_prep"]

from cmcourier.tui.data_provider import PREP_STAGES, TUISnapshot

_STAGE_LABELS: dict[str, str] = {
    "S0": "TRIGGER",
    "S1": "INDEXING",
    "S2": "MAPPING",
    "S3": "METADATA",
    "S4": "ASSEMBLY",
}


def render_prep(snap: TUISnapshot, *, width: int = 76) -> str:
    """Build the PREP tab body as a multi-line string."""
    lines: list[str] = []
    for stage in PREP_STAGES:
        info = snap.stages.get(stage, {})
        count = int(info.get("count", 0))
        p50 = float(info.get("p50_ms", 0.0))
        p95 = float(info.get("p95_ms", 0.0))
        bar = _bar(count, _stage_target(snap, stage), width=28)
        lines.append(
            f"  {stage} {_STAGE_LABELS.get(stage, stage):8}  {bar}  "
            f"{count:>6}  p50 {p50:>7.1f} ms  p95 {p95:>7.1f} ms"
        )
    lines.append("")
    lines.append(" SLOW OPS (PREP, top 5)")
    prep_slow = [
        op
        for op in snap.slow_ops_all
        if str(op.get("stage", "")).startswith(("S1", "S2", "S3", "S4"))
    ]
    if not prep_slow:
        lines.append("    (none yet)")
    else:
        for op in prep_slow[:5]:
            stage = str(op.get("stage", "?"))
            txn = str(op.get("txn_num", "?"))
            dms_val = op.get("duration_ms", 0.0)
            rank_val = op.get("rank", 0)
            dms = float(dms_val) if isinstance(dms_val, (int, float)) else 0.0
            rank = int(rank_val) if isinstance(rank_val, (int, float)) else 0
            lines.append(f"  {rank}  {stage:12}  {txn:<14}  {dms:>10,.0f} ms")
    return "\n".join(lines)


def _bar(value: int, target: int, *, width: int) -> str:
    if target <= 0:
        return " " * width
    ratio = max(0.0, min(1.0, value / target))
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)


def _stage_target(snap: TUISnapshot, stage: str) -> int:
    """Best-effort upper bound for the progress bar — the largest count
    seen across S0..S5 (since S0 is the triggers total)."""
    counts = [int(s.get("count", 0)) for s in snap.stages.values()]
    return max(counts, default=0)

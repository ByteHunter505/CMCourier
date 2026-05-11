"""UPLOAD tab renderer (025 phase 3)."""

from __future__ import annotations

__all__ = ["render_upload"]

from cmcourier.tui.chart import render_sparkline
from cmcourier.tui.data_provider import UPLOAD_STAGE, TUISnapshot


def render_upload(snap: TUISnapshot, *, width: int = 76) -> str:
    """Build the UPLOAD tab body as a multi-line string."""
    s5 = snap.stages.get(UPLOAD_STAGE, {})
    count = int(s5.get("count", 0))
    p50 = float(s5.get("p50_ms", 0.0))
    p95 = float(s5.get("p95_ms", 0.0))
    p99 = float(s5.get("p99_ms", 0.0))
    target = max(count + snap.queue_depth, 1)
    bar = _bar(count, target, width=28)

    lines: list[str] = [
        f"  S5 UPLOAD     {bar}  {count:>4} / {target:<4}",
        f"                p50 {p50:>7.1f} ms  p95 {p95:>7.1f} ms  p99 {p99:>7.1f} ms",
        "",
    ]
    if snap.lane_snapshot is not None:
        # 036: dual heavy/light sub-panels replace the single-pool view.
        lines.extend(_render_lane_panels(snap))
    else:
        lines.extend(
            [
                " WORKERS",
                f"  Pool capacity:   {snap.pool_capacity}   "
                f"in-use {snap.pool_in_use}   idle {snap.pool_idle}",
                f"  Queue depth:     {snap.queue_depth} pending",
            ]
        )
    if snap.auto_tune_enabled:
        lines.append("  Auto-tune:       ON")
        lines.append(
            f"    target p95:    {snap.auto_tune_target_p95_ms:,.0f} ms   "
            f"observed p95: {snap.auto_tune_observed_p95_ms:,.1f} ms"
        )
        lines.append(
            f"    adjust:        every {snap.auto_tune_adjust_interval_s}s   "
            f"next: in {snap.auto_tune_next_in_s:.0f}s"
        )
        lines.append(
            f"    timeout:       {snap.auto_tune_timeout_s:.1f}s active   "
            f"(range {snap.auto_tune_timeout_min_s}–{snap.auto_tune_timeout_max_s}s)"
        )
        last_ago = snap.auto_tune_seconds_since_last_decision
        last_ago_s = f"{int(last_ago)}s ago" if last_ago is not None else "—"
        lines.append(
            f"    last move:     {snap.auto_tune_last_action} → "
            f"workers={snap.auto_tune_last_workers_after}  ({last_ago_s})"
        )
    else:
        lines.append("  Auto-tune:       OFF")

    lines.append("")
    lines.append(" NETWORK (CMIS)")
    lines.append(f"  Endpoint:      {snap.cmis_endpoint[:60]}")
    ceiling_str = (
        f"  ceiling {snap.bandwidth_ceiling_mbps:.1f} MB/s (config)"
        if snap.bandwidth_ceiling_mbps > 0
        else "  ceiling — (auto-scale)"
    )
    lines.append(
        f"  Bandwidth:     {snap.bandwidth_current_mbps:5.2f} MB/s   "
        f"peak {snap.bandwidth_peak_mbps:5.2f} MB/s{ceiling_str}"
    )

    lines.append("")
    chart_title = " UPLOAD SPEED (60s · MB/s · "
    if snap.bandwidth_ceiling_mbps > 0:
        chart_title += f"y: 0 → {snap.bandwidth_ceiling_mbps:.1f})"
    else:
        chart_title += f"y: 0 → peak {snap.bandwidth_peak_mbps:.2f})"
    lines.append(chart_title)
    series_values = [v for _, v in snap.bandwidth_series]
    if not series_values:
        lines.append("  " + " " * 60)
    else:
        lines.append("  " + render_sparkline(series_values, y_max=snap.bandwidth_ceiling_mbps))
        lines.append("  " + " " * 0 + "└" + "─" * 58 + "┘  -60s ............. now")

    lines.append("")
    lines.append(" SLOW OPS (UPLOAD, top 5)")
    upload_slow = [op for op in snap.slow_ops_all if str(op.get("kind", "")) == "cmis_upload"]
    if not upload_slow:
        lines.append("    (none yet)")
    else:
        for op in upload_slow[:5]:
            rank_val = op.get("rank", 0)
            dms_val = op.get("duration_ms", 0.0)
            rank = int(rank_val) if isinstance(rank_val, (int, float)) else 0
            dms = float(dms_val) if isinstance(dms_val, (int, float)) else 0.0
            txn = str(op.get("txn_num", "?"))
            worker = str(op.get("worker", "?"))
            lines.append(f"  {rank}  {txn:<14}  {worker:<20}  {dms:>10,.0f} ms")

    if snap.is_complete:
        lines.append("")
        lines.append(" ──────────────────────────────────────────────────────")
        lines.append(" RUN COMPLETE.  Press [Q] to exit.")
        lines.append(" ──────────────────────────────────────────────────────")

    return "\n".join(lines)


def _bar(value: int, target: int, *, width: int) -> str:
    if target <= 0:
        return " " * width
    ratio = max(0.0, min(1.0, value / target))
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)


def _render_lane_panels(snap: TUISnapshot) -> list[str]:
    """036: render side-by-side HEAVY/LIGHT panels for dual-lane runs."""
    assert snap.lane_snapshot is not None
    ls = snap.lane_snapshot
    return [
        f" WORKERS (heavy/light · total budget {ls.total_budget})",
        f"  HEAVY  capacity {ls.heavy.pool_size:>3}   "
        f"in-use {ls.heavy.busy:>3}   "
        f"idle {ls.heavy.idle:>3}   "
        f"queue {ls.heavy.queue_depth:>4}",
        f"         done {ls.heavy.completed:>5}   failed {ls.heavy.failed:>4}",
        f"  LIGHT  capacity {ls.light.pool_size:>3}   "
        f"in-use {ls.light.busy:>3}   "
        f"idle {ls.light.idle:>3}   "
        f"queue {ls.light.queue_depth:>4}",
        f"         done {ls.light.completed:>5}   failed {ls.light.failed:>4}",
    ]

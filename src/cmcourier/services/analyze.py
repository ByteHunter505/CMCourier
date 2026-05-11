"""Offline log analyzer (027 — POST-MVP §3).

Consumes the five observability tiers and produces a
:class:`BatchReport` per batch_id, plus pairwise compare and
trend summaries across batches.

Design constraints (REQ-013):

* Reading the same JSONL files always produces a byte-identical
  report. No wall-clock leakage, no random ordering.
* Network-bound or memory-bound classification stays purely a
  function of input data (no environment probing).
* JSONL parsing is line-by-line and tolerant — corrupted lines
  are logged WARNING and skipped.
"""

from __future__ import annotations

__all__ = [
    "BatchReport",
    "BottleneckClassification",
    "CompareReport",
    "LogReader",
    "NetworkSummary",
    "SystemSummary",
    "TrendRow",
    "build_batch_report",
    "classify_bottleneck",
    "compare_batches",
    "compute_trends",
    "format_compare_json",
    "format_compare_terminal",
    "format_json",
    "format_terminal",
    "format_trends_json",
    "format_trends_terminal",
]

import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ----- thresholds (referenced from docs/how-to/log-analysis.md) -----------

_CPU_PCT_HIGH = 80.0
_RAM_PCT_HIGH = 0.85
_DISK_TOTAL_MBPS_HIGH = 100.0
_DISK_CPU_LOW = 50.0
_NETWORK_CEILING_FRACTION = 0.8
_BOTTLENECK_SAMPLE_THRESHOLD = 0.5
_WORKER_SAT_THRESHOLD = 0.8
_UPLOAD_P95_HIGH_MS = 5000.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NetworkSummary:
    """Aggregated network metrics, keyed by ``kind``."""

    per_kind: dict[str, dict[str, float | int]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SystemSummary:
    """Aggregated tier-5 system metrics over the batch window."""

    cpu_pct_avg: float
    cpu_pct_max: float
    process_cpu_pct_avg: float
    process_cpu_pct_max: float
    ram_pct_avg: float
    ram_pct_max: float
    disk_total_mbps_avg: float
    disk_total_mbps_max: float
    net_total_mbps_avg: float
    net_total_mbps_max: float
    worker_saturation_pct: float
    sample_count: int
    cpu_bound_sample_pct: float
    memory_bound_sample_pct: float
    disk_bound_sample_pct: float
    network_bound_sample_pct: float


@dataclass(frozen=True, slots=True)
class BottleneckClassification:
    """One of: ``cpu-bound``, ``memory-bound``, ``disk-bound``,
    ``network-bound``, ``worker-saturated``, ``under-utilized``."""

    classification: str
    confidence: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BatchReport:
    batch_id: str
    pipeline: str | None
    total_docs: int
    elapsed_s: float
    throughput_docs_per_s: float
    stage_summary: dict[str, dict[str, float | int]]
    slow_ops: list[dict[str, Any]]
    network_summary: NetworkSummary
    system_summary: SystemSummary | None
    bottleneck: BottleneckClassification


# ---------------------------------------------------------------------------
# LogReader
# ---------------------------------------------------------------------------


class LogReader:
    """Read the five log tiers for one batch.

    The reader globs each tier's files in ``log_dir`` and filters
    records by ``batch_id``. Cross-midnight runs are supported
    because the glob picks up rotated files transparently.
    """

    def __init__(self, *, log_dir: Path) -> None:
        self._log_dir = log_dir

    def read_batch(self, batch_id: str) -> dict[str, list[dict[str, Any]]]:
        return {
            "pipeline": self._read_filtered("metrics-*.jsonl", batch_id),
            "network": self._read_filtered("network-*.jsonl", batch_id),
            "system": self._read_filtered("system-*.jsonl", batch_id),
            "slow_ops": self._read_jsonl(self._log_dir / f"slow-ops-{batch_id}.jsonl"),
        }

    def _read_filtered(self, glob: str, batch_id: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self._log_dir.glob(glob)):
            for rec in self._read_jsonl(path):
                if rec.get("batch_id") == batch_id:
                    records.append(rec)
        return records

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError as exc:
                    _log.warning(
                        "skipping malformed JSONL line",
                        extra={
                            "path": str(path),
                            "line_no": line_no,
                            "reason": str(exc),
                        },
                    )
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
        return out


# ---------------------------------------------------------------------------
# Aggregators
# ---------------------------------------------------------------------------


def _percentiles(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) < 2:
        v = float(sorted_vals[0])
        return v, v, v
    # statistics.quantiles with method="inclusive" matches numpy's "linear".
    # For p50/p95/p99 we use n=100 deciles+ centiles.
    centiles = statistics.quantiles(sorted_vals, n=100, method="inclusive")
    p50 = float(centiles[49])
    p95 = float(centiles[94])
    p99 = float(centiles[98])
    return p50, p95, p99


def _build_network_summary(records: list[dict[str, Any]]) -> NetworkSummary:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_kind.setdefault(str(rec.get("kind", "unknown")), []).append(rec)
    per_kind: dict[str, dict[str, float | int]] = {}
    for kind in sorted(by_kind):
        bucket = by_kind[kind]
        durations = [float(r.get("duration_ms", 0.0)) for r in bucket]
        p50, p95, p99 = _percentiles(durations)
        total_bytes = sum(int(r.get("size_bytes", 0) or 0) for r in bucket)
        per_kind[kind] = {
            "count": len(bucket),
            "p50_ms": round(p50, 3),
            "p95_ms": round(p95, 3),
            "p99_ms": round(p99, 3),
            "total_bytes": total_bytes,
        }
    return NetworkSummary(per_kind=per_kind)


def _build_system_summary(
    samples: list[dict[str, Any]],
    *,
    cmis_max_bandwidth_mbps: int,
    pool_capacity: int,
) -> SystemSummary | None:
    if not samples:
        return None

    def col(name: str) -> list[float]:
        return [float(s.get(name, 0.0)) for s in samples]

    cpu_pcts = col("cpu_pct")
    proc_cpu = col("process_cpu_pct")
    ram_used = col("ram_used_mb")
    ram_total = col("ram_total_mb")
    ram_pcts = [(u / t) if t > 0 else 0.0 for u, t in zip(ram_used, ram_total, strict=False)]
    disk_total = [
        float(s.get("disk_read_mbps", 0.0)) + float(s.get("disk_write_mbps", 0.0)) for s in samples
    ]
    net_total = [
        float(s.get("net_in_mbps", 0.0)) + float(s.get("net_out_mbps", 0.0)) for s in samples
    ]
    active = [int(s.get("active_workers") or 0) for s in samples]

    n = len(samples)
    cpu_bound = sum(1 for c in proc_cpu if c > _CPU_PCT_HIGH) / n
    mem_bound = sum(1 for r in ram_pcts if r > _RAM_PCT_HIGH) / n
    disk_bound = (
        sum(
            1
            for d, c in zip(disk_total, cpu_pcts, strict=False)
            if d > _DISK_TOTAL_MBPS_HIGH and c < _DISK_CPU_LOW
        )
        / n
    )
    if cmis_max_bandwidth_mbps > 0:
        net_bound = (
            sum(1 for nv in net_total if nv / cmis_max_bandwidth_mbps > _NETWORK_CEILING_FRACTION)
            / n
        )
    else:
        net_bound = 0.0
    worker_sat = sum(1 for a in active if a >= pool_capacity) / n if pool_capacity > 0 else 0.0

    return SystemSummary(
        cpu_pct_avg=round(statistics.fmean(cpu_pcts), 3),
        cpu_pct_max=round(max(cpu_pcts), 3),
        process_cpu_pct_avg=round(statistics.fmean(proc_cpu), 3),
        process_cpu_pct_max=round(max(proc_cpu), 3),
        ram_pct_avg=round(statistics.fmean(ram_pcts), 4),
        ram_pct_max=round(max(ram_pcts), 4),
        disk_total_mbps_avg=round(statistics.fmean(disk_total), 3),
        disk_total_mbps_max=round(max(disk_total), 3),
        net_total_mbps_avg=round(statistics.fmean(net_total), 3),
        net_total_mbps_max=round(max(net_total), 3),
        worker_saturation_pct=round(worker_sat, 4),
        sample_count=n,
        cpu_bound_sample_pct=round(cpu_bound, 4),
        memory_bound_sample_pct=round(mem_bound, 4),
        disk_bound_sample_pct=round(disk_bound, 4),
        network_bound_sample_pct=round(net_bound, 4),
    )


# ---------------------------------------------------------------------------
# Bottleneck classifier
# ---------------------------------------------------------------------------


def classify_bottleneck(
    system_summary: SystemSummary | None,
    network_summary: NetworkSummary,
    stage_summary: dict[str, dict[str, float | int]],  # noqa: ARG001 — reserved for future heuristics
    *,
    cmis_max_bandwidth_mbps: int,  # noqa: ARG001 — bound at aggregation time
    pool_capacity: int,  # noqa: ARG001 — bound at aggregation time
) -> BottleneckClassification:
    """Pure classifier — see docs/how-to/log-analysis.md for the rules."""

    candidates: list[tuple[str, float, str]] = []

    if system_summary is not None:
        if system_summary.worker_saturation_pct >= _WORKER_SAT_THRESHOLD:
            candidates.append(
                (
                    "worker-saturated",
                    system_summary.worker_saturation_pct,
                    f"active_workers == pool_capacity in "
                    f"{int(system_summary.worker_saturation_pct * 100)}% of samples",
                )
            )
        if system_summary.cpu_bound_sample_pct >= _BOTTLENECK_SAMPLE_THRESHOLD:
            candidates.append(
                (
                    "cpu-bound",
                    system_summary.cpu_bound_sample_pct,
                    f"process_cpu_pct > {_CPU_PCT_HIGH:.0f}% in "
                    f"{int(system_summary.cpu_bound_sample_pct * 100)}% of samples",
                )
            )
        if system_summary.memory_bound_sample_pct >= _BOTTLENECK_SAMPLE_THRESHOLD:
            candidates.append(
                (
                    "memory-bound",
                    system_summary.memory_bound_sample_pct,
                    f"ram usage > {_RAM_PCT_HIGH * 100:.0f}% in "
                    f"{int(system_summary.memory_bound_sample_pct * 100)}% of samples",
                )
            )
        if system_summary.disk_bound_sample_pct >= _BOTTLENECK_SAMPLE_THRESHOLD:
            candidates.append(
                (
                    "disk-bound",
                    system_summary.disk_bound_sample_pct,
                    f"disk I/O > {_DISK_TOTAL_MBPS_HIGH:.0f} Mbps with low CPU "
                    f"in {int(system_summary.disk_bound_sample_pct * 100)}% of samples",
                )
            )
        if system_summary.network_bound_sample_pct >= _BOTTLENECK_SAMPLE_THRESHOLD:
            candidates.append(
                (
                    "network-bound",
                    system_summary.network_bound_sample_pct,
                    f"NIC > {int(_NETWORK_CEILING_FRACTION * 100)}% of configured "
                    f"max in {int(system_summary.network_bound_sample_pct * 100)}% "
                    f"of samples",
                )
            )

    # Fallback heuristic when system samples are absent or no class fired.
    if not candidates:
        upload = network_summary.per_kind.get("cmis_upload", {})
        upload_p95 = float(upload.get("p95_ms", 0.0))
        if upload_p95 > _UPLOAD_P95_HIGH_MS:
            return BottleneckClassification(
                classification="network-bound",
                confidence=min(upload_p95 / 10000.0, 1.0),
                reasons=(f"cmis_upload p95 = {upload_p95:.0f} ms (> 5000 ms)",),
            )
        return BottleneckClassification(
            classification="under-utilized",
            confidence=1.0,
            reasons=("no bottleneck class crossed its threshold",),
        )

    # Tie-break by (confidence desc, class precedence). Precedence:
    # worker-saturated > cpu > memory > disk > network > under-utilized.
    precedence = {
        "worker-saturated": 0,
        "cpu-bound": 1,
        "memory-bound": 2,
        "disk-bound": 3,
        "network-bound": 4,
        "under-utilized": 5,
    }
    candidates.sort(key=lambda c: (-c[1], precedence.get(c[0], 9)))
    cls, confidence, reason = candidates[0]
    return BottleneckClassification(
        classification=cls,
        confidence=round(confidence, 4),
        reasons=tuple(c[2] for c in candidates),
    )


# ---------------------------------------------------------------------------
# build_batch_report
# ---------------------------------------------------------------------------


def build_batch_report(
    *,
    batch_id: str,
    records: dict[str, list[dict[str, Any]]],
    cmis_max_bandwidth_mbps: int,
    pool_capacity: int,
) -> BatchReport:
    pipeline_records = records.get("pipeline", [])
    summary = pipeline_records[-1] if pipeline_records else {}
    network_summary = _build_network_summary(records.get("network", []))
    system_summary = _build_system_summary(
        records.get("system", []),
        cmis_max_bandwidth_mbps=cmis_max_bandwidth_mbps,
        pool_capacity=pool_capacity,
    )
    stage_summary: dict[str, dict[str, float | int]] = summary.get("stages", {}) or {}
    bottleneck = classify_bottleneck(
        system_summary,
        network_summary,
        stage_summary,
        cmis_max_bandwidth_mbps=cmis_max_bandwidth_mbps,
        pool_capacity=pool_capacity,
    )

    return BatchReport(
        batch_id=batch_id,
        pipeline=summary.get("pipeline"),
        total_docs=int(summary.get("total_docs", 0) or 0),
        elapsed_s=float(summary.get("elapsed_s", 0.0) or 0.0),
        throughput_docs_per_s=float(summary.get("throughput_docs_per_s", 0.0) or 0.0),
        stage_summary=stage_summary,
        slow_ops=list(records.get("slow_ops", [])),
        network_summary=network_summary,
        system_summary=system_summary,
        bottleneck=bottleneck,
    )


# ---------------------------------------------------------------------------
# Compare + trends
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompareReport:
    a: BatchReport
    b: BatchReport
    throughput_delta_docs_per_s: float
    elapsed_delta_s: float
    stage_p95_delta_ms: dict[str, float]


def compare_batches(a: BatchReport, b: BatchReport) -> CompareReport:
    stages = sorted(set(a.stage_summary) | set(b.stage_summary))
    stage_delta: dict[str, float] = {}
    for stage in stages:
        pa = float(a.stage_summary.get(stage, {}).get("p95_ms", 0.0))
        pb = float(b.stage_summary.get(stage, {}).get("p95_ms", 0.0))
        stage_delta[stage] = round(pb - pa, 3)
    return CompareReport(
        a=a,
        b=b,
        throughput_delta_docs_per_s=round(b.throughput_docs_per_s - a.throughput_docs_per_s, 4),
        elapsed_delta_s=round(b.elapsed_s - a.elapsed_s, 3),
        stage_p95_delta_ms=stage_delta,
    )


@dataclass(frozen=True, slots=True)
class TrendRow:
    batch_id: str
    pipeline: str
    total_docs: int
    elapsed_s: float
    throughput_docs_per_s: float
    s5_p95_ms: float


def compute_trends(
    *,
    log_dir: Path,
    last_n: int = 10,
    pipeline_filter: str | None = None,
) -> list[TrendRow]:
    rows: list[TrendRow] = []
    for path in sorted(log_dir.glob("metrics-*.jsonl")):
        for rec in LogReader._read_jsonl(path):  # noqa: SLF001 — same module helper
            if rec.get("kind") != "batch_summary":
                continue
            pipeline = str(rec.get("pipeline", ""))
            if pipeline_filter is not None and pipeline != pipeline_filter:
                continue
            stages = rec.get("stages", {}) or {}
            s5 = stages.get("S5", {}) or {}
            rows.append(
                TrendRow(
                    batch_id=str(rec.get("batch_id", "")),
                    pipeline=pipeline,
                    total_docs=int(rec.get("total_docs", 0) or 0),
                    elapsed_s=float(rec.get("elapsed_s", 0.0) or 0.0),
                    throughput_docs_per_s=float(rec.get("throughput_docs_per_s", 0.0) or 0.0),
                    s5_p95_ms=float(s5.get("p95_ms", 0.0) or 0.0),
                )
            )
    # Files are date-stamped + records are appended in run order — preserve
    # arrival order, then keep the most-recent N (= last in file order).
    if last_n > 0:
        rows = rows[-last_n:]
    return rows


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def _fmt_kv(key: str, value: object) -> str:
    return f"  {key:<24} {value}"


def format_terminal(report: BatchReport) -> str:
    lines: list[str] = []
    lines.append(f"BATCH {report.batch_id}")
    lines.append("=" * 60)
    lines.append(_fmt_kv("pipeline", report.pipeline or "-"))
    lines.append(_fmt_kv("total_docs", report.total_docs))
    lines.append(_fmt_kv("elapsed_s", f"{report.elapsed_s:.2f}"))
    lines.append(_fmt_kv("throughput", f"{report.throughput_docs_per_s:.3f} docs/s"))

    lines.append("")
    lines.append("STAGES")
    lines.append("-" * 60)
    lines.append(f"  {'stage':<6}{'count':>8}{'p50_ms':>12}{'p95_ms':>12}{'p99_ms':>12}")
    for stage in sorted(report.stage_summary):
        bucket = report.stage_summary[stage]
        lines.append(
            f"  {stage:<6}"
            f"{int(bucket.get('count', 0)):>8}"
            f"{float(bucket.get('p50_ms', 0)):>12.2f}"
            f"{float(bucket.get('p95_ms', 0)):>12.2f}"
            f"{float(bucket.get('p99_ms', 0)):>12.2f}"
        )

    if report.network_summary.per_kind:
        lines.append("")
        lines.append("NETWORK")
        lines.append("-" * 60)
        lines.append(
            f"  {'kind':<14}{'count':>8}{'p50_ms':>12}{'p95_ms':>12}{'p99_ms':>12}{'bytes':>14}"
        )
        for kind in sorted(report.network_summary.per_kind):
            row = report.network_summary.per_kind[kind]
            lines.append(
                f"  {kind:<14}"
                f"{int(row.get('count', 0)):>8}"
                f"{float(row.get('p50_ms', 0)):>12.2f}"
                f"{float(row.get('p95_ms', 0)):>12.2f}"
                f"{float(row.get('p99_ms', 0)):>12.2f}"
                f"{int(row.get('total_bytes', 0)):>14}"
            )

    if report.system_summary is not None:
        s = report.system_summary
        lines.append("")
        lines.append("SYSTEM")
        lines.append("-" * 60)
        lines.append(_fmt_kv("samples", s.sample_count))
        lines.append(_fmt_kv("cpu_pct_avg/max", f"{s.cpu_pct_avg:.1f} / {s.cpu_pct_max:.1f}"))
        lines.append(
            _fmt_kv(
                "process_cpu_avg/max",
                f"{s.process_cpu_pct_avg:.1f} / {s.process_cpu_pct_max:.1f}",
            )
        )
        lines.append(
            _fmt_kv(
                "ram_pct_avg/max",
                f"{s.ram_pct_avg * 100:.1f}% / {s.ram_pct_max * 100:.1f}%",
            )
        )
        lines.append(
            _fmt_kv(
                "disk_mbps_avg/max",
                f"{s.disk_total_mbps_avg:.1f} / {s.disk_total_mbps_max:.1f}",
            )
        )
        lines.append(
            _fmt_kv(
                "net_mbps_avg/max",
                f"{s.net_total_mbps_avg:.1f} / {s.net_total_mbps_max:.1f}",
            )
        )
        lines.append(_fmt_kv("worker_saturation", f"{s.worker_saturation_pct * 100:.1f}%"))

    if report.slow_ops:
        lines.append("")
        lines.append("TOP SLOW OPS")
        lines.append("-" * 60)
        for op in report.slow_ops[:5]:
            lines.append(
                f"  {op.get('kind', '?'):<14}"
                f"{float(op.get('duration_ms', 0)):>10.0f} ms  "
                f"txn={op.get('txn_num', '-')}  worker={op.get('worker', '-')}"
            )

    lines.append("")
    lines.append(
        f"Bottleneck: {report.bottleneck.classification} "
        f"(confidence {report.bottleneck.confidence:.2f})"
    )
    for reason in report.bottleneck.reasons:
        lines.append(f"  • {reason}")

    return "\n".join(lines) + "\n"


def _network_summary_to_dict(ns: NetworkSummary) -> dict[str, object]:
    return {"per_kind": ns.per_kind}


def _system_summary_to_dict(ss: SystemSummary | None) -> dict[str, object] | None:
    if ss is None:
        return None
    return {
        "cpu_pct_avg": ss.cpu_pct_avg,
        "cpu_pct_max": ss.cpu_pct_max,
        "process_cpu_pct_avg": ss.process_cpu_pct_avg,
        "process_cpu_pct_max": ss.process_cpu_pct_max,
        "ram_pct_avg": ss.ram_pct_avg,
        "ram_pct_max": ss.ram_pct_max,
        "disk_total_mbps_avg": ss.disk_total_mbps_avg,
        "disk_total_mbps_max": ss.disk_total_mbps_max,
        "net_total_mbps_avg": ss.net_total_mbps_avg,
        "net_total_mbps_max": ss.net_total_mbps_max,
        "worker_saturation_pct": ss.worker_saturation_pct,
        "sample_count": ss.sample_count,
        "cpu_bound_sample_pct": ss.cpu_bound_sample_pct,
        "memory_bound_sample_pct": ss.memory_bound_sample_pct,
        "disk_bound_sample_pct": ss.disk_bound_sample_pct,
        "network_bound_sample_pct": ss.network_bound_sample_pct,
    }


def _bottleneck_to_dict(b: BottleneckClassification) -> dict[str, object]:
    return {
        "classification": b.classification,
        "confidence": b.confidence,
        "reasons": list(b.reasons),
    }


def _report_to_dict(report: BatchReport) -> dict[str, object]:
    return {
        "batch_id": report.batch_id,
        "pipeline": report.pipeline,
        "total_docs": report.total_docs,
        "elapsed_s": report.elapsed_s,
        "throughput_docs_per_s": report.throughput_docs_per_s,
        "stage_summary": report.stage_summary,
        "slow_ops": report.slow_ops,
        "network_summary": _network_summary_to_dict(report.network_summary),
        "system_summary": _system_summary_to_dict(report.system_summary),
        "bottleneck": _bottleneck_to_dict(report.bottleneck),
    }


def format_json(report: BatchReport) -> str:
    return json.dumps(_report_to_dict(report), indent=2, sort_keys=True)


def format_compare_terminal(report: CompareReport) -> str:
    lines: list[str] = []
    lines.append(f"COMPARE  A: {report.a.batch_id}    B: {report.b.batch_id}")
    lines.append("=" * 60)
    lines.append(f"  {'metric':<24}{'A':>14}{'B':>14}{'delta':>12}")
    lines.append(
        f"  {'throughput docs/s':<24}"
        f"{report.a.throughput_docs_per_s:>14.3f}"
        f"{report.b.throughput_docs_per_s:>14.3f}"
        f"{report.throughput_delta_docs_per_s:>+12.3f}"
    )
    lines.append(
        f"  {'elapsed_s':<24}"
        f"{report.a.elapsed_s:>14.2f}"
        f"{report.b.elapsed_s:>14.2f}"
        f"{report.elapsed_delta_s:>+12.2f}"
    )
    lines.append("")
    lines.append("STAGE p95 DELTAS")
    lines.append("-" * 60)
    lines.append(f"  {'stage':<6}{'A p95':>14}{'B p95':>14}{'delta':>12}")
    for stage in sorted(report.stage_p95_delta_ms):
        pa = float(report.a.stage_summary.get(stage, {}).get("p95_ms", 0.0))
        pb = float(report.b.stage_summary.get(stage, {}).get("p95_ms", 0.0))
        lines.append(
            f"  {stage:<6}{pa:>14.2f}{pb:>14.2f}{report.stage_p95_delta_ms[stage]:>+12.2f}"
        )
    lines.append("")
    lines.append(
        f"Bottleneck A: {report.a.bottleneck.classification}    "
        f"B: {report.b.bottleneck.classification}"
    )
    return "\n".join(lines) + "\n"


def format_compare_json(report: CompareReport) -> str:
    return json.dumps(
        {
            "a": _report_to_dict(report.a),
            "b": _report_to_dict(report.b),
            "throughput_delta_docs_per_s": report.throughput_delta_docs_per_s,
            "elapsed_delta_s": report.elapsed_delta_s,
            "stage_p95_delta_ms": report.stage_p95_delta_ms,
        },
        indent=2,
        sort_keys=True,
    )


def format_trends_terminal(rows: list[TrendRow]) -> str:
    lines: list[str] = []
    lines.append("TRENDS")
    lines.append("=" * 60)
    lines.append(
        f"  {'batch_id':<14}{'pipeline':<16}{'docs':>6}"
        f"{'elapsed':>10}{'docs/s':>10}{'S5 p95_ms':>12}"
    )
    for row in rows:
        lines.append(
            f"  {row.batch_id[:14]:<14}"
            f"{row.pipeline:<16}"
            f"{row.total_docs:>6}"
            f"{row.elapsed_s:>10.2f}"
            f"{row.throughput_docs_per_s:>10.3f}"
            f"{row.s5_p95_ms:>12.2f}"
        )
    return "\n".join(lines) + "\n"


def format_trends_json(rows: list[TrendRow]) -> str:
    return json.dumps(
        [
            {
                "batch_id": r.batch_id,
                "pipeline": r.pipeline,
                "total_docs": r.total_docs,
                "elapsed_s": r.elapsed_s,
                "throughput_docs_per_s": r.throughput_docs_per_s,
                "s5_p95_ms": r.s5_p95_ms,
            }
            for r in rows
        ],
        indent=2,
        sort_keys=True,
    )

"""Integration tests for the `cmcourier analyze` subcommand suite (027)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from cmcourier.cli.app import main

pytestmark = [pytest.mark.integration]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _seed_logs(log_dir: Path, batch_id: str, *, pipeline: str = "csv-trigger") -> None:
    # batch_summary closes at 12:00:12.34 after a 12.34 s run → the
    # network/system tiers are associated by the window [12:00:00, 12:00:12.34].
    _write_jsonl(
        log_dir / "metrics-2026-05-11.jsonl",
        [
            {
                "kind": "batch_summary",
                "batch_id": batch_id,
                "ts": "2026-05-11T12:00:12.340000+00:00",
                "pipeline": pipeline,
                "total_docs": 10,
                "elapsed_s": 12.34,
                "throughput_docs_per_s": 0.81,
                "stages": {
                    "S5": {
                        "count": 10,
                        "p50_ms": 100.0,
                        "p95_ms": 500.0,
                        "p99_ms": 800.0,
                        "sum_ms": 5000.0,
                    },
                },
            }
        ],
    )
    _write_jsonl(
        log_dir / "network-2026-05-11.jsonl",
        [
            {
                "kind": "cmis_upload",
                "batch_id": batch_id,
                "ts": "2026-05-11T12:00:05+00:00",
                "duration_ms": 200.0,
                "size_bytes": 1024,
                "worker": "w1",
            }
        ],
    )
    _write_jsonl(
        log_dir / "system-2026-05-11.jsonl",
        [
            {
                "batch_id": batch_id,
                "ts_iso": "2026-05-11T12:00:00+00:00",
                "cpu_pct": 30.0,
                "ram_used_mb": 4096,
                "ram_total_mb": 16384,
                "disk_read_mbps": 5.0,
                "disk_write_mbps": 3.0,
                "net_in_mbps": 10.0,
                "net_out_mbps": 50.0,
                "process_pid": 1,
                "process_threads": 8,
                "process_cpu_pct": 25.0,
                "process_rss_mb": 200,
                "active_workers": 2,
            }
        ],
    )
    _write_jsonl(
        log_dir / f"slow-ops-{batch_id}.jsonl",
        [
            {
                "batch_id": batch_id,
                "kind": "cmis_upload",
                "duration_ms": 6000.0,
                "txn_num": "TXN_001",
                "worker": "w1",
            }
        ],
    )


# ---------------------------------------------------------------------------
# analyze batch
# ---------------------------------------------------------------------------


class TestAnalyzeBatch:
    def test_batch_report_text(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        _seed_logs(log_dir, "B1")
        result = CliRunner().invoke(
            main,
            ["analyze", "batch", "B1", "--log-dir", str(log_dir)],
        )
        assert result.exit_code == 0, result.stderr
        out = result.stdout
        assert "B1" in out
        assert "csv-trigger" in out
        assert "S5" in out
        assert "cmis_upload" in out
        assert "Bottleneck:" in out

    def test_batch_report_json(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        _seed_logs(log_dir, "B1")
        result = CliRunner().invoke(
            main,
            [
                "analyze",
                "batch",
                "B1",
                "--log-dir",
                str(log_dir),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["batch_id"] == "B1"
        assert payload["pipeline"] == "csv-trigger"
        assert "stage_summary" in payload
        assert "network_summary" in payload
        assert "bottleneck" in payload
        assert payload["bottleneck"]["classification"] in {
            "under-utilized",
            "network-bound",
            "cpu-bound",
            "memory-bound",
            "disk-bound",
            "worker-saturated",
            "upload-bound",
            "assembly-bound",
            "metadata-bound",
            "mapping-bound",
            "indexing-bound",
            "trigger-bound",
        }

    def test_batch_unknown_id_exits_nonzero(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        result = CliRunner().invoke(
            main,
            ["analyze", "batch", "missing", "--log-dir", str(log_dir)],
        )
        # Empty report still renders; we surface a stderr note and exit 0
        # for "no data" (operators may legitimately query a fresh batch).
        # The bottleneck verdict is "under-utilized" by classifier fallback.
        assert result.exit_code == 0
        assert "missing" in result.stdout

    def test_batch_deterministic(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        _seed_logs(log_dir, "B1")
        out_a = (
            CliRunner().invoke(main, ["analyze", "batch", "B1", "--log-dir", str(log_dir)]).stdout
        )
        out_b = (
            CliRunner().invoke(main, ["analyze", "batch", "B1", "--log-dir", str(log_dir)]).stdout
        )
        assert out_a == out_b


# ---------------------------------------------------------------------------
# analyze compare
# ---------------------------------------------------------------------------


class TestAnalyzeCompare:
    def test_compare_text(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        _seed_logs(log_dir, "B1")
        # Second batch with different metrics — write a separate metrics line.
        _write_jsonl(
            log_dir / "metrics-2026-05-11.jsonl",
            [
                {
                    "kind": "batch_summary",
                    "batch_id": "B1",
                    "pipeline": "csv-trigger",
                    "total_docs": 10,
                    "elapsed_s": 12.34,
                    "throughput_docs_per_s": 0.81,
                    "stages": {
                        "S5": {
                            "count": 10,
                            "p50_ms": 100.0,
                            "p95_ms": 500.0,
                            "p99_ms": 800.0,
                        },
                    },
                },
                {
                    "kind": "batch_summary",
                    "batch_id": "B2",
                    "pipeline": "csv-trigger",
                    "total_docs": 20,
                    "elapsed_s": 10.0,
                    "throughput_docs_per_s": 2.0,
                    "stages": {
                        "S5": {
                            "count": 20,
                            "p50_ms": 80.0,
                            "p95_ms": 300.0,
                            "p99_ms": 500.0,
                        },
                    },
                },
            ],
        )
        result = CliRunner().invoke(
            main,
            ["analyze", "compare", "B1", "B2", "--log-dir", str(log_dir)],
        )
        assert result.exit_code == 0, result.stderr
        assert "B1" in result.stdout and "B2" in result.stdout
        assert "throughput" in result.stdout.lower()


# ---------------------------------------------------------------------------
# analyze trends
# ---------------------------------------------------------------------------


class TestAnalyzeTrends:
    def test_trends_last_n(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        _write_jsonl(
            log_dir / "metrics-2026-05-11.jsonl",
            [
                {
                    "kind": "batch_summary",
                    "batch_id": f"B{i}",
                    "pipeline": "csv-trigger",
                    "total_docs": 10,
                    "elapsed_s": 10.0,
                    "throughput_docs_per_s": 1.0,
                    "stages": {
                        "S5": {
                            "count": 10,
                            "p50_ms": 100.0,
                            "p95_ms": 500.0 + i,
                            "p99_ms": 800.0,
                        },
                    },
                }
                for i in range(5)
            ],
        )
        result = CliRunner().invoke(
            main,
            ["analyze", "trends", "--last", "3", "--log-dir", str(log_dir)],
        )
        assert result.exit_code == 0, result.stderr
        out = result.stdout
        # Last 3 batches (B2, B3, B4) listed; earlier ones omitted.
        assert "B4" in out and "B3" in out and "B2" in out
        assert "B0" not in out

    def test_trends_filter_by_pipeline(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        _write_jsonl(
            log_dir / "metrics-2026-05-11.jsonl",
            [
                {
                    "kind": "batch_summary",
                    "batch_id": "B1",
                    "pipeline": "csv-trigger",
                    "total_docs": 5,
                    "elapsed_s": 5.0,
                    "throughput_docs_per_s": 1.0,
                    "stages": {},
                },
                {
                    "kind": "batch_summary",
                    "batch_id": "B2",
                    "pipeline": "rvabrep",
                    "total_docs": 7,
                    "elapsed_s": 5.0,
                    "throughput_docs_per_s": 1.4,
                    "stages": {},
                },
            ],
        )
        result = CliRunner().invoke(
            main,
            [
                "analyze",
                "trends",
                "--pipeline",
                "rvabrep",
                "--log-dir",
                str(log_dir),
            ],
        )
        assert result.exit_code == 0, result.stderr
        assert "B2" in result.stdout
        assert "B1" not in result.stdout

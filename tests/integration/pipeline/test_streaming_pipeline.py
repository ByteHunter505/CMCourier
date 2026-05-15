"""Integration tests for :class:`StreamingOrchestrator` (063).

End-to-end pipeline run through the real adapter graph
(Constitution Principle VI). CMIS HTTP is mocked via ``respx``.

The harness's ``build_pipeline`` factory wires the StagedPipeline; the
test then wraps it in a StreamingOrchestrator with a minimal config
that only fills the two slots the orchestrator reads
(``observability`` for the recorder, ``processing`` for bucket_size +
prep_workers).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import respx

from cmcourier.config.schema import (
    ObservabilityConfig,
    PipelineConfig,
    ProcessingConfig,
    StreamingConfig,
)
from cmcourier.orchestrators.staged import StagedPipeline
from cmcourier.orchestrators.streaming import StreamingOrchestrator

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _write_trigger_csv(tmp_path: Path, rows: list[tuple[str, str, str]]) -> Path:
    path = tmp_path / "triggers.csv"
    lines = ["ShortName,CIF,SystemID"]
    lines.extend(",".join(row) for row in rows)
    path.write_text("\n".join(lines) + "\n")
    return path


def _count_rows(db_path: Path, batch_id: str, status: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM migration_log WHERE batch_id = ? AND status = ?",
            (batch_id, status),
        ).fetchone()[0]
    finally:
        conn.close()


def _build_orchestrator(
    pipeline: StagedPipeline,
    tmp_path: Path,
    *,
    bucket_size: int,
    prep_workers: int,
) -> StreamingOrchestrator:
    cfg = MagicMock(spec=PipelineConfig)
    cfg.observability = ObservabilityConfig(log_dir=tmp_path)
    cfg.processing = ProcessingConfig(
        mode="streaming",
        streaming=StreamingConfig(bucket_size=bucket_size),
        prep_workers=prep_workers,
    )
    return StreamingOrchestrator(pipeline=pipeline, config=cfg, log_dir=tmp_path)


class TestStreamingFreshRun:
    @respx.mock
    def test_uploads_all_docs(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001", "TXN_PIPE_002"])
        triggers = _write_trigger_csv(
            tmp_path,
            [("TESTCLIENT01", "123456", "1"), ("TESTCLIENT02", "234567", "1")],
        )
        pipeline = pipeline_harness.build_pipeline(triggers)
        orch = _build_orchestrator(pipeline, tmp_path, bucket_size=4, prep_workers=2)
        report = orch.run(
            source_descriptor=str(triggers),
            batch_size=10,
            batches_in_flight=2,
        )
        assert len(report.chunks) == 1
        run = report.chunks[0]
        assert run.s5_done == 2
        assert run.s5_failed == 0
        assert run.total_docs == 2
        pipeline_harness.tracking_store.flush()
        assert _count_rows(pipeline_harness.db_path, run.batch_id, "S5_DONE") == 2

    @respx.mock
    def test_bucket_caps_memory(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        # Two real triggers; bucket_size=1. With single-doc bucket and
        # the synchronous prep/upload loop, peak qsize cannot exceed 1.
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001", "TXN_PIPE_002"])
        triggers = _write_trigger_csv(
            tmp_path,
            [("TESTCLIENT01", "123456", "1"), ("TESTCLIENT02", "234567", "1")],
        )
        pipeline = pipeline_harness.build_pipeline(triggers)
        orch = _build_orchestrator(pipeline, tmp_path, bucket_size=1, prep_workers=2)
        orch.run(
            source_descriptor=str(triggers),
            batch_size=10,
            batches_in_flight=2,
        )
        assert orch.peak_qsize <= 1


class TestStreamingResumeRejection:
    @respx.mock
    def test_rejects_from_stage_gt_one(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        pipeline = pipeline_harness.build_pipeline(triggers)
        orch = _build_orchestrator(pipeline, tmp_path, bucket_size=2, prep_workers=1)
        with pytest.raises(ValueError, match="from-stage"):
            orch.run(
                source_descriptor=str(triggers),
                batch_size=10,
                batches_in_flight=2,
                from_stage=3,
            )

    @respx.mock
    def test_rejects_explicit_batch_id(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        pipeline = pipeline_harness.build_pipeline(triggers)
        orch = _build_orchestrator(pipeline, tmp_path, bucket_size=2, prep_workers=1)
        with pytest.raises(ValueError, match="batch-id"):
            orch.run(
                source_descriptor=str(triggers),
                batch_size=10,
                batches_in_flight=2,
                resume_batch_id="B-X",
            )


class TestStreamingCrossBatchIdempotency:
    @respx.mock
    def test_second_run_emits_s1_skipped_rows(self, pipeline_harness, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        # First run: upload one doc successfully under streaming mode.
        pipeline_harness.register_cmis_for_docs(["TXN_PIPE_001"])
        triggers = _write_trigger_csv(tmp_path, [("TESTCLIENT01", "123456", "1")])
        pipeline = pipeline_harness.build_pipeline(triggers)
        orch = _build_orchestrator(pipeline, tmp_path, bucket_size=2, prep_workers=1)
        first = orch.run(
            source_descriptor=str(triggers),
            batch_size=10,
            batches_in_flight=2,
        )
        assert first.chunks[0].s5_done == 1
        pipeline_harness.tracking_store.flush()

        # Second streaming run, fresh batch. No CMIS stubs reset — if the
        # orchestrator tried to re-upload it would hit a 404 from respx.
        # 062: every cross-batch-skip should land as an S1_SKIPPED row in
        # the new batch.
        pipeline2 = pipeline_harness.build_pipeline(triggers)
        orch2 = _build_orchestrator(pipeline2, tmp_path, bucket_size=2, prep_workers=1)
        second = orch2.run(
            source_descriptor=str(triggers),
            batch_size=10,
            batches_in_flight=2,
        )
        second_run = second.chunks[0]
        assert second_run.s5_done == 0
        assert second_run.s1_skipped_cross_batch == 1
        pipeline_harness.tracking_store.flush()
        assert _count_rows(pipeline_harness.db_path, second_run.batch_id, "S1_SKIPPED") == 1

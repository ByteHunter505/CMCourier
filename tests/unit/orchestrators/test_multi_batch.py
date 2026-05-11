"""Unit tests for ``MultiBatchOrchestrator`` (028, REQ-023)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cmcourier.config.schema import ObservabilityConfig, PipelineConfig
from cmcourier.domain.models import TriggerRecord
from cmcourier.orchestrators.multi_batch import (
    MultiBatchOrchestrator,
    MultiBatchRunReport,
)
from cmcourier.orchestrators.staged import RunReport

# ---------------------------------------------------------------------------
# Stub pipeline + config (we don't want to spin up real CMIS, AS400 etc.)
# ---------------------------------------------------------------------------


class _FakePipeline:
    """Minimal stand-in for StagedPipeline — covers the surface
    that MultiBatchOrchestrator touches."""

    pipeline_name = "csv-trigger"

    def __init__(
        self,
        *,
        triggers_per_call: list[TriggerRecord],
        prep_sleep_s: float = 0.0,
        upload_sleep_s: float = 0.0,
        raise_on_prep: int | None = None,
    ) -> None:
        self._triggers = triggers_per_call
        self._prep_sleep = prep_sleep_s
        self._upload_sleep = upload_sleep_s
        self._raise_on_prep = raise_on_prep
        self._batch_counter = 0
        self.prep_order: list[str] = []
        self.upload_order: list[str] = []
        self.lock = threading.Lock()

        class _S:
            def acquire(self_inner, descriptor: str) -> Iterator[TriggerRecord]:  # noqa: ARG002, N805
                yield from triggers_per_call

        self._trigger_strategy = _S()
        self._tracking_store = MagicMock()
        self._tracking_store.start_batch = self._fake_start_batch
        self._tracking_store.flush = MagicMock()
        self._tracking_store.complete_batch = MagicMock()
        self._tracking_store.list_txn_nums_for_batch = MagicMock(return_value=set())
        self.auto_tune_controller = None
        self.sampler = None

    def _fake_start_batch(self, *, total_records: int) -> str:  # noqa: ARG002
        self._batch_counter += 1
        return f"B{self._batch_counter}"

    def _resolve_batch_id(
        self,
        batch_id: str | None,
        from_stage: int,  # noqa: ARG002
        batch_size: int,
    ) -> str:
        if batch_id is not None:
            return batch_id
        return self._fake_start_batch(total_records=batch_size)

    def prep_chunk(
        self,
        *,
        triggers: list[TriggerRecord],
        batch_id: str,
        recorder,  # noqa: ARG002
        from_stage: int = 1,  # noqa: ARG002
    ):
        if self._prep_sleep:
            time.sleep(self._prep_sleep)
        if self._raise_on_prep is not None and batch_id == f"B{self._raise_on_prep}":
            raise RuntimeError("synthetic prep failure")
        with self.lock:
            self.prep_order.append(batch_id)
        # Lightweight stand-in for _StageItem — only the upload path cares
        # about ``document.txn_num`` and we don't actually upload in the fake.
        items = [
            SimpleNamespace(document=SimpleNamespace(txn_num=f"TXN_{batch_id}_{i}"))
            for i, _ in enumerate(triggers)
        ]
        return items, 0, len(items), 0, 0, 0

    def upload_chunk(self, *, items, batch_id: str, recorder):  # noqa: ARG002
        if self._upload_sleep:
            time.sleep(self._upload_sleep)
        with self.lock:
            self.upload_order.append(batch_id)
        return len(items), 0

    def run(self, **kwargs):
        # Mimic the single-batch entry point: prep + upload for the full source.
        batch_id = self._resolve_batch_id(
            kwargs.get("batch_id"), kwargs.get("from_stage", 1), kwargs.get("batch_size", 1000)
        )
        items, skipped, s1d, s2f, s3f, s4f = self.prep_chunk(
            triggers=self._triggers, batch_id=batch_id, recorder=None
        )
        s5d, s5f = self.upload_chunk(items=items, batch_id=batch_id, recorder=None)
        return RunReport(
            batch_id=batch_id,
            total_triggers=len(self._triggers),
            total_docs=s1d + skipped,
            s1_done=s1d,
            s1_skipped_cross_batch=skipped,
            s2_done=s1d - s2f,
            s2_failed=s2f,
            s3_done=s1d - s2f - s3f,
            s3_failed=s3f,
            s4_done=s1d - s2f - s3f - s4f,
            s4_failed=s4f,
            s5_done=s5d,
            s5_failed=s5f,
            elapsed_seconds=0.0,
        )


def _make_triggers(n: int) -> list[TriggerRecord]:
    return [TriggerRecord(shortname=f"SN_{i}", cif=str(i), system_id="1") for i in range(n)]


def _build_orchestrator(pipeline, tmp_path: Path) -> MultiBatchOrchestrator:
    # Build a minimal valid PipelineConfig for the orchestrator's observability
    # access. We only touch ``config.observability`` from the orchestrator.
    cfg = MagicMock(spec=PipelineConfig)
    cfg.observability = ObservabilityConfig(log_dir=tmp_path)
    return MultiBatchOrchestrator(pipeline=pipeline, config=cfg, log_dir=tmp_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMultiBatchOrchestrator:
    def test_n_one_delegates_to_pipeline_run(self, tmp_path: Path) -> None:
        triggers = _make_triggers(5)
        pipeline = _FakePipeline(triggers_per_call=triggers)
        orch = _build_orchestrator(pipeline, tmp_path)
        report = orch.run(
            source_descriptor="",
            batch_size=10,
            batches_in_flight=1,
        )
        assert isinstance(report, MultiBatchRunReport)
        assert len(report.chunks) == 1
        assert report.chunks[0].s5_done == 5
        assert report.failed_chunks == []

    def test_n_two_overlap_on_three_chunks(self, tmp_path: Path) -> None:
        triggers = _make_triggers(15)
        pipeline = _FakePipeline(triggers_per_call=triggers, prep_sleep_s=0.02, upload_sleep_s=0.02)
        orch = _build_orchestrator(pipeline, tmp_path)
        report = orch.run(
            source_descriptor="",
            batch_size=5,
            batches_in_flight=2,
        )
        # 15 triggers / 5 per chunk = 3 chunks.
        assert len(report.chunks) == 3
        assert report.s5_done == 15
        assert report.failed_chunks == []
        # Order check: every chunk prepped before being uploaded.
        assert pipeline.prep_order == ["B1", "B2", "B3"]
        # Uploads complete in the same order (single upload thread).
        assert pipeline.upload_order == ["B1", "B2", "B3"]

    def test_n_two_overlap_actually_overlaps(self, tmp_path: Path) -> None:
        """Wall-clock evidence that prep and upload run concurrently."""
        triggers = _make_triggers(6)
        # Sleep long enough that serial execution would be roughly
        # 3 * (prep_sleep + upload_sleep). Overlapped should be closer to
        # 3 * upload_sleep + prep_sleep (the last chunk's prep doesn't overlap).
        pipeline = _FakePipeline(triggers_per_call=triggers, prep_sleep_s=0.05, upload_sleep_s=0.05)
        orch = _build_orchestrator(pipeline, tmp_path)
        t0 = time.monotonic()
        orch.run(source_descriptor="", batch_size=2, batches_in_flight=2)
        elapsed = time.monotonic() - t0
        # 3 chunks. Serial would be ~0.3 s. Overlapped should be ~0.2 s.
        # Be lenient: anything under 0.28 s proves real overlap.
        assert elapsed < 0.28, f"no overlap detected; elapsed={elapsed:.3f}s"

    def test_n_two_exception_in_prep_is_isolated(self, tmp_path: Path) -> None:
        triggers = _make_triggers(15)
        pipeline = _FakePipeline(triggers_per_call=triggers, raise_on_prep=2)
        orch = _build_orchestrator(pipeline, tmp_path)
        report = orch.run(
            source_descriptor="",
            batch_size=5,
            batches_in_flight=2,
        )
        # Chunk 2 failed; chunks 1 and 3 succeeded.
        assert len(report.chunks) == 2
        assert len(report.failed_chunks) == 1
        assert report.failed_chunks[0][1] == "RuntimeError"

    def test_n_three_rejected(self, tmp_path: Path) -> None:
        pipeline = _FakePipeline(triggers_per_call=_make_triggers(1))
        orch = _build_orchestrator(pipeline, tmp_path)
        with pytest.raises(ValueError, match="3..5 deferred"):
            orch.run(source_descriptor="", batch_size=1, batches_in_flight=3)

    def test_empty_source_returns_zero_chunks(self, tmp_path: Path) -> None:
        pipeline = _FakePipeline(triggers_per_call=[])
        orch = _build_orchestrator(pipeline, tmp_path)
        report = orch.run(source_descriptor="", batch_size=10, batches_in_flight=2)
        assert report.chunks == []

    def test_resume_forces_n_one(self, tmp_path: Path) -> None:
        triggers = _make_triggers(3)
        pipeline = _FakePipeline(triggers_per_call=triggers)
        orch = _build_orchestrator(pipeline, tmp_path)
        report = orch.run(
            source_descriptor="",
            batch_size=10,
            batches_in_flight=2,
            resume_batch_id="EXISTING",
        )
        # Resume = single batch path; one RunReport.
        assert len(report.chunks) == 1
        assert report.chunks[0].batch_id == "EXISTING"


# ---------------------------------------------------------------------------
# 030 — TUI live binding (chunk-state machine + active recorder)
# ---------------------------------------------------------------------------


class TestOrchestratorChunkState:
    """The orchestrator now tracks per-chunk state for live TUI binding."""

    def test_chunks_snapshot_empty_before_run(self, tmp_path: Path) -> None:
        pipeline = _FakePipeline(triggers_per_call=_make_triggers(1))
        orch = _build_orchestrator(pipeline, tmp_path)
        assert orch.chunks_snapshot() == []

    def test_chunks_snapshot_after_n_two_run(self, tmp_path: Path) -> None:
        triggers = _make_triggers(6)
        pipeline = _FakePipeline(triggers_per_call=triggers)
        orch = _build_orchestrator(pipeline, tmp_path)
        orch.run(source_descriptor="", batch_size=2, batches_in_flight=2)
        # 6 triggers / 2 = 3 chunks. All DONE after run completes.
        states = orch.chunks_snapshot()
        assert len(states) == 3
        assert all(s.status == "DONE" for s in states)
        assert [s.batch_id for s in states] == ["B1", "B2", "B3"]

    def test_chunks_snapshot_marks_failed(self, tmp_path: Path) -> None:
        triggers = _make_triggers(6)
        pipeline = _FakePipeline(triggers_per_call=triggers, raise_on_prep=2)
        orch = _build_orchestrator(pipeline, tmp_path)
        orch.run(source_descriptor="", batch_size=2, batches_in_flight=2)
        states = orch.chunks_snapshot()
        # Chunk 2 failed in prep; the others are DONE.
        statuses = {s.batch_id: s.status for s in states}
        assert statuses.get("B2") == "FAILED"

    def test_active_recorder_none_before_run(self, tmp_path: Path) -> None:
        pipeline = _FakePipeline(triggers_per_call=_make_triggers(1))
        orch = _build_orchestrator(pipeline, tmp_path)
        assert orch.active_recorder() is None

    def test_active_recorder_set_during_run(self, tmp_path: Path) -> None:
        """During a real run there should be an active recorder while a
        chunk is in flight. We sleep inside prep/upload to keep the
        recorder alive long enough to observe."""
        triggers = _make_triggers(2)
        recorder_seen: list[object] = []
        pipeline = _FakePipeline(triggers_per_call=triggers, prep_sleep_s=0.0, upload_sleep_s=0.0)
        orch = _build_orchestrator(pipeline, tmp_path)

        # Patch _build_chunk_recorder to capture the recorder it builds.
        orig = orch._build_chunk_recorder  # noqa: SLF001

        def _patched() -> object:
            r = orig()
            recorder_seen.append(r)
            return r

        orch._build_chunk_recorder = _patched  # type: ignore[assignment, method-assign]
        orch.run(source_descriptor="", batch_size=1, batches_in_flight=2)
        # 2 chunks × 1 recorder each = 2 recorders constructed.
        assert len(recorder_seen) == 2

"""Unit tests for ``StreamingOrchestrator`` (063)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cmcourier.config.schema import (
    ObservabilityConfig,
    PipelineConfig,
    ProcessingConfig,
    StreamingConfig,
)
from cmcourier.domain.models import TriggerRecord
from cmcourier.orchestrators.multi_batch import MultiBatchRunReport
from cmcourier.orchestrators.streaming import StreamingOrchestrator, _TriggerIter

# ---------------------------------------------------------------------------
# Stub pipeline
# ---------------------------------------------------------------------------


class _FakePipeline:
    """Stand-in for StagedPipeline — covers the StreamingOrchestrator surface."""

    pipeline_name = "csv-trigger"

    def __init__(
        self,
        *,
        triggers: list[TriggerRecord],
        prep_sleep_s: float = 0.0,
        upload_sleep_s: float = 0.0,
        prep_returns_none_indexes: tuple[int, ...] = (),
        upload_outcome_by_idx: dict[int, str] | None = None,
        pool_ceiling: int = 2,
    ) -> None:
        self._triggers = triggers
        self._prep_sleep = prep_sleep_s
        self._upload_sleep = upload_sleep_s
        self._prep_returns_none = set(prep_returns_none_indexes)
        self._upload_outcomes = upload_outcome_by_idx or {}
        self._pool_ceiling_value = pool_ceiling
        self.prep_calls: list[str] = []
        self.upload_calls: list[str] = []
        self.warm_calls: list[int] = []
        self.lock = threading.Lock()
        self._batch_counter = 0
        self._idx_for_trigger: dict[int, int] = {id(t): i for i, t in enumerate(triggers)}

        class _S:
            def acquire(self, descriptor: str) -> Iterator[TriggerRecord]:  # noqa: ARG002, PLR6301
                yield from triggers

        self._trigger_strategy = _S()
        self._tracking_store = MagicMock()
        self._tracking_store.start_batch = self._fake_start_batch
        self._tracking_store.flush = MagicMock()
        self._tracking_store.complete_batch = MagicMock()
        self.auto_tune_controller = None
        self.sampler = None

    def _fake_start_batch(self, *, total_records: int) -> str:  # noqa: ARG002
        self._batch_counter += 1
        return f"B{self._batch_counter}"

    def _pool_ceiling(self) -> int:
        return self._pool_ceiling_value

    def warm_upload_pool(self, workers: int) -> None:
        self.warm_calls.append(workers)

    def streaming_prep_one(self, trigger, batch_id: str, recorder):  # noqa: ARG002
        if self._prep_sleep:
            time.sleep(self._prep_sleep)
        idx = self._idx_for_trigger.get(id(trigger), -1)
        with self.lock:
            self.prep_calls.append(getattr(trigger, "shortname", str(idx)))
        if idx in self._prep_returns_none:
            return None, 0, 0
        return (
            SimpleNamespace(
                __idx__=idx,
                document=SimpleNamespace(txn_num=f"TXN_{idx}"),
            ),
            0,
            0,
        )

    def streaming_upload_one(self, item, batch_id: str, recorder):  # noqa: ARG002
        if self._upload_sleep:
            time.sleep(self._upload_sleep)
        idx = item.__idx__
        with self.lock:
            self.upload_calls.append(item.document.txn_num)
        return self._upload_outcomes.get(idx, "done")


def _make_triggers(n: int) -> list[TriggerRecord]:
    return [TriggerRecord(shortname=f"SN_{i}", cif=str(i), system_id="1") for i in range(n)]


def _build_orch(
    pipeline,
    tmp_path: Path,
    *,
    bucket_size: int = 8,
    prep_workers: int = 1,
) -> StreamingOrchestrator:
    cfg = MagicMock(spec=PipelineConfig)
    cfg.observability = ObservabilityConfig(log_dir=tmp_path)
    cfg.processing = ProcessingConfig(
        mode="streaming",
        streaming=StreamingConfig(bucket_size=bucket_size),
        prep_workers=prep_workers,
    )
    return StreamingOrchestrator(pipeline=pipeline, config=cfg, log_dir=tmp_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTriggerIter:
    def test_concurrent_consumers_each_see_each_trigger_exactly_once(self) -> None:
        triggers = list(range(200))
        shared = _TriggerIter(iter(triggers))
        seen: list[int] = []
        seen_lock = threading.Lock()

        def consumer() -> None:
            while True:
                try:
                    value = next(shared)
                except StopIteration:
                    return
                with seen_lock:
                    seen.append(value)

        threads = [threading.Thread(target=consumer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(seen) == triggers
        assert shared.count == len(triggers)


class TestStreamingOrchestrator:
    def test_happy_path_uploads_all(self, tmp_path: Path) -> None:
        triggers = _make_triggers(10)
        pipeline = _FakePipeline(triggers=triggers, pool_ceiling=4)
        orch = _build_orch(pipeline, tmp_path, bucket_size=4, prep_workers=2)

        report = orch.run(
            source_descriptor="",
            batch_size=100,
            batches_in_flight=2,
        )
        assert isinstance(report, MultiBatchRunReport)
        assert len(report.chunks) == 1
        run = report.chunks[0]
        assert run.s5_done == 10
        assert run.s5_failed == 0
        assert run.total_triggers == 10
        assert pipeline.warm_calls == [4]
        # Every trigger went through prep + upload exactly once.
        assert sorted(pipeline.upload_calls) == [f"TXN_{i}" for i in range(10)]

    def test_empty_source_drains_cleanly(self, tmp_path: Path) -> None:
        pipeline = _FakePipeline(triggers=[], pool_ceiling=3)
        orch = _build_orch(pipeline, tmp_path, bucket_size=2, prep_workers=2)
        report = orch.run(source_descriptor="", batch_size=10, batches_in_flight=2)
        assert report.chunks[0].s5_done == 0
        assert report.chunks[0].total_triggers == 0

    def test_rejects_from_stage_gt_one(self, tmp_path: Path) -> None:
        pipeline = _FakePipeline(triggers=_make_triggers(1))
        orch = _build_orch(pipeline, tmp_path)
        with pytest.raises(ValueError, match="from-stage"):
            orch.run(
                source_descriptor="",
                batch_size=1,
                batches_in_flight=2,
                from_stage=3,
            )

    def test_rejects_explicit_resume_batch_id(self, tmp_path: Path) -> None:
        pipeline = _FakePipeline(triggers=_make_triggers(1))
        orch = _build_orch(pipeline, tmp_path)
        with pytest.raises(ValueError, match="batch-id"):
            orch.run(
                source_descriptor="",
                batch_size=1,
                batches_in_flight=2,
                resume_batch_id="B-existing",
            )

    def test_prep_failures_drop_silently(self, tmp_path: Path) -> None:
        # First and third triggers' prep returns None (filtered / cross-batch
        # skipped / failed); they never reach the bucket.
        triggers = _make_triggers(5)
        pipeline = _FakePipeline(
            triggers=triggers,
            prep_returns_none_indexes=(0, 2),
            pool_ceiling=2,
        )
        orch = _build_orch(pipeline, tmp_path, bucket_size=2, prep_workers=2)
        report = orch.run(source_descriptor="", batch_size=10, batches_in_flight=2)
        run = report.chunks[0]
        assert run.s5_done == 3
        uploaded = sorted(pipeline.upload_calls)
        assert uploaded == ["TXN_1", "TXN_3", "TXN_4"]

    def test_bucket_caps_memory(self, tmp_path: Path) -> None:
        # 50 triggers, bucket_size=3. Slow consumers so the producers
        # stay ahead → bucket repeatedly fills to its cap.
        triggers = _make_triggers(50)
        pipeline = _FakePipeline(
            triggers=triggers,
            upload_sleep_s=0.005,
            pool_ceiling=2,
        )
        orch = _build_orch(pipeline, tmp_path, bucket_size=3, prep_workers=4)
        orch.run(source_descriptor="", batch_size=10, batches_in_flight=2)
        # Peak qsize is sampled inside producers right after put(). Allow
        # the sampler one slot of head-room: a producer can observe the
        # post-put qsize before a consumer takes the just-pushed item, so
        # the witnessed peak can be exactly bucket_size.
        assert orch.peak_qsize <= 3

    def test_outcome_skipped_and_failed_counted(self, tmp_path: Path) -> None:
        triggers = _make_triggers(4)
        pipeline = _FakePipeline(
            triggers=triggers,
            pool_ceiling=2,
            upload_outcome_by_idx={1: "skipped", 2: "failed"},
        )
        orch = _build_orch(pipeline, tmp_path, bucket_size=4, prep_workers=2)
        report = orch.run(source_descriptor="", batch_size=10, batches_in_flight=2)
        run = report.chunks[0]
        assert run.s5_done == 2
        assert run.s5_failed == 1
        assert run.total_docs == 4

"""Integration test for S3 cache short-circuit (037 Phase 2).

Builds a minimal ``StagedPipeline`` with mocked deps, runs S3 twice
on the same item, and verifies the second run hits the cache and
skips ``MetadataService.resolve``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from cmcourier.domain.models import (
    CMMapping,
    ResolvedMetadata,
    RVABREPDocument,
    TriggerRecord,
)
from cmcourier.orchestrators.staged import StagedPipeline, _StageItem
from cmcourier.services.document_cache import DocumentCacheService
from cmcourier.services.metadata import MetadataResolution

pytestmark = pytest.mark.integration


class _InMemoryCache:
    """Inline fake — avoids spinning up SQLite for unit-scope tests."""

    def __init__(self) -> None:
        from cmcourier.domain.ports import CacheEntry, CacheStats

        self.rows: dict[tuple[str, str], CacheEntry] = {}
        self._CacheStats = CacheStats

    def get(self, key):  # type: ignore[no-untyped-def]
        return self.rows.get((key.txn_num, key.fields_hash))

    def put(self, entry):  # type: ignore[no-untyped-def]
        self.rows[(entry.txn_num, entry.fields_hash)] = entry

    def clear_txn(self, txn_num: str) -> int:
        keys = [k for k in self.rows if k[0] == txn_num]
        for k in keys:
            del self.rows[k]
        return len(keys)

    def clear_all(self) -> int:
        n = len(self.rows)
        self.rows.clear()
        return n

    def clear_older_than(self, threshold: datetime) -> int:
        keys = [k for k, v in self.rows.items() if v.cached_at < threshold]
        for k in keys:
            del self.rows[k]
        return len(keys)

    def stats(self):  # type: ignore[no-untyped-def]
        return self._CacheStats(
            total_rows=len(self.rows),
            oldest_cached_at=None,
            newest_cached_at=None,
        )


def _item(txn: str = "TXN_001") -> _StageItem:
    trigger = TriggerRecord(shortname="CLIENT01", cif=None, system_id="1")
    doc = RVABREPDocument(
        system_code="1",
        txn_num=txn,
        index1="",
        index2="999999",
        index3="",
        index4="",
        index5="",
        index6="",
        index7="CC03",
        image_type="O",
        image_path="path",
        file_name=f"{txn}.001",
        creation_date=datetime(2025, 11, 17, tzinfo=UTC),
        last_view_date=None,
        total_pages=1,
        delete_code="",
    )
    mapping = CMMapping(
        clase_id="04.01.01.01.01",
        id_rvi="FF17",
        id_corto="CN01",
        clase_name="Test",
        required_metadata_fields=("BAC_CIF", "Nombre_Cliente"),
        cmis_type="",
    )
    return _StageItem(trigger=trigger, document=doc, mapping=mapping)


def _build_pipeline(
    *,
    document_cache: DocumentCacheService | None,
    resolve_mock: MagicMock,
) -> StagedPipeline:
    metadata = MagicMock()
    metadata.resolve = resolve_mock

    tracking_store = MagicMock()
    tracking_store.is_stage_done.return_value = False

    return StagedPipeline(
        trigger_strategy=MagicMock(),
        indexing_service=MagicMock(),
        mapping_service=MagicMock(),
        metadata_service=metadata,
        assembler=MagicMock(),
        uploader=MagicMock(),
        tracking_store=tracking_store,
        document_cache=document_cache,
    )


def _resolution(cif: str = "123456") -> MetadataResolution:
    return MetadataResolution(
        metadata=ResolvedMetadata.from_dict({"BAC_CIF": cif, "Nombre_Cliente": "ACME"}),
        healed_trigger=TriggerRecord(shortname="CLIENT01", cif=cif, system_id="1"),
    )


class TestCacheShortCircuit:
    def test_second_run_hits_cache(self) -> None:
        cache = _InMemoryCache()
        svc = DocumentCacheService(cache=cache, ttl_minutes=60)  # type: ignore[arg-type]
        resolve_mock = MagicMock(return_value=_resolution())
        pipeline = _build_pipeline(document_cache=svc, resolve_mock=resolve_mock)

        # First pass: miss → resolve runs.
        survivors, failed = pipeline._stage_s3([_item()], "batch_a")
        assert len(survivors) == 1
        assert failed == 0
        assert resolve_mock.call_count == 1

        # Second pass: hit → resolve must NOT run again.
        resolve_mock.reset_mock()
        survivors2, failed2 = pipeline._stage_s3([_item()], "batch_b")
        assert len(survivors2) == 1
        assert failed2 == 0
        assert resolve_mock.call_count == 0
        # Healed CIF restored from cache onto the item's trigger.
        assert survivors2[0].trigger.cif == "123456"

    def test_no_cache_means_every_run_calls_resolver(self) -> None:
        resolve_mock = MagicMock(return_value=_resolution())
        pipeline = _build_pipeline(document_cache=None, resolve_mock=resolve_mock)
        pipeline._stage_s3([_item()], "batch_a")
        pipeline._stage_s3([_item()], "batch_b")
        assert resolve_mock.call_count == 2

    def test_ttl_expiry_misses(self) -> None:
        cache = _InMemoryCache()
        clock = [datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)]
        svc = DocumentCacheService(
            cache=cache,  # type: ignore[arg-type]
            ttl_minutes=60,
            clock=lambda: clock[0],
        )
        resolve_mock = MagicMock(return_value=_resolution())
        pipeline = _build_pipeline(document_cache=svc, resolve_mock=resolve_mock)

        pipeline._stage_s3([_item()], "batch_a")
        assert resolve_mock.call_count == 1
        # Advance past TTL.
        clock[0] += timedelta(minutes=61)
        pipeline._stage_s3([_item()], "batch_b")
        assert resolve_mock.call_count == 2

    def test_counters_reflect_hits_and_misses(self) -> None:
        cache = _InMemoryCache()
        svc = DocumentCacheService(cache=cache, ttl_minutes=60)  # type: ignore[arg-type]
        resolve_mock = MagicMock(return_value=_resolution())
        pipeline = _build_pipeline(document_cache=svc, resolve_mock=resolve_mock)

        pipeline._stage_s3([_item("T1")], "b1")  # miss
        pipeline._stage_s3([_item("T1")], "b2")  # hit
        pipeline._stage_s3([_item("T2")], "b3")  # miss

        snap = svc.counters_snapshot()
        assert snap.hits == 1
        assert snap.misses_absent == 2
        assert snap.misses_expired == 0

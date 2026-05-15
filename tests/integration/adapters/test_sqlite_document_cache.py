"""Tests de integración para :class:`SqliteDocumentCache` (037 Fase 1).

Usa un archivo SQLite real bajo ``tmp_path``. La cache y el `tracking store`
comparten base de datos, así que cada test abre primero un
``SQLiteTrackingStore`` para bootstrapear el schema y después ejercita el
adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import pytest

from cmcourier.adapters.tracking import SqliteDocumentCache, SQLiteTrackingStore
from cmcourier.domain.ports import CacheEntry, CacheKey

pytestmark = pytest.mark.integration


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "tracking.db"
    store = SQLiteTrackingStore(p)
    try:
        # Solo con tocar el store ya se asegura que el schema
        # (incluido document_cache) quede creado.
        store.flush()
    finally:
        store.close()
    return p


@pytest.fixture
def cache(db_path: Path) -> SqliteDocumentCache:
    return SqliteDocumentCache(db_path)


def _entry(
    txn: str = "TXN_0000001",
    fields_hash: str = "abc123",
    cif: str | None = "123456",
    cached_at: datetime | None = None,
    properties: dict[str, str] | None = None,
) -> CacheEntry:
    return CacheEntry(
        txn_num=txn,
        fields_hash=fields_hash,
        trigger_cif=cif,
        properties=MappingProxyType(properties or {"BAC_CIF": "123456", "Nombre_Cliente": "ACME"}),
        cached_at=cached_at or datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC),
    )


class TestPutGet:
    def test_put_then_get_round_trips(self, cache: SqliteDocumentCache) -> None:
        entry = _entry()
        cache.put(entry)
        got = cache.get(CacheKey(txn_num=entry.txn_num, fields_hash=entry.fields_hash))
        assert got is not None
        assert got.txn_num == entry.txn_num
        assert got.fields_hash == entry.fields_hash
        assert got.trigger_cif == entry.trigger_cif
        assert dict(got.properties) == dict(entry.properties)
        assert got.cached_at == entry.cached_at

    def test_get_miss_returns_none(self, cache: SqliteDocumentCache) -> None:
        assert cache.get(CacheKey(txn_num="missing", fields_hash="abc")) is None

    def test_put_upserts_same_key(self, cache: SqliteDocumentCache) -> None:
        first = _entry(cached_at=datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC))
        cache.put(first)
        second = _entry(
            cached_at=datetime(2026, 5, 11, 11, 0, 0, tzinfo=UTC),
            properties={"BAC_CIF": "999"},
        )
        cache.put(second)
        got = cache.get(CacheKey(txn_num=first.txn_num, fields_hash=first.fields_hash))
        assert got is not None
        assert got.cached_at == datetime(2026, 5, 11, 11, 0, 0, tzinfo=UTC)
        assert dict(got.properties) == {"BAC_CIF": "999"}

    def test_different_fields_hash_is_independent_row(self, cache: SqliteDocumentCache) -> None:
        e1 = _entry(fields_hash="hash_a")
        e2 = _entry(fields_hash="hash_b", properties={"X": "y"})
        cache.put(e1)
        cache.put(e2)
        assert cache.get(CacheKey(e1.txn_num, "hash_a")) is not None
        assert cache.get(CacheKey(e2.txn_num, "hash_b")) is not None


class TestClear:
    def test_clear_txn_removes_all_rows_for_that_txn(self, cache: SqliteDocumentCache) -> None:
        cache.put(_entry(txn="t1", fields_hash="a"))
        cache.put(_entry(txn="t1", fields_hash="b"))
        cache.put(_entry(txn="t2", fields_hash="a"))
        assert cache.clear_txn("t1") == 2
        assert cache.get(CacheKey("t1", "a")) is None
        assert cache.get(CacheKey("t1", "b")) is None
        assert cache.get(CacheKey("t2", "a")) is not None

    def test_clear_all_truncates(self, cache: SqliteDocumentCache) -> None:
        cache.put(_entry(txn="t1"))
        cache.put(_entry(txn="t2"))
        cache.put(_entry(txn="t3"))
        assert cache.clear_all() == 3
        assert cache.stats().total_rows == 0

    def test_clear_older_than_only_old_rows(self, cache: SqliteDocumentCache) -> None:
        old = _entry(txn="old", cached_at=datetime(2026, 5, 10, tzinfo=UTC))
        fresh = _entry(txn="fresh", cached_at=datetime(2026, 5, 11, 12, 0, tzinfo=UTC))
        cache.put(old)
        cache.put(fresh)
        threshold = datetime(2026, 5, 11, tzinfo=UTC)
        assert cache.clear_older_than(threshold) == 1
        assert cache.get(CacheKey("old", "abc123")) is None
        assert cache.get(CacheKey("fresh", "abc123")) is not None


class TestStats:
    def test_stats_empty_table(self, cache: SqliteDocumentCache) -> None:
        stats = cache.stats()
        assert stats.total_rows == 0
        assert stats.oldest_cached_at is None
        assert stats.newest_cached_at is None

    def test_stats_after_puts(self, cache: SqliteDocumentCache) -> None:
        t0 = datetime(2026, 5, 10, tzinfo=UTC)
        t1 = datetime(2026, 5, 11, tzinfo=UTC)
        t2 = datetime(2026, 5, 11, 12, tzinfo=UTC)
        cache.put(_entry(txn="a", cached_at=t1))
        cache.put(_entry(txn="b", cached_at=t0))
        cache.put(_entry(txn="c", cached_at=t2))
        stats = cache.stats()
        assert stats.total_rows == 3
        assert stats.oldest_cached_at == t0
        assert stats.newest_cached_at == t2


class TestRobustness:
    def test_get_with_unicode_properties(self, cache: SqliteDocumentCache) -> None:
        entry = _entry(properties={"Nombre": "García Lorca", "Tipo": "$x!12"})
        cache.put(entry)
        got = cache.get(CacheKey(entry.txn_num, entry.fields_hash))
        assert got is not None
        assert got.properties["Nombre"] == "García Lorca"

    def test_clear_nonexistent_txn_returns_zero(self, cache: SqliteDocumentCache) -> None:
        assert cache.clear_txn("never_existed") == 0

    def test_clear_older_than_handles_empty(self, cache: SqliteDocumentCache) -> None:
        assert cache.clear_older_than(datetime(2030, 1, 1, tzinfo=UTC)) == 0

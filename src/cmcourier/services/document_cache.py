"""Cross-batch S3 metadata cache service (POST-MVP §9, 037 Phase 2).

Wraps :class:`IDocumentCache` with TTL logic, hit / miss counters,
and structured log events. The pipeline's S3 path consults this
service before invoking :class:`MetadataService`; a hit short-
circuits the resolver and a miss runs the resolver + writes the
cache.

Clock injection (``clock=lambda: datetime.now(UTC)``) keeps TTL
expiry deterministic in tests.

Constitution Principle III: function size ≤ 50 lines; the
``try_get`` and ``put`` helpers each fit on one screen.
"""

from __future__ import annotations

__all__ = [
    "CacheCounters",
    "DocumentCacheService",
    "compute_fields_hash",
]

import hashlib
import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from cmcourier.domain.models import ResolvedMetadata
from cmcourier.domain.ports import (
    CacheEntry,
    CacheKey,
    CacheStats,
    IDocumentCache,
)

_log = logging.getLogger(__name__)


def compute_fields_hash(fields: Iterable[str]) -> str:
    """Return a SHA-256 hex of the sorted, comma-joined field list.

    Sorting makes the hash independent of declaration order in the
    mapping CSV. Two different field sets MUST produce different
    hashes — that is the cache's mapping-evolution safety guarantee.
    """
    joined = ",".join(sorted(fields))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CacheCounters:
    """Thread-safe in-memory hit / miss counters surfaced to the CLI."""

    hits: int = 0
    misses_absent: int = 0
    misses_expired: int = 0

    @property
    def total_misses(self) -> int:
        return self.misses_absent + self.misses_expired

    @property
    def total_calls(self) -> int:
        return self.hits + self.total_misses


class DocumentCacheService:
    """TTL-aware wrapper over :class:`IDocumentCache`.

    Lifecycle:

    1. Construct with ``cache``, ``ttl_minutes`` and an optional
       monotonic clock.
    2. Pipeline calls :meth:`try_get` before S3.
    3. On a miss, pipeline runs the resolver and calls :meth:`put`.
    """

    def __init__(
        self,
        *,
        cache: IDocumentCache,
        ttl_minutes: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._cache = cache
        self._ttl = timedelta(minutes=int(ttl_minutes))
        self._clock = clock
        self._lock = threading.Lock()
        self._counters = CacheCounters()

    # ---------- API used by the pipeline ----------

    def try_get(self, *, txn_num: str, fields: Iterable[str]) -> CacheEntry | None:
        """Return a fresh entry or ``None``. Updates in-memory counters."""
        key = CacheKey(txn_num=txn_num, fields_hash=compute_fields_hash(fields))
        entry = self._cache.get(key)
        if entry is None:
            with self._lock:
                self._counters.misses_absent += 1
            _log.info(
                "document_cache miss",
                extra={
                    "event": "document_cache_miss",
                    "txn_num": txn_num,
                    "reason": "absent",
                    "fields_hash": key.fields_hash,
                },
            )
            return None
        age = self._clock() - entry.cached_at
        if age > self._ttl:
            with self._lock:
                self._counters.misses_expired += 1
            _log.info(
                "document_cache miss",
                extra={
                    "event": "document_cache_miss",
                    "txn_num": txn_num,
                    "reason": "expired",
                    "age_s": age.total_seconds(),
                    "fields_hash": key.fields_hash,
                },
            )
            return None
        with self._lock:
            self._counters.hits += 1
        _log.info(
            "document_cache hit",
            extra={
                "event": "document_cache_hit",
                "txn_num": txn_num,
                "age_s": age.total_seconds(),
                "fields_hash": key.fields_hash,
            },
        )
        return entry

    def put(
        self,
        *,
        txn_num: str,
        fields: Iterable[str],
        metadata: ResolvedMetadata,
        trigger_cif: str | None,
    ) -> None:
        """Upsert the resolved metadata + the (possibly healed) CIF."""
        entry = CacheEntry(
            txn_num=txn_num,
            fields_hash=compute_fields_hash(fields),
            trigger_cif=trigger_cif,
            properties=MappingProxyType(dict(metadata.properties)),
            cached_at=self._clock(),
        )
        self._cache.put(entry)

    # ---------- operator-facing pass-throughs ----------

    def clear_txn(self, txn_num: str) -> int:
        return self._cache.clear_txn(txn_num)

    def clear_all(self) -> int:
        return self._cache.clear_all()

    def clear_older_than_minutes(self, minutes: int) -> int:
        threshold = self._clock() - timedelta(minutes=int(minutes))
        return self._cache.clear_older_than(threshold)

    def disk_stats(self) -> CacheStats:
        return self._cache.stats()

    def counters_snapshot(self) -> CacheCounters:
        with self._lock:
            return CacheCounters(
                hits=self._counters.hits,
                misses_absent=self._counters.misses_absent,
                misses_expired=self._counters.misses_expired,
            )

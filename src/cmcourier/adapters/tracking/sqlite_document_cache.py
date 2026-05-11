"""SQLite-backed :class:`IDocumentCache` (POST-MVP §9, 037 Phase 1).

Stores resolved S3 metadata so cross-batch re-runs of the same
``txn_num`` skip the resolver. Uses the same database file as
:class:`SQLiteTrackingStore` — the schema migration for
``document_cache`` runs at every tracking store open, so no special
bootstrap is required. The adapter opens its own connection in WAL
mode for thread-safe reads / writes.

Constitution Principle VI: this adapter is the only place that knows
about SQLite for the cache. All TTL / hit-miss logic lives in the
service layer (:mod:`cmcourier.services.document_cache`).
"""

from __future__ import annotations

__all__ = ["SqliteDocumentCache"]

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from cmcourier.domain.exceptions import TrackingError
from cmcourier.domain.ports import (
    CacheEntry,
    CacheKey,
    CacheStats,
    IDocumentCache,
)

_log = logging.getLogger(__name__)

_PRAGMAS_WAL: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
)


class SqliteDocumentCache(IDocumentCache):
    """Concrete cache adapter. One connection per instance, app-locked."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        try:
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            for stmt in _PRAGMAS_WAL:
                self._conn.execute(stmt)
        except sqlite3.Error as exc:
            raise TrackingError("failed to open document cache", path=str(db_path)) from exc

    # ----- get / put -----

    def get(self, key: CacheKey) -> CacheEntry | None:
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT txn_num, fields_hash, trigger_cif, properties_json, cached_at "
                    "FROM document_cache WHERE txn_num = ? AND fields_hash = ?",
                    (key.txn_num, key.fields_hash),
                ).fetchone()
            except sqlite3.Error as exc:
                raise TrackingError("document_cache get failed", txn_num=key.txn_num) from exc
        if row is None:
            return None
        return CacheEntry(
            txn_num=row[0],
            fields_hash=row[1],
            trigger_cif=row[2],
            properties=MappingProxyType(json.loads(row[3])),
            cached_at=datetime.fromisoformat(row[4]),
        )

    def put(self, entry: CacheEntry) -> None:
        payload = json.dumps(dict(entry.properties), separators=(",", ":"))
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO document_cache "
                    "(txn_num, fields_hash, trigger_cif, properties_json, cached_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(txn_num, fields_hash) DO UPDATE SET "
                    "trigger_cif = excluded.trigger_cif, "
                    "properties_json = excluded.properties_json, "
                    "cached_at = excluded.cached_at",
                    (
                        entry.txn_num,
                        entry.fields_hash,
                        entry.trigger_cif,
                        payload,
                        entry.cached_at.isoformat(),
                    ),
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                raise TrackingError("document_cache put failed", txn_num=entry.txn_num) from exc

    # ----- clear -----

    def clear_txn(self, txn_num: str) -> int:
        return self._exec_delete("DELETE FROM document_cache WHERE txn_num = ?", (txn_num,))

    def clear_all(self) -> int:
        return self._exec_delete("DELETE FROM document_cache", ())

    def clear_older_than(self, threshold: datetime) -> int:
        return self._exec_delete(
            "DELETE FROM document_cache WHERE cached_at < ?",
            (threshold.isoformat(),),
        )

    def _exec_delete(self, sql: str, params: tuple[str, ...]) -> int:
        with self._lock:
            try:
                cur = self._conn.execute(sql, params)
                self._conn.commit()
                return cur.rowcount
            except sqlite3.Error as exc:
                raise TrackingError("document_cache delete failed") from exc

    # ----- stats -----

    def stats(self) -> CacheStats:
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT COUNT(*), MIN(cached_at), MAX(cached_at) FROM document_cache"
                ).fetchone()
            except sqlite3.Error as exc:
                raise TrackingError("document_cache stats failed") from exc
        total = int(row[0] or 0)
        oldest = datetime.fromisoformat(row[1]) if row[1] else None
        newest = datetime.fromisoformat(row[2]) if row[2] else None
        return CacheStats(total_rows=total, oldest_cached_at=oldest, newest_cached_at=newest)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                _log.debug("document_cache close raised", exc_info=True)

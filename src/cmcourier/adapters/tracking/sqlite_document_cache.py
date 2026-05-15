""":class:`IDocumentCache` respaldado por SQLite (POST-MVP §9, 037 Fase 1).

Guarda los metadatos resueltos de S3 para que las re-corridas cross-`batch`
del mismo ``txn_num`` salten el resolver. Usa el mismo archivo de base de
datos que :class:`SQLiteTrackingStore` — la migración de schema para
``document_cache`` corre en cada apertura del tracking store, así que no
hace falta bootstrap especial. El adaptador abre su propia conexión en
`WAL mode` para lecturas / escrituras thread-safe.

Principio VI de la Constitución: este adaptador es el único lugar que
sabe de SQLite para el cache. Toda la lógica de TTL / hit-miss vive en la
capa de servicios (:mod:`cmcourier.services.document_cache`).
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
    """Adaptador de cache concreto. Una conexión por instancia, con `lock` a nivel de aplicación."""

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

"""SQLite-backed :class:`ITrackingStore` (REBIRTH §9, §10.3).

Two connections coexist over the same WAL-mode database file:

* a **reader** connection on the main thread, used for synchronous reads
  and for ``start_batch`` (the only write that must be visible immediately);
* a **writer** connection owned by a daemon thread that drains a
  :class:`queue.Queue` of statements and commits them in batches (up to
  500 statements, or every 1 second — whichever fires first).

The reader / writer split is enabled by SQLite's WAL journal mode: a
writer connection never blocks readers and vice versa. ``synchronous=OFF``
and a 64 MiB page cache (REBIRTH §9.3) keep throughput high under
production-scale workloads.

Constitution Principle I: this module only depends on the standard library
and on :mod:`cmcourier.domain`. All :class:`sqlite3.Error` exceptions are
wrapped in :class:`TrackingError` before bubbling up.
"""

from __future__ import annotations

__all__ = ["SQLiteTrackingStore"]

import logging
import queue
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cmcourier.domain.exceptions import TrackingError
from cmcourier.domain.models import MigrationRecord, StageStatus
from cmcourier.domain.ports import ITrackingStore

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema (REQ-014..018)
# ---------------------------------------------------------------------------


_CREATE_MIGRATION_LOG = """
CREATE TABLE IF NOT EXISTS migration_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_shortname   TEXT    NOT NULL,
    trigger_cif         TEXT    NOT NULL,
    trigger_system_id   TEXT    NOT NULL,
    rvabrep_txn_num     TEXT    NOT NULL,
    rvabrep_file_name   TEXT    NOT NULL,
    batch_id            TEXT    NOT NULL,
    status              TEXT    NOT NULL,
    created_at          TEXT    NOT NULL,
    cm_object_id        TEXT,
    cm_folder           TEXT,
    cm_object_type      TEXT,
    error_message       TEXT,
    source_file_path    TEXT,
    page_count          INTEGER,
    file_size_bytes     INTEGER,
    started_at          TEXT,
    completed_at        TEXT,
    retry_count         INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_MIGRATION_BATCH = """
CREATE TABLE IF NOT EXISTS migration_batch (
    batch_id        TEXT PRIMARY KEY,
    total_records   INTEGER NOT NULL,
    started_at      TEXT NOT NULL,
    completed_at    TEXT
)
"""

_CREATE_IDX_TXN_BATCH = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_migration_log_txn_batch
ON migration_log (rvabrep_txn_num, batch_id)
"""

_CREATE_IDX_UPLOADED = """
CREATE INDEX IF NOT EXISTS idx_migration_log_uploaded
ON migration_log (rvabrep_txn_num)
WHERE status = 'S5_DONE'
"""


# ---------------------------------------------------------------------------
# PRAGMAs (REBIRTH §9.3)
# ---------------------------------------------------------------------------


_PRAGMAS_WAL: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=OFF",
    "PRAGMA cache_size=-64000",
    "PRAGMA temp_store=MEMORY",
)

_BATCH_FLUSH_SIZE = 500
_BATCH_FLUSH_INTERVAL_S = 1.0


# is_stage_done(stage) returns True if the row has reached AT LEAST that
# stage's success state. After mark_stage_done(SN_DONE), the row may
# subsequently transition to a later stage's PENDING/DONE/FAILED — those
# all count as "past SN_DONE" so resume logic can skip redoing the work.
_STATUSES_AT_OR_PAST: dict[StageStatus, frozenset[str]] = {
    StageStatus.S1_DONE: frozenset(
        {
            "S1_DONE",
            "S2_PENDING",
            "S2_DONE",
            "S2_FAILED",
            "S3_PENDING",
            "S3_DONE",
            "S3_FAILED",
            "S4_PENDING",
            "S4_DONE",
            "S4_FAILED",
            "S5_PENDING",
            "S5_DONE",
            "S5_FAILED",
        }
    ),
    StageStatus.S2_DONE: frozenset(
        {
            "S2_DONE",
            "S3_PENDING",
            "S3_DONE",
            "S3_FAILED",
            "S4_PENDING",
            "S4_DONE",
            "S4_FAILED",
            "S5_PENDING",
            "S5_DONE",
            "S5_FAILED",
        }
    ),
    StageStatus.S3_DONE: frozenset(
        {
            "S3_DONE",
            "S4_PENDING",
            "S4_DONE",
            "S4_FAILED",
            "S5_PENDING",
            "S5_DONE",
            "S5_FAILED",
        }
    ),
    StageStatus.S4_DONE: frozenset(
        {
            "S4_DONE",
            "S5_PENDING",
            "S5_DONE",
            "S5_FAILED",
        }
    ),
    StageStatus.S5_DONE: frozenset({"S5_DONE"}),
}


# ---------------------------------------------------------------------------
# Write-task envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _WriteTask:
    """A single SQL statement plus its bind parameters, queued for the writer."""

    sql: str
    params: tuple[Any, ...]


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


class SQLiteTrackingStore(ITrackingStore):
    """Concrete tracking store backed by SQLite (WAL + async writer queue)."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._queue: queue.Queue[_WriteTask] = queue.Queue()
        self._stop = threading.Event()
        self._closed = False

        try:
            self._reader = sqlite3.connect(str(db_path))
            self._apply_pragmas(self._reader)
            self._create_schema(self._reader)
        except sqlite3.Error as exc:
            raise TrackingError("failed to open tracking store", path=str(db_path)) from exc

        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="cmcourier-tracking-writer", daemon=True
        )
        self._writer_thread.start()

    # ------------------------------------------------------------------ init

    @staticmethod
    def _apply_pragmas(conn: sqlite3.Connection) -> None:
        for stmt in _PRAGMAS_WAL:
            conn.execute(stmt)

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.execute(_CREATE_MIGRATION_LOG)
        conn.execute(_CREATE_MIGRATION_BATCH)
        conn.execute(_CREATE_IDX_TXN_BATCH)
        conn.execute(_CREATE_IDX_UPLOADED)
        conn.commit()

    # ------------------------------------------------------------ writer loop

    def _writer_loop(self) -> None:
        try:
            writer = sqlite3.connect(str(self._db_path))
            self._apply_pragmas(writer)
        except sqlite3.Error:
            _log.exception("tracking writer: failed to open writer connection")
            return

        while not self._stop.is_set() or not self._queue.empty():
            batch = self._drain_batch()
            if not batch:
                continue
            try:
                writer.execute("BEGIN")
                for task in batch:
                    writer.execute(task.sql, task.params)
                writer.commit()
            except sqlite3.Error:
                _log.exception("tracking writer: batch commit failed (size=%d)", len(batch))
                try:
                    writer.rollback()
                except sqlite3.Error:
                    _log.exception("tracking writer: rollback also failed")
            finally:
                for _ in batch:
                    self._queue.task_done()

        writer.close()

    def _drain_batch(self) -> list[_WriteTask]:
        batch: list[_WriteTask] = []
        try:
            batch.append(self._queue.get(timeout=_BATCH_FLUSH_INTERVAL_S))
        except queue.Empty:
            return batch
        while len(batch) < _BATCH_FLUSH_SIZE:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    # ----------------------------------------------------------- public API

    def flush(self) -> None:
        """Block until the writer queue is fully drained.

        Used by tests and by orchestrators that need to read state they
        just wrote.
        """
        self._queue.join()

    def start_batch(self, total_records: int) -> str:
        """Insert a new batch row synchronously and return its UUID4."""
        batch_id = str(uuid.uuid4())
        try:
            self._reader.execute(
                "INSERT INTO migration_batch (batch_id, total_records, started_at) "
                "VALUES (?, ?, ?)",
                (batch_id, total_records, datetime.now().isoformat()),
            )
            self._reader.commit()
        except sqlite3.Error as exc:
            raise TrackingError("start_batch failed", batch_id=batch_id) from exc
        return batch_id

    def complete_batch(self, batch_id: str) -> None:
        self._enqueue(
            "UPDATE migration_batch SET completed_at = ? WHERE batch_id = ?",
            (datetime.now().isoformat(), batch_id),
        )

    def mark_stage_pending(self, record: MigrationRecord, stage: StageStatus) -> None:
        _require_state(stage, "PENDING")
        # INSERT OR IGNORE makes this idempotent within a batch (unique index
        # on (rvabrep_txn_num, batch_id)).
        sql = (
            "INSERT OR IGNORE INTO migration_log ("
            "trigger_shortname, trigger_cif, trigger_system_id, "
            "rvabrep_txn_num, rvabrep_file_name, batch_id, status, created_at, "
            "cm_object_id, cm_folder, cm_object_type, error_message, "
            "source_file_path, page_count, file_size_bytes, "
            "started_at, completed_at, retry_count"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        self._enqueue(sql, _record_to_params(record, stage))

    def mark_stage_done(self, txn_num: str, batch_id: str, stage: StageStatus) -> None:
        _require_state(stage, "DONE")
        self._enqueue(
            "UPDATE migration_log SET status = ?, completed_at = ? "
            "WHERE rvabrep_txn_num = ? AND batch_id = ?",
            (stage.value, datetime.now().isoformat(), txn_num, batch_id),
        )

    def mark_stage_failed(
        self, txn_num: str, batch_id: str, stage: StageStatus, error: str
    ) -> None:
        _require_state(stage, "FAILED")
        self._enqueue(
            "UPDATE migration_log "
            "SET status = ?, error_message = ?, retry_count = retry_count + 1 "
            "WHERE rvabrep_txn_num = ? AND batch_id = ?",
            (stage.value, error, txn_num, batch_id),
        )

    def is_uploaded(self, txn_num: str) -> bool:
        try:
            row = self._reader.execute(
                "SELECT 1 FROM migration_log "
                "WHERE rvabrep_txn_num = ? AND status = 'S5_DONE' LIMIT 1",
                (txn_num,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise TrackingError("is_uploaded failed", txn_num=txn_num) from exc
        return row is not None

    def is_stage_done(self, txn_num: str, batch_id: str, stage: StageStatus) -> bool:
        _require_state(stage, "DONE")
        valid = _STATUSES_AT_OR_PAST[stage]
        placeholders = ",".join("?" * len(valid))
        try:
            row = self._reader.execute(
                f"SELECT 1 FROM migration_log "
                f"WHERE rvabrep_txn_num = ? AND batch_id = ? AND status IN ({placeholders}) "
                f"LIMIT 1",
                (txn_num, batch_id, *valid),
            ).fetchone()
        except sqlite3.Error as exc:
            raise TrackingError("is_stage_done failed", txn_num=txn_num) from exc
        return row is not None

    def list_txn_nums_for_batch(self, batch_id: str) -> set[str]:
        try:
            rows = self._reader.execute(
                "SELECT DISTINCT rvabrep_txn_num FROM migration_log WHERE batch_id = ?",
                (batch_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise TrackingError("list_txn_nums_for_batch failed", batch_id=batch_id) from exc
        return {row[0] for row in rows}

    def close(self) -> None:
        """Idempotent shutdown: drain queue, stop writer, close reader."""
        if self._closed:
            return
        self._closed = True
        self._queue.join()
        self._stop.set()
        self._writer_thread.join(timeout=5.0)
        try:
            self._reader.close()
        except sqlite3.Error:
            _log.exception("tracking store: failed to close reader connection")

    # --------------------------------------------------------------- helpers

    def _enqueue(self, sql: str, params: tuple[Any, ...]) -> None:
        self._queue.put(_WriteTask(sql=sql, params=params))


# ---------------------------------------------------------------------------
# Module-level helpers (kept outside the class so methods stay terse)
# ---------------------------------------------------------------------------


def _require_state(stage: StageStatus, expected_suffix: str) -> None:
    """Reject stage values whose name does not end with the expected suffix."""
    if not stage.value.endswith(f"_{expected_suffix}"):
        raise ValueError(f"expected a {expected_suffix} stage, got {stage.value!r}")


def _record_to_params(record: MigrationRecord, stage: StageStatus) -> tuple[Any, ...]:
    """Flatten a :class:`MigrationRecord` into the 18-tuple for INSERT."""
    return (
        record.trigger_shortname,
        record.trigger_cif,
        record.trigger_system_id,
        record.rvabrep_txn_num,
        record.rvabrep_file_name,
        record.batch_id,
        stage.value,
        record.created_at.isoformat(),
        record.cm_object_id,
        record.cm_folder,
        record.cm_object_type,
        record.error_message,
        record.source_file_path,
        record.page_count,
        record.file_size_bytes,
        record.started_at.isoformat() if record.started_at else None,
        record.completed_at.isoformat() if record.completed_at else None,
        record.retry_count,
    )

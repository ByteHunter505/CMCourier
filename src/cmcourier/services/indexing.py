"""Stage S1 — :class:`IndexingService` (REBIRTH §10.1, §3.2).

Given a :class:`TriggerRecord`, find every non-deleted
:class:`RVABREPDocument` that matches it on ``(shortname, system_id)``. CIF
is intentionally NOT a filter here — CIF self-healing is the responsibility
of Stage S3 (Metadata, REBIRTH §6.5).

Two public APIs:

* :meth:`find_documents` — single-trigger lookup with typed-error semantics
  (raises :class:`RVABREPNotFoundError` / :class:`RVABREPDeletedError`).
* :meth:`find_documents_batch` — Iterator yielding ``(trigger, docs)`` per
  input trigger, chunked into IN-list batches of ``batch_size`` (default 50)
  against the data source. Missing triggers yield an empty list; the
  orchestrator decides per-pipeline semantics.

Constitution Principle I: this module imports only the standard library and
:mod:`cmcourier.domain`. Constitution Principle VIII: logs identify column
names and trigger shortnames but never the values of CIF or free-text
indexed fields.
"""

from __future__ import annotations

__all__ = ["IndexingColumnsConfig", "IndexingService"]

import logging
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from cmcourier.domain.exceptions import (
    IndexingError,
    RVABREPDeletedError,
    RVABREPNotFoundError,
)
from cmcourier.domain.models import (
    RVABREPDocument,
    TriggerRecord,
    parse_cymmdd,
)
from cmcourier.domain.ports import IDataSource

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Column configuration (REBIRTH §3.2 physical names by default)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndexingColumnsConfig:
    """Column-name map between adapter rows and :class:`RVABREPDocument`.

    Defaults match the AS400 RVABREP physical column names from REBIRTH §3.2.
    Tests and non-AS400 deployments override individual columns.
    """

    shortname_column: str = "ABABCD"  # index1 in RVABREPDocument, ShortName trigger
    system_id_column: str = "ABAACD"  # system_code in RVABREPDocument, SystemID trigger
    delete_code_column: str = "ABACST"
    txn_num_column: str = "ABAANB"

    index2_column: str = "ABACCD"
    index3_column: str = "ABADCD"
    index4_column: str = "ABAECD"
    index5_column: str = "ABAFCD"
    index6_column: str = "ABAGCD"
    index7_column: str = "ABAHCD"  # = id_rvi

    image_type_column: str = "ABABST"
    image_path_column: str = "ABAICD"
    file_name_column: str = "ABAJCD"

    creation_date_column: str = "ABAADT"
    last_view_date_column: str = "ABABDT"
    total_pages_column: str = "ABABUN"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class IndexingService:
    """Stage S1 engine: TriggerRecord → list[RVABREPDocument]."""

    def __init__(
        self,
        source: IDataSource,
        config: IndexingColumnsConfig,
        batch_size: int = 50,
    ) -> None:
        self._source = source
        self._cfg = config
        self._batch_size = batch_size

    # ----------------------------------------------------------- public API

    def find_documents(self, trigger: TriggerRecord) -> list[RVABREPDocument]:
        """Look up every non-deleted RVABREP row matching the trigger."""
        rows = self._query_for_trigger(trigger)
        if not rows:
            raise RVABREPNotFoundError(
                shortname=trigger.shortname,
                system_id=trigger.system_id,
            )
        docs = self._classify(rows, trigger)
        if not docs:
            raise RVABREPDeletedError(
                shortname=trigger.shortname,
                system_id=trigger.system_id,
                deleted_count=len(rows),
            )
        return docs

    def find_documents_batch(
        self, triggers: Iterable[TriggerRecord]
    ) -> Iterator[tuple[TriggerRecord, list[RVABREPDocument]]]:
        """Yield (trigger, docs) per input trigger. Missing yields ``[]``."""
        buffer: list[TriggerRecord] = []
        for trigger in triggers:
            buffer.append(trigger)
            if len(buffer) >= self._batch_size:
                yield from self._process_chunk(buffer)
                buffer = []
        if buffer:
            yield from self._process_chunk(buffer)

    # ----------------------------------------------------------- internals

    def _query_for_trigger(self, trigger: TriggerRecord) -> list[dict[str, Any]]:
        try:
            return self._source.get_by_fields(
                {
                    self._cfg.shortname_column: trigger.shortname,
                    self._cfg.system_id_column: trigger.system_id,
                }
            )
        except Exception as exc:
            raise IndexingError(
                "indexing query failed",
                shortname=trigger.shortname,
                system_id=trigger.system_id,
            ) from exc

    def _process_chunk(
        self, chunk: list[TriggerRecord]
    ) -> Iterator[tuple[TriggerRecord, list[RVABREPDocument]]]:
        shortnames = [t.shortname for t in chunk]
        try:
            rows = self._source.get_by_fields_in(
                field=self._cfg.shortname_column,
                values=shortnames,
                fixed_filters={},
            )
        except Exception as exc:
            raise IndexingError(
                "indexing batched query failed",
                shortnames=shortnames,
            ) from exc
        by_key: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = (str(row[self._cfg.shortname_column]), str(row[self._cfg.system_id_column]))
            by_key[key].append(row)
        for trigger in chunk:
            trigger_rows = by_key.get((trigger.shortname, trigger.system_id), [])
            yield trigger, self._classify(trigger_rows, trigger)

    def _classify(
        self, rows: list[dict[str, Any]], trigger: TriggerRecord
    ) -> list[RVABREPDocument]:
        active = [r for r in rows if not _str(r.get(self._cfg.delete_code_column))]
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        duplicates = 0
        for row in active:
            txn = _str(row.get(self._cfg.txn_num_column))
            if txn in seen:
                duplicates += 1
                continue
            seen.add(txn)
            unique.append(row)
        if duplicates:
            _log.warning(
                "indexing: dropped duplicate txn_num rows",
                extra={
                    "shortname": trigger.shortname,
                    "duplicate_count": duplicates,
                },
            )
        return [self._row_to_document(r) for r in unique]

    def _row_to_document(self, row: dict[str, Any]) -> RVABREPDocument:
        cfg = self._cfg
        return RVABREPDocument(
            system_code=_str(row.get(cfg.system_id_column)),
            txn_num=_str(row.get(cfg.txn_num_column)),
            index1=_str(row.get(cfg.shortname_column)),
            index2=_str(row.get(cfg.index2_column)),
            index3=_str(row.get(cfg.index3_column)),
            index4=_str(row.get(cfg.index4_column)),
            index5=_str(row.get(cfg.index5_column)),
            index6=_str(row.get(cfg.index6_column)),
            index7=_str(row.get(cfg.index7_column)),
            image_type=_str(row.get(cfg.image_type_column)),
            image_path=_str(row.get(cfg.image_path_column)),
            file_name=_str(row.get(cfg.file_name_column)),
            creation_date=parse_cymmdd(_str(row.get(cfg.creation_date_column))),
            last_view_date=_parse_last_view_date(row.get(cfg.last_view_date_column)),
            total_pages=_to_int(row.get(cfg.total_pages_column)),
            delete_code=_str(row.get(cfg.delete_code_column)),
        )


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _str(value: Any) -> str:
    """Coerce *value* to a string, treating ``None`` as the empty string."""
    if value is None:
        return ""
    return str(value)


def _to_int(value: Any) -> int:
    """Coerce *value* to ``int``; ``None`` / empty string become ``0``."""
    if value is None:
        return 0
    text = str(value).strip()
    if not text:
        return 0
    return int(text)


def _parse_last_view_date(value: Any) -> Any:
    """Parse a CYYMMDD ``last_view_date`` cell, mapping ``'0'`` / ``''`` to ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "0":
        return None
    return parse_cymmdd(text)

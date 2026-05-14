"""Direct-RVABREP trigger strategy. REBIRTH §5.1 mode direct_rvabrep."""

from __future__ import annotations

__all__ = [
    "DirectRvabrepTriggerStrategy",
    "RvabrepColumnsConfig",
    "RvabrepFilters",
]

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from cmcourier.domain.models import RvabrepRowTrigger, Trigger
from cmcourier.domain.ports import IDataSource, S0Strategy

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RvabrepColumnsConfig:
    """RVABREP physical column-name overrides (REBIRTH §3.2)."""

    col_shortname: str = "ABABCD"  # index1
    col_cif: str = "ABACCD"  # index2
    col_system_id: str = "ABAACD"  # system_code
    col_id_rvi: str = "ABAHCD"  # index7 (document type)
    file_name_column: str = "ABAJCD"  # ABAJCD (file_name)


@dataclass(frozen=True, slots=True)
class RvabrepFilters:
    """Filters for the RVABREP scan. Empty tuple = no filter."""

    systems: tuple[str, ...] = ()
    document_types: tuple[str, ...] = ()


def _is_blank(v: object) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


class DirectRvabrepTriggerStrategy(S0Strategy):
    """Discovers triggers by scanning RVABREP itself, optionally filtered.

    046: yields one :class:`RvabrepRowTrigger` per non-deleted matched row.
    Pre-046 the strategy deduplicated by ``(shortname, system_id)`` and
    yielded a ``TriggerRecord``; that forced S1 to re-query RVABREP and
    re-expand back to N docs per client — wasted work and the wrong
    semantic for "process THIS row, not the whole client". The
    enrichment now stays trivial in S1 because the row is already known.

    When both ``systems`` and ``document_types`` filters are set, the
    strategy picks the smaller filter for the IN-list query and rejects the
    other in Python during iteration. See plan §3.5.
    """

    def __init__(
        self,
        rvabrep_source: IDataSource,
        filters: RvabrepFilters | None = None,
        columns: RvabrepColumnsConfig | None = None,
    ) -> None:
        self._source = rvabrep_source
        self._filters = filters or RvabrepFilters()
        self._columns = columns or RvabrepColumnsConfig()

    def acquire(self, source_descriptor: str = "") -> Iterator[Trigger]:
        """Yield one ``RvabrepRowTrigger`` per matched RVABREP row.

        Rows with blank shortname OR system_id are dropped with a single
        INFO summary log line (rare — they indicate malformed RVABREP
        rows that wouldn't survive S1 anyway).
        """
        del source_descriptor
        skipped = 0
        for row in self._iter_filtered_rows():
            shortname_raw = row.get(self._columns.col_shortname)
            system_raw = row.get(self._columns.col_system_id)
            if _is_blank(shortname_raw) or _is_blank(system_raw):
                skipped += 1
                continue
            yield RvabrepRowTrigger(
                row=row,
                col_shortname=self._columns.col_shortname,
                col_cif=self._columns.col_cif,
                col_system_id=self._columns.col_system_id,
            )
        if skipped:
            _logger.info("skipped %d malformed RVABREP row(s)", skipped)

    def _iter_filtered_rows(self) -> Iterator[dict[str, object]]:
        f = self._filters
        if not f.systems and not f.document_types:
            yield from self._source.get_all()
            return
        # Pick the smaller filter for the IN query; reject the other in Python.
        if f.document_types and (not f.systems or len(f.document_types) <= len(f.systems)):
            primary_field, primary_values = self._columns.col_id_rvi, list(f.document_types)
            secondary_field, secondary_values = self._columns.col_system_id, set(f.systems)
        else:
            primary_field, primary_values = self._columns.col_system_id, list(f.systems)
            secondary_field, secondary_values = self._columns.col_id_rvi, set(f.document_types)
        rows = self._source.get_by_fields_in(
            field=primary_field,
            values=primary_values,
            fixed_filters={},
        )
        for row in rows:
            if secondary_values:
                v = row.get(secondary_field)
                if v is None or str(v) not in secondary_values:
                    continue
            yield row

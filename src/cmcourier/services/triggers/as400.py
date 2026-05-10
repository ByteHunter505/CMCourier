"""AS400 trigger strategy — REBIRTH §5.1 mode ``as400:<alias>``.

Runs a configured SQL query over an :class:`As400DataSource` and yields
one :class:`TriggerRecord` per row. Rows with blank ``shortname`` or
``system_id`` are dropped with an INFO log of the count (matches
:class:`CsvTriggerStrategy` semantics).

Constitution Principle VIII: the SQL query MAY contain customer keys
(CIFs, shortnames). The strategy NEVER logs the query body or its
parameters.
"""

from __future__ import annotations

__all__ = ["As400TriggerStrategy"]

import logging
from collections.abc import Iterator

from cmcourier.adapters.sources.as400 import As400DataSource
from cmcourier.domain.models import TriggerRecord
from cmcourier.domain.ports import S0Strategy

_log = logging.getLogger(__name__)


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


class As400TriggerStrategy(S0Strategy):
    """Run an AS400 SELECT and yield TriggerRecords from the rows."""

    def __init__(
        self,
        source: As400DataSource,
        query: str,
        *,
        col_shortname: str = "SHORTNAME",
        col_cif: str = "CIF",
        col_system_id: str = "SYSTEMID",
    ) -> None:
        self._source = source
        self._query = query
        self._col_shortname = col_shortname
        self._col_cif = col_cif
        self._col_system_id = col_system_id

    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]:
        del source_descriptor  # vestigial port parameter
        skipped = 0
        for row in self._source.query_stream(self._query, []):
            shortname = row.get(self._col_shortname)
            system_id = row.get(self._col_system_id)
            if _is_blank(shortname) or _is_blank(system_id):
                skipped += 1
                continue
            cif = row.get(self._col_cif)
            yield TriggerRecord(
                shortname=str(shortname).strip(),
                cif=None if _is_blank(cif) else str(cif).strip(),
                system_id=str(system_id).strip(),
            )
        if skipped:
            _log.info("as400 trigger: skipped %d blank rows", skipped)

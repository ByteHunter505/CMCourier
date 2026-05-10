"""CSV-driven trigger strategy. REBIRTH §5.1 mode csv:<alias>."""

from __future__ import annotations

__all__ = ["CsvTriggerColumnsConfig", "CsvTriggerStrategy"]

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.models import TriggerRecord
from cmcourier.domain.ports import IDataSource, S0Strategy

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CsvTriggerColumnsConfig:
    """Column-name overrides for a CSV trigger source.

    Defaults match the canonical layout in REBIRTH §12 trigger config.
    """

    col_shortname: str = "ShortName"
    col_cif: str = "CIF"
    col_system_id: str = "SystemID"


def _is_blank(v: object) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


class CsvTriggerStrategy(S0Strategy):
    """Reads triggers from any tabular ``IDataSource`` (CSV, XLSX, etc.).

    The first row is checked against required columns ``col_shortname`` and
    ``col_system_id``. ``col_cif`` is optional — its absence (or per-row
    blank cells) yields ``TriggerRecord.cif=None`` so CIF self-healing in
    stage S3 (REBIRTH §6.5) can populate it later.
    """

    def __init__(
        self,
        source: IDataSource,
        columns: CsvTriggerColumnsConfig | None = None,
    ) -> None:
        self._source = source
        self._columns = columns or CsvTriggerColumnsConfig()

    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]:
        """Yield TriggerRecord per non-blank row. ``source_descriptor`` ignored."""
        del source_descriptor  # vestigial port parameter; see plan §3.3
        skipped = 0
        validated = False
        for row in self._source.get_all():
            if not validated:
                self._validate_columns(row)
                validated = True
            shortname_raw = row.get(self._columns.col_shortname)
            system_raw = row.get(self._columns.col_system_id)
            if _is_blank(shortname_raw) or _is_blank(system_raw):
                skipped += 1
                continue
            cif_raw = row.get(self._columns.col_cif)
            yield TriggerRecord(
                shortname=str(shortname_raw).strip(),
                cif=None if _is_blank(cif_raw) else str(cif_raw).strip(),
                system_id=str(system_raw).strip(),
            )
        if skipped:
            _logger.info("skipped %d blank trigger row(s)", skipped)

    def _validate_columns(self, row: dict[str, object]) -> None:
        for col in (self._columns.col_shortname, self._columns.col_system_id):
            if col not in row:
                raise ConfigurationError(
                    "Trigger CSV missing required column",
                    missing_column=col,
                )
        # col_cif is optional: absence yields cif=None for every record.

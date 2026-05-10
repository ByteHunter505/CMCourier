"""Mapping service - in-memory cache + lookup over the Modelo Documental.

REBIRTH §4. Loads every row from any :class:`IDataSource` at construction
and builds an ``id_rvi -> CMMapping`` dict for O(1) lookup. Subsequent
``get_mapping`` calls hit the cache. The service does no I/O after
construction.

Stage S2 (Document Class Mapping) of every pipeline depends on this
service, as does the ``doctor`` command's mapping-completeness check.

Constitution Principle I: imports only ``cmcourier.domain.*`` and the
Python standard library. No third-party imports, no adapter imports.
"""

from __future__ import annotations

__all__ = ["MappingColumnsConfig", "MappingService"]

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from cmcourier.domain.exceptions import ConfigurationError, IDRViNotMappedError
from cmcourier.domain.models import CMMapping
from cmcourier.domain.ports import IDataSource

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MappingColumnsConfig:
    """Column-name overrides for a Modelo Documental source.

    Defaults match REBIRTH §4.1 (the canonical CSV layout).
    """

    col_clase_id: str = "ID CLASE DOCUMENTAL"
    col_id_rvi: str = "ID RVI"
    col_id_corto: str = "ID Corto"
    col_clase_name: str = "CLASE DOCUMENTAL"
    col_metadata_list: str = "METADATOS"

    def required_columns(self) -> tuple[str, ...]:
        """Return the names of every column the service must find in the source."""
        return (
            self.col_clase_id,
            self.col_id_rvi,
            self.col_id_corto,
            self.col_clase_name,
            self.col_metadata_list,
        )


def _is_blank(value: object) -> bool:
    """Return True if *value* is None, empty, or whitespace-only."""
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_metadata_list(raw: object) -> tuple[str, ...]:
    """Parse the ``METADATOS`` cell into a tuple of trimmed, non-empty fields."""
    if _is_blank(raw) or not isinstance(raw, str):
        return ()
    parts = (p.strip() for p in raw.split(","))
    return tuple(p for p in parts if p)


class MappingService:
    """In-memory cache + lookup over the Modelo Documental (REBIRTH §4).

    Construction iterates the entire source once, validates required columns,
    and builds a dict keyed by ``id_rvi``. First occurrence of a duplicate
    ``id_rvi`` wins (REBIRTH §4.3); subsequent occurrences are dropped with a
    ``WARNING`` log entry. Rows whose ``id_rvi`` is blank are silently
    skipped, with an ``INFO`` log entry summarizing the count.

    The service does not own the source's lifecycle; callers ``close()`` it.
    """

    def __init__(
        self,
        source: IDataSource,
        columns: MappingColumnsConfig | None = None,
    ) -> None:
        self._columns = columns or MappingColumnsConfig()
        self._cache: dict[str, CMMapping] = {}
        self._load(source)

    def _load(self, source: IDataSource) -> None:
        skipped = 0
        validated = False
        for row in source.get_all():
            if not validated:
                self._validate_columns(row)
                validated = True

            id_rvi_raw = row.get(self._columns.col_id_rvi)
            if _is_blank(id_rvi_raw):
                skipped += 1
                continue
            id_rvi = str(id_rvi_raw).strip()

            if id_rvi in self._cache:
                _logger.warning(
                    "duplicate ID RVI %r dropped from mapping (first occurrence wins)",
                    id_rvi,
                )
                continue

            self._cache[id_rvi] = self._row_to_mapping(row, id_rvi)

        if skipped:
            _logger.info(
                "skipped %d row(s) from Modelo Documental with empty ID RVI",
                skipped,
            )

    def _validate_columns(self, row: dict[str, object]) -> None:
        for col in self._columns.required_columns():
            if col not in row:
                raise ConfigurationError(
                    "Modelo Documental missing required column",
                    missing_column=col,
                )

    def _row_to_mapping(self, row: dict[str, object], id_rvi: str) -> CMMapping:
        return CMMapping(
            clase_id=str(row[self._columns.col_clase_id]).strip(),
            id_rvi=id_rvi,
            id_corto=str(row[self._columns.col_id_corto]).strip(),
            clase_name=str(row[self._columns.col_clase_name]).strip(),
            required_metadata_fields=_parse_metadata_list(row.get(self._columns.col_metadata_list)),
        )

    def get_mapping(self, id_rvi: str) -> CMMapping:
        """Return the :class:`CMMapping` for *id_rvi*; raise on miss."""
        try:
            return self._cache[id_rvi]
        except KeyError:
            raise IDRViNotMappedError(id_rvi=id_rvi) from None

    def get_all(self) -> Iterator[CMMapping]:
        """Yield every cached mapping in the order rows arrived from the source."""
        return iter(self._cache.values())

    def count(self) -> int:
        """Return the number of mappings cached."""
        return len(self._cache)

    def __contains__(self, id_rvi: object) -> bool:
        return isinstance(id_rvi, str) and id_rvi in self._cache

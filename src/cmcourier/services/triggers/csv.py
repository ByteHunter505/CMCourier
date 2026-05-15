"""Estrategia de trigger basada en CSV. Modo ``csv:<alias>``."""

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
    """Overrides de nombres de columna para una fuente CSV de trigger.

    Los defaults coinciden con el layout canónico del CSV de trigger.
    """

    col_shortname: str = "ShortName"
    col_cif: str = "CIF"
    col_system_id: str = "SystemID"


def _is_blank(v: object) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


class CsvTriggerStrategy(S0Strategy):
    """Lee triggers desde cualquier ``IDataSource`` tabular (CSV,
    XLSX, etc.).

    La primera fila se chequea contra las columnas requeridas
    ``col_shortname`` y ``col_system_id``. ``col_cif`` es opcional:
    su ausencia (o celdas vacías por fila) producen
    ``TriggerRecord.cif=None`` para que el self-healing de CIF en
    el stage S3 lo pueda completar más adelante.
    """

    def __init__(
        self,
        source: IDataSource,
        columns: CsvTriggerColumnsConfig | None = None,
    ) -> None:
        self._source = source
        self._columns = columns or CsvTriggerColumnsConfig()

    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]:
        """Yieldea un ``TriggerRecord`` por cada fila no vacía.
        ``source_descriptor`` se ignora."""
        del source_descriptor  # parámetro vestigial del port; ver plan §3.3
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
        # ``col_cif`` es opcional: su ausencia produce ``cif=None`` en
        # cada record.

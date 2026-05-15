"""Estrategia de trigger por RVABREP directo. Modo ``direct_rvabrep``."""

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
    """Overrides de nombres físicos de columnas de RVABREP."""

    col_shortname: str = "ABABCD"  # index1
    col_cif: str = "ABACCD"  # index2
    col_system_id: str = "ABAACD"  # system_code
    col_id_rvi: str = "ABAHCD"  # index7 (tipo de documento)
    file_name_column: str = "ABAJCD"  # ABAJCD (file_name)


@dataclass(frozen=True, slots=True)
class RvabrepFilters:
    """Filtros para el escaneo de RVABREP. Tupla vacía = sin filtro."""

    systems: tuple[str, ...] = ()
    document_types: tuple[str, ...] = ()


def _is_blank(v: object) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


class DirectRvabrepTriggerStrategy(S0Strategy):
    """Descubre triggers escaneando RVABREP en sí, opcionalmente
    filtrado.

    046: yieldea un :class:`RvabrepRowTrigger` por cada fila
    matcheada y no borrada. Antes de 046 la estrategia deduplicaba
    por ``(shortname, system_id)`` y yieldeaba un ``TriggerRecord``;
    eso forzaba a S1 a re-consultar RVABREP y re-expandir a N docs
    por cliente, trabajo desperdiciado y semántica equivocada para
    "procesar ESTA fila, no todo el cliente". Ahora el enriquecimiento
    en S1 queda trivial porque la fila ya se conoce.

    Cuando los filtros ``systems`` y ``document_types`` están ambos
    seteados, la estrategia elige el filtro más chico para la query
    de lista IN y rechaza el otro en Python durante la iteración.
    Ver plan §3.5.
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
        """Yieldea un ``RvabrepRowTrigger`` por cada fila matcheada
        de RVABREP.

        Las filas con shortname o system_id vacío se descartan con
        una única línea de log INFO de resumen (raro: indican filas
        malformadas de RVABREP que no sobrevivirían a S1 de todos
        modos).
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
        # Elegir el filtro más chico para la query IN; rechazar el
        # otro en Python.
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

"""Estrategia de trigger por escaneo local. Modo ``local_scan``.

Lista ``scan_path`` de forma no recursiva y yieldea un
:class:`TriggerRecord` por cada fila de RVABREP cuyo filename
matchea con el directorio. Caso de uso: archivos ya extraídos del
file server AS400 a un directorio local; el `pipeline` maneja el
descubrimiento a partir del estado del filesystem en vez de
escaneos de RVABREP o CSVs de trigger.

Algoritmo:

1. Listar ``scan_path`` de forma no recursiva (``Path.iterdir``).
2. Conservar las entradas cuyo nombre tiene extensión ``.PDF``
   (case-insensitive) O termina en ``.001`` (primera página de un
   doc paginado).
3. Por cada sobreviviente, consultar la fuente RVABREP vía
   ``get_by_fields({file_name_column: name})``.
4. Por cada fila matcheada, yieldear
   ``TriggerRecord(shortname, cif, system_id)`` armado a partir
   de las columnas index1, index2 y system_code de la fila.
5. Los archivos sin match en RVABREP se descartan con un log
   WARNING.

Principio VIII de la Constitución: los mensajes de log llevan el
NOMBRE del archivo pero NUNCA valores de cliente provenientes de
la fila matcheada de RVABREP.
"""

from __future__ import annotations

__all__ = ["LocalScanTriggerStrategy"]

import logging
from collections.abc import Iterator
from pathlib import Path

from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.models import LocalScanTrigger, Trigger
from cmcourier.domain.ports import IDataSource, S0Strategy
from cmcourier.services.triggers.direct_rvabrep import RvabrepColumnsConfig

_log = logging.getLogger(__name__)


def _is_trigger_filename(name: str) -> bool:
    """Un filename de trigger es un PDF nativo o la primera página
    de un documento paginado."""
    if name.upper().endswith(".PDF"):
        return True
    return name.endswith(".001")


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class LocalScanTriggerStrategy(S0Strategy):
    """Modo ``local_scan``."""

    def __init__(
        self,
        scan_path: Path,
        rvabrep_source: IDataSource,
        columns: RvabrepColumnsConfig | None = None,
    ) -> None:
        self._scan_path = scan_path
        self._rvabrep = rvabrep_source
        self._columns = columns or RvabrepColumnsConfig()

    def acquire(self, source_descriptor: str = "") -> Iterator[Trigger]:
        """Yieldea un ``LocalScanTrigger`` por cada archivo escaneado (046).

        Antes de 046 la estrategia colapsaba cada archivo a un
        ``ClientTrigger`` y S1 lo re-expandía a **todos** los docs
        del cliente dueño del archivo. Operativamente eso significaba
        "tirar 100 archivos en scan_path y subir 1800 docs": semántica
        equivocada. Ahora S1 procesa exactamente el archivo que
        escaneó el operador.
        """
        del source_descriptor  # parámetro vestigial del port
        if not self._scan_path.is_dir():
            raise ConfigurationError(
                "scan_path is not a readable directory",
                scan_path=str(self._scan_path),
            )
        for entry in self._scan_path.iterdir():
            if not entry.is_file() or not _is_trigger_filename(entry.name):
                continue
            rows = self._rvabrep.get_by_fields({self._columns.file_name_column: entry.name})
            if not rows:
                _log.warning(
                    "local_scan: no RVABREP match for file",
                    extra={
                        "file_name": entry.name,
                        "scan_path": str(self._scan_path),
                    },
                )
                continue
            # Si un filename colisiona con varias filas de RVABREP
            # (raro: distintos sistemas con el mismo filename), se
            # emite un trigger por fila matcheada para que cada uno
            # tenga su propio audit trail. En la práctica 1 archivo
            # == 1 fila.
            for row in rows:
                if _clean(row.get(self._columns.col_shortname)) is None:
                    continue
                yield LocalScanTrigger(
                    file_path=entry,
                    row=row,
                    col_shortname=self._columns.col_shortname,
                    col_cif=self._columns.col_cif,
                    col_system_id=self._columns.col_system_id,
                )

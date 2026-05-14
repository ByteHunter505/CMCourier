"""Local-scan trigger strategy. REBIRTH §5.1 mode ``local_scan``.

Lists ``scan_path`` non-recursively and yields one
:class:`TriggerRecord` per RVABREP row that matches a filename in
the directory. Use case: files already extracted from the AS400 file
server to a local directory; the pipeline drives discovery off
filesystem state rather than off RVABREP scans or trigger CSVs.

Algorithm:

1. List ``scan_path`` non-recursively (``Path.iterdir``).
2. Keep entries whose name has extension ``.PDF`` (case-insensitive)
   OR ends in ``.001`` (paged-doc first page per REBIRTH §3.4).
3. For each survivor, query the RVABREP source via
   ``get_by_fields({file_name_column: name})``.
4. For each matched row, yield ``TriggerRecord(shortname, cif,
   system_id)`` built from the row's index1, index2, and
   system_code columns.
5. Files with no RVABREP match → WARNING log + dropped.

Constitution Principle VIII: log messages carry the file NAME but
NEVER any customer values from the matched RVABREP row.
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
    """A trigger filename is a native PDF or the first page of a paged doc."""
    if name.upper().endswith(".PDF"):
        return True
    return name.endswith(".001")


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class LocalScanTriggerStrategy(S0Strategy):
    """REBIRTH §5.1 mode ``local_scan``."""

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
        """Yield one ``LocalScanTrigger`` per scanned file (046).

        Pre-046 the strategy collapsed each file to a ``ClientTrigger`` and
        S1 then re-expanded that to **every** doc of the file's owning
        client. Operationally this meant "drop 100 files into scan_path,
        upload 1800 docs" — the wrong semantic. Now S1 processes exactly
        the file the operator scanned.
        """
        del source_descriptor  # vestigial port parameter
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
            # If a filename collides across multiple RVABREP rows (rare —
            # different systems with the same filename), we emit one
            # trigger per matched row so each gets its own audit trail.
            # In practice 1 file == 1 row.
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

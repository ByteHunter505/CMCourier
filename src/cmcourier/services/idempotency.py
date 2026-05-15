"""`IdempotencyCoordinator` (034 fase 3).

Compone el :class:`SQLiteTrackingStore` siempre presente (máquina
de estados por `batch`, resume, auditoría) con un
:class:`As400NiarvilogStore` opcional (`idempotency` distribuida
cross-`batch` cuando ``tracking.as400_sync.enabled=true``).

Contrato de diseño:

* Cuando ``as400_store is None``: cada lectura/escritura delega
  directamente a SQLite. El comportamiento es byte-identical al de
  pre-034.
* Cuando ``as400_store`` está provisto:
  * Las lecturas de `idempotency` cross-`batch` provienen de AS400
    (es la fuente distribuida de verdad: SQLite es por workstation
    y puede atrasarse).
  * Las lecturas por `batch` (``mark_stage_done``, ``is_stage_done``)
    siguen yendo a SQLite porque AS400 no tiene noción de `batches`.
  * Las escrituras terminales (``mark_uploaded`` / ``mark_failed``)
    son DUALES: primero SQLite (resume in-process) y luego AS400
    (estado visible para el operador).

El coordinador NO decide la política ante conflictos: los expone
vía :class:`SyncReport` y deja que el caller decida si lanzar.
"""

from __future__ import annotations

__all__ = [
    "IdempotencyConflictError",
    "IdempotencyCoordinator",
    "SyncReport",
]

import logging
from dataclasses import dataclass, field

from cmcourier.adapters.tracking.as400_niarvilog import (
    As400NiarvilogStore,
    NiarvilogRow,
)
from cmcourier.domain.models import (
    CMMapping,
    MigrationRecord,
    RVABREPDocument,
    StageStatus,
    Trigger,
)
from cmcourier.domain.ports import ITrackingStore

_log = logging.getLogger(__name__)


class IdempotencyConflictError(Exception):
    """Se lanza desde :meth:`IdempotencyCoordinator.preflight_sync`
    cuando AS400 y SQLite difieren sobre el estado terminal de un doc.

    El `pipeline` aborta; el operador resuelve con
    ``cmcourier sync resolve``.
    """


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Resultado de una pasada de reconciliación pre-flight.

    * ``imported_from_as400``: txn_nums donde AS400 ya tenía
      ``STSCOD='O'`` y se importó el OBJIDN / estado a SQLite.
    * ``conflicts``: txn_nums donde AS400 y SQLite difieren sobre
      "¿este doc está terminado?". El caller decide si lanzar.
    * ``stale_cleaned``: cantidad de filas con ``STSCOD='I'`` que
      pre-flight reseteó a ``N`` (un run anterior crasheó en medio
      del claim).
    """

    imported_from_as400: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    stale_cleaned: int = 0


class IdempotencyCoordinator:
    """`Dispatch` de lectura/escritura entre SQLite y (opcionalmente) AS400."""

    def __init__(
        self,
        *,
        sqlite_store: ITrackingStore,
        as400_store: As400NiarvilogStore | None = None,
    ) -> None:
        self._sqlite = sqlite_store
        self._as400 = as400_store

    # ----- API de lectura --------------------------------------------

    def is_uploaded(self, txn_num: str) -> bool:
        """Chequeo legacy solo contra SQLite. Usar
        :meth:`is_uploaded_record` cuando el store AS400 está activo y
        se cuenta con el contexto completo de document/trigger (la PK
        de AS400 es compuesta)."""
        return self._sqlite.is_uploaded(txn_num)

    def is_uploaded_record(
        self,
        *,
        document: RVABREPDocument,
        trigger: Trigger,
    ) -> bool:
        """Cuando AS400 está activo, pregunta directamente a AS400 vía
        la PK compuesta. Cuando AS400 es ``None``, cae a SQLite por
        txn_num.
        """
        if self._as400 is None:
            return self._sqlite.is_uploaded(document.txn_num)
        row = self._as400.read_state(
            siscod=trigger.audit_row().get("system_id") or "",
            trnnum=document.txn_num,
            docfrm=document.index7,
            imgarc=document.file_name,
        )
        return row is not None and row.stscod == "O"

    # ----- API de escritura ------------------------------------------

    def try_claim(
        self,
        *,
        record: MigrationRecord,
        document: RVABREPDocument,
        mapping: CMMapping,
        trigger: Trigger,
    ) -> bool:
        """Con AS400 activo: claim atómico contra NIARVILOG. Devuelve
        ``False`` si otro proceso es dueño del doc.

        Con AS400 ``None``: siempre devuelve ``True`` (sin claim
        distribuido).
        """
        if self._as400 is None:
            return True
        return self._as400.try_claim(
            record=record,
            document=document,
            mapping=mapping,
            trigger=trigger,
        )

    def mark_uploaded(
        self,
        *,
        record: MigrationRecord,
        document: RVABREPDocument,
        mapping: CMMapping,
        trigger: Trigger,
        cm_object_id: str,
    ) -> None:
        """Marca S5_DONE en SQLite primero y luego propaga a AS400 si
        está activo. El orden importa: SQLite es la fuente de verdad
        in-process para el resume, así que tiene que hacer `commit`
        antes que cualquier escritura a AS400 (que podría fallar y
        disparar `retry`)."""
        self._sqlite.mark_stage_done(
            record.rvabrep_txn_num,
            record.batch_id,
            StageStatus.S5_DONE,
            cm_object_id=cm_object_id,
        )
        if self._as400 is None:
            return
        self._as400.mark_uploaded(
            record=record,
            document=document,
            mapping=mapping,
            trigger=trigger,
            cm_object_id=cm_object_id,
        )

    def mark_failed(
        self,
        *,
        record: MigrationRecord,
        document: RVABREPDocument,
        mapping: CMMapping,
        trigger: Trigger,
        stage: StageStatus,
        error: str,
    ) -> None:
        """Marca <stage>_FAILED en SQLite primero y luego propaga a AS400."""
        self._sqlite.mark_stage_failed(record.rvabrep_txn_num, record.batch_id, stage, error)
        if self._as400 is None:
            return
        self._as400.mark_failed(
            record=record,
            document=document,
            mapping=mapping,
            trigger=trigger,
            error=error,
        )

    # ----- pre-flight ------------------------------------------------

    def preflight_sync(
        self,
        *,
        batch_scope: set[str],
        raise_on_conflict: bool = False,
    ) -> SyncReport:
        """Reconcilia AS400 → SQLite para el alcance del `batch`.

        Algoritmo (solo corre cuando AS400 está activo):

        1. Ejecuta :meth:`As400NiarvilogStore.cleanup_stale_in_progress`.
        2. Para cada txn_num en ``batch_scope``, le pregunta a AS400
           por el estado de la fila y lo compara con SQLite.
        3. Clasifica: ``imported_from_as400`` (AS400 done, SQLite
           vacío), ``conflicts`` (AS400 no done pero SQLite dice done),
           o consistente (sin acción).
        4. Si ``raise_on_conflict=True`` y hay conflictos, lanza
           :class:`IdempotencyConflictError` con la lista de txns.

        Cuando AS400 es ``None``, devuelve un reporte vacío (no-op).
        """
        if self._as400 is None:
            return SyncReport()
        stale = self._as400.cleanup_stale_in_progress()
        imported: list[str] = []
        conflicts: list[str] = []
        for txn in sorted(batch_scope):
            row = self._safe_read(txn)
            if row is None:
                continue
            sqlite_done = (
                self._sqlite.is_stage_done(txn, "", StageStatus.S5_DONE)
                if hasattr(self._sqlite, "is_stage_done")
                else False
            )
            # Leer SQLite sin batch_id es ambiguo en la API actual;
            # para el pre-flight v1 se cae a ``is_uploaded`` (estado
            # terminal cross-`batch`).
            sqlite_done = self._sqlite.is_uploaded(txn)
            if row.stscod == "O" and not sqlite_done:
                imported.append(txn)
            elif row.stscod != "O" and sqlite_done:
                conflicts.append(txn)
            # Cualquier otra combinación es consistente: skip.
        report = SyncReport(
            imported_from_as400=imported,
            conflicts=conflicts,
            stale_cleaned=stale,
        )
        if raise_on_conflict and conflicts:
            raise IdempotencyConflictError(
                "AS400 vs SQLite conflict on "
                f"{len(conflicts)} txn(s): {', '.join(conflicts[:5])}"
                + ("..." if len(conflicts) > 5 else "")
                + ". Resolve with `cmcourier sync resolve <txn> "
                "--prefer-as400|--prefer-local` (or --all)."
            )
        return report

    # ----- helpers ---------------------------------------------------

    def _safe_read(self, txn: str) -> NiarvilogRow | None:
        """Lookup pre-flight únicamente por TRNNUM (034 fase 4).

        Usa el helper ``read_state_by_txn`` del store. Por convención
        operativa del banco, cada txn_num tiene como máximo una fila
        en NIARVILOG (la del IMGARC de la primera página).
        """
        assert self._as400 is not None
        return self._as400.read_state_by_txn(trnnum=txn)

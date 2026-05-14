"""Domain models — frozen dataclasses, REBIRTH §3-§10 source of truth.

Pure Python standard library only. Constitution Principle I: domain has zero
external dependencies. Every dataclass is ``frozen=True, slots=True`` so
mutation is impossible and per-instance memory is minimal at scale.

This module owns the helpers ``parse_cymmdd``, ``is_pdf_filename``,
``compute_cm_folder``, and ``compute_cm_object_type`` because they are tightly
bound to the model semantics (REBIRTH §3.3, §3.4, §4.2).
"""

from __future__ import annotations

__all__ = [
    "BatchDetails",
    "BatchInfo",
    "CMMapping",
    "ClientTrigger",
    "DocDetail",
    "FailedRecord",
    "LocalScanTrigger",
    "MigrationRecord",
    "ResolvedMetadata",
    "RVABREPDocument",
    "RvabrepRowTrigger",
    "StageStatus",
    "StagedFile",
    "Trigger",
    "TriggerRecord",
    "compute_cm_folder",
    "compute_cm_object_type",
    "is_pdf_filename",
    "parse_cymmdd",
]

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

# ---------------------------------------------------------------------------
# Helpers (REBIRTH §3.3, §3.4, §4.2)
# ---------------------------------------------------------------------------


def parse_cymmdd(date_str: str) -> datetime:
    """Parse the AS400 7-digit ``CYYMMDD`` date format (REBIRTH §3.3).

    ``C`` is the century flag: ``0`` = 1900s, ``1`` = 2000s. ``YY`` is the
    year within century, ``MM`` the month, ``DD`` the day.

    >>> parse_cymmdd("1251117")
    datetime.datetime(2025, 11, 17, 0, 0)

    Raises ``ValueError`` for any input that does not match the format or
    represents an invalid calendar date.
    """
    if not isinstance(date_str, str) or len(date_str) != 7 or not date_str.isdigit():
        raise ValueError(f"CYYMMDD requires exactly 7 digits, got {date_str!r}")
    century = int(date_str[0])
    year = (1900 + century * 100) + int(date_str[1:3])
    month = int(date_str[3:5])
    day = int(date_str[5:7])
    return datetime(year, month, day)  # raises ValueError on invalid month/day


def is_pdf_filename(name: str) -> bool:
    """Return ``True`` when *name* is a native PDF (REBIRTH §3.4)."""
    return name.upper().endswith(".PDF")


def compute_cm_folder(clase_id: str) -> str:
    """Compute the CMIS folder path from a Modelo Documental ``clase_id`` (REBIRTH §4.2)."""
    return f"/$type/BAC_{clase_id.replace('.', '_')}"


def compute_cm_object_type(clase_id: str) -> str:
    """Compute the CMIS ``cmis:objectTypeId`` from a ``clase_id`` (REBIRTH §4.2)."""
    return f"$t!-2_BAC_{clase_id.replace('.', '_')}v-1"


# ---------------------------------------------------------------------------
# Stage state machine (REBIRTH §10.3)
# ---------------------------------------------------------------------------


class StageStatus(StrEnum):
    """Per-stage state machine values for the tracking store.

    Inheriting from :class:`enum.StrEnum` (Python 3.11+) means each member is
    its own string literal — ``StageStatus.S1_DONE == "S1_DONE"`` and
    ``str(StageStatus.S1_DONE) == "S1_DONE"``. Persistence layers store the
    member's string value directly as the SQL column.
    """

    S1_PENDING = "S1_PENDING"
    S1_DONE = "S1_DONE"
    S1_FAILED = "S1_FAILED"

    S2_PENDING = "S2_PENDING"
    S2_DONE = "S2_DONE"
    S2_FAILED = "S2_FAILED"

    S3_PENDING = "S3_PENDING"
    S3_DONE = "S3_DONE"
    S3_FAILED = "S3_FAILED"

    S4_PENDING = "S4_PENDING"
    S4_DONE = "S4_DONE"
    S4_FAILED = "S4_FAILED"

    S5_PENDING = "S5_PENDING"
    S5_DONE = "S5_DONE"
    S5_FAILED = "S5_FAILED"

    SKIPPED = "SKIPPED"

    @classmethod
    def terminal_for_stage(cls, stage: int) -> tuple[StageStatus, StageStatus]:
        """Return ``(Sn_DONE, Sn_FAILED)`` for the given stage number."""
        if not 1 <= stage <= 5:
            raise ValueError(f"stage must be in [1, 5], got {stage!r}")
        return (cls[f"S{stage}_DONE"], cls[f"S{stage}_FAILED"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Trigger(ABC):
    """Polymorphic base for everything that disparas a doc through the pipeline (046).

    A trigger's shape depends on what disparates a doc, which depends on the
    pipeline kind:

    * ``ClientTrigger`` — a client tuple (shortname, cif, system_id). S1
      expands it to every RVABREP doc owned by that client. Used by
      csv-trigger and single-doc pipelines (REBIRTH §5.1 csv mode).
    * ``RvabrepRowTrigger`` — a single RVABREP row, already-known. S1 wraps
      it into one ``RVABREPDocument`` without re-querying. Used by
      rvabrep-direct and as400-trigger pipelines (the SQL/scan already
      delivered the row).
    * ``LocalScanTrigger`` — a file on disk + the RVABREP row that
      describes it. S1 emits one ``RVABREPDocument`` for that exact file.
      Used by local-scan pipeline (REBIRTH §5.1 local_scan mode).

    Every concrete subtype implements ``audit_row()`` to produce best-effort
    ``{shortname, cif, system_id}`` strings for the migration_log trigger_*
    columns — those columns are operator-readable audit only; the canonical
    per-doc identity is ``rvabrep_txn_num`` on the resulting
    ``RVABREPDocument``.
    """

    __slots__ = ()

    @abstractmethod
    def audit_row(self) -> dict[str, str | None]:
        """Best-effort projection to {shortname, cif, system_id} for tracking."""


# RVABREP physical column names — used as ``RvabrepRowTrigger`` /
# ``LocalScanTrigger`` defaults so the production AS400 path "just works".
# Strategies that read CSVs with friendly column names (typical for tests +
# the integration fixtures) override the defaults at construction time.
# Matches ``RvabrepColumnsConfig`` defaults (REBIRTH §3.2). Lives in domain
# (not services) because the audit-row projection is a domain concern;
# strategies pass their column names in but don't own the lookup.
_DEFAULT_COL_SHORTNAME = "ABABCD"
_DEFAULT_COL_CIF = "ABACCD"
_DEFAULT_COL_SYSTEM_ID = "ABAACD"


def _read_normalized(row: Mapping[str, Any], key: str) -> str | None:
    v = row.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _project_audit_from_row(
    row: Mapping[str, Any],
    *,
    col_shortname: str,
    col_cif: str,
    col_system_id: str,
) -> dict[str, str | None]:
    """Pull the audit triple from a row, normalizing blanks to None."""
    return {
        "shortname": _read_normalized(row, col_shortname),
        "cif": _read_normalized(row, col_cif),
        "system_id": _read_normalized(row, col_system_id),
    }


@dataclass(frozen=True, slots=True)
class ClientTrigger(Trigger):
    """One row of a client trigger list (REBIRTH §5, pre-046 ``TriggerRecord``).

    ``cif`` may be ``None`` to support the CIF self-healing rule (REBIRTH §6.5):
    in modes where the trigger source does not provide a CIF, the metadata
    layer resolves it from RVABREP and writes back the resolved value.
    """

    shortname: str
    cif: str | None
    system_id: str

    def __post_init__(self) -> None:
        if not self.shortname:
            raise ValueError("ClientTrigger.shortname must be non-empty")
        if not self.system_id:
            raise ValueError("ClientTrigger.system_id must be non-empty")

    def audit_row(self) -> dict[str, str | None]:
        return {"shortname": self.shortname, "cif": self.cif, "system_id": self.system_id}


@dataclass(frozen=True, slots=True)
class RvabrepRowTrigger(Trigger):
    """An already-known RVABREP row (rvabrep-direct + as400-trigger).

    The row carries every column the downstream stages need; S1 wraps it
    into a single ``RVABREPDocument`` without re-querying RVABREP. The
    ``col_*`` fields tell ``audit_row()`` which row keys hold the audit
    triple — defaults are the physical AS400 names, strategies that read
    CSVs with friendly column names override at construction.
    """

    row: Mapping[str, Any]
    col_shortname: str = _DEFAULT_COL_SHORTNAME
    col_cif: str = _DEFAULT_COL_CIF
    col_system_id: str = _DEFAULT_COL_SYSTEM_ID

    def audit_row(self) -> dict[str, str | None]:
        return _project_audit_from_row(
            self.row,
            col_shortname=self.col_shortname,
            col_cif=self.col_cif,
            col_system_id=self.col_system_id,
        )


@dataclass(frozen=True, slots=True)
class LocalScanTrigger(Trigger):
    """One scanned file + the RVABREP row that describes it (local_scan).

    Crucially: ``row`` is the RVABREP entry whose ``ABAJCD`` matched the
    scanned file's name. S1 produces exactly one ``RVABREPDocument`` for
    this file, regardless of how many other docs the same client has —
    the operator who dropped the file into ``scan_path`` wanted THAT file
    migrated, not every doc of its client. ``col_*`` fields carry the
    column-name map for ``audit_row()`` (see ``RvabrepRowTrigger``).
    """

    file_path: Path
    row: Mapping[str, Any]
    col_shortname: str = _DEFAULT_COL_SHORTNAME
    col_cif: str = _DEFAULT_COL_CIF
    col_system_id: str = _DEFAULT_COL_SYSTEM_ID

    def audit_row(self) -> dict[str, str | None]:
        return _project_audit_from_row(
            self.row,
            col_shortname=self.col_shortname,
            col_cif=self.col_cif,
            col_system_id=self.col_system_id,
        )


# 046 — backward-compat alias. Every pre-046 import of ``TriggerRecord``
# (csv-trigger strategy, single-doc CLI, tests, tracking adapter, …) keeps
# resolving to the same concrete dataclass — now named ``ClientTrigger`` to
# reflect its semantic shape but type-identical for ``isinstance`` checks.
TriggerRecord = ClientTrigger


@dataclass(frozen=True, slots=True)
class RVABREPDocument:
    """One row of the AS400 RVABREP master index (REBIRTH §3.2)."""

    system_code: str
    txn_num: str
    index1: str
    index2: str
    index3: str
    index4: str
    index5: str
    index6: str
    index7: str
    image_type: str
    image_path: str
    file_name: str
    creation_date: datetime
    last_view_date: datetime | None
    total_pages: int
    delete_code: str

    @property
    def is_pdf(self) -> bool:
        """Return ``True`` if this document is a native PDF (REBIRTH §3.4)."""
        return is_pdf_filename(self.file_name)

    @property
    def is_deleted(self) -> bool:
        """Return ``True`` if the row has been marked deleted (REBIRTH §3.2)."""
        return bool(self.delete_code)


@dataclass(frozen=True, slots=True)
class CMMapping:
    """One row of the Modelo Documental — RVI type to CM class (REBIRTH §4).

    ``cmis_type`` (034) is the CMIS Type code that maps to AS400
    ``NIARVILOG.TIPIDN``. Defaults to ``""`` until change 035
    splits the mapping CSV into ``MapeoRVI_CM.csv`` +
    ``MetadatosCM.csv`` with an explicit ``CMISType`` column.

    ``cmis_folder`` (038) is the explicit CMIS folder path. When set,
    overrides the derived ``cm_folder`` property at upload time. When
    ``None`` (column blank or absent), pipelines fall back to
    ``cm_folder``.

    ``cmis_property_ids`` (038) maps friendly metadata field names
    (as found in ``MetadatosCM.Metadato``) to their wire-level CMIS
    property identifiers (``MetadatosCM.CMISPropertyId``). ``None``
    means "no catalog" — the metadata service keeps friendly /
    canonical names as the property keys, preserving pre-038 behavior.
    """

    clase_id: str
    id_rvi: str
    id_corto: str
    clase_name: str
    required_metadata_fields: tuple[str, ...]
    cmis_type: str = ""
    cmis_folder: str | None = None
    cmis_property_ids: Mapping[str, str] | None = None

    @property
    def cm_folder(self) -> str:
        """The CMIS folder where documents of this class are uploaded."""
        return compute_cm_folder(self.clase_id)

    @property
    def cm_object_type(self) -> str:
        """The CMIS ``cmis:objectTypeId`` for documents of this class."""
        return compute_cm_object_type(self.clase_id)


@dataclass(frozen=True, slots=True)
class ResolvedMetadata:
    """Read-only snapshot of resolved BAC_* properties for one document (REBIRTH §6).

    Construct via :meth:`from_dict`. The internal storage is a
    ``MappingProxyType`` over a copy, so mutating the source dict cannot
    corrupt the snapshot and the ``properties`` view raises ``TypeError`` on
    item assignment.
    """

    properties: Mapping[str, str]

    @classmethod
    def from_dict(cls, d: Mapping[str, str]) -> ResolvedMetadata:
        return cls(properties=MappingProxyType(dict(d)))

    def __getitem__(self, key: str) -> str:
        return self.properties[key]

    def __contains__(self, key: object) -> bool:
        return key in self.properties

    def __iter__(self) -> Iterator[str]:
        return iter(self.properties)

    def __len__(self) -> int:
        return len(self.properties)


@dataclass(frozen=True, slots=True)
class StagedFile:
    """The output of stage S4 — an assembled file ready for upload (REBIRTH §7)."""

    path: Path
    size_bytes: int
    page_count: int

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise ValueError("StagedFile.size_bytes must be >= 0")
        if self.page_count < 0:
            raise ValueError("StagedFile.page_count must be >= 0")


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    """One row of the tracking store (REBIRTH §9.2).

    Required fields capture the identity of the migration attempt and its
    current status. Optional fields are filled in as the document moves
    through stages.

    ``created_at`` is REQUIRED and provided by the persistence layer (it
    knows when the row was inserted). We deliberately do not use
    ``default_factory=datetime.now`` so tests can pass deterministic values.
    """

    trigger_shortname: str
    trigger_cif: str
    trigger_system_id: str
    rvabrep_txn_num: str
    rvabrep_file_name: str
    batch_id: str
    status: StageStatus
    created_at: datetime

    cm_object_id: str | None = None
    cm_folder: str | None = None
    cm_object_type: str | None = None
    error_message: str | None = None
    source_file_path: str | None = None
    page_count: int | None = None
    file_size_bytes: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0


# ---------------------------------------------------------------------------
# Batch summaries (REBIRTH §11 — operator CLI surface, change 021)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BatchInfo:
    """One row of ``migration_batch`` plus a derived status.

    ``status`` is ``'completed'`` once ``completed_at`` is non-null,
    ``'in_progress'`` otherwise. Computed, not stored — keeps the
    SQLite schema unchanged.
    """

    batch_id: str
    started_at: datetime
    completed_at: datetime | None
    total_records: int

    @property
    def status(self) -> str:
        return "completed" if self.completed_at is not None else "in_progress"


@dataclass(frozen=True, slots=True)
class FailedRecord:
    """One ``*_FAILED`` row of ``migration_log``.

    Used by ``batch show`` to surface what blocked progression.
    """

    txn_num: str
    status: str
    error_message: str


@dataclass(frozen=True, slots=True)
class BatchDetails:
    """Aggregated state of a single batch.

    ``stage_counts`` always contains keys ``S0..S5``; inner dict has
    keys ``DONE / FAILED / PENDING`` with integer counts (zero for
    missing combos). Predictable shape lets the CLI render a stable
    table regardless of the batch's progress.
    """

    info: BatchInfo
    stage_counts: Mapping[str, Mapping[str, int]]
    failed_records: tuple[FailedRecord, ...]


@dataclass(frozen=True, slots=True)
class DocDetail:
    """One ``migration_log`` row, projected for the TUI's per-chunk
    drill-down (052).

    ``status`` is the raw ``Sn_DONE / Sn_FAILED / Sn_PENDING`` value.
    ``error_message`` is the fail/skip reason ("" when there is none).
    Read from the tracking store on demand — never held in memory for
    every chunk (that would undo spec 050's bounded-memory guarantee).
    """

    txn_num: str
    file_name: str
    status: str
    error_message: str
    file_size_bytes: int

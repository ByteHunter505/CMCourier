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
    "CMMapping",
    "MigrationRecord",
    "ResolvedMetadata",
    "RVABREPDocument",
    "StageStatus",
    "StagedFile",
    "TriggerRecord",
    "compute_cm_folder",
    "compute_cm_object_type",
    "is_pdf_filename",
    "parse_cymmdd",
]

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

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


@dataclass(frozen=True, slots=True)
class TriggerRecord:
    """One row of the trigger list (REBIRTH §5).

    ``cif`` may be ``None`` to support the CIF self-healing rule (REBIRTH §6.5):
    in modes where the trigger source does not provide a CIF, the metadata
    layer resolves it from RVABREP and writes back the resolved value.
    """

    shortname: str
    cif: str | None
    system_id: str

    def __post_init__(self) -> None:
        if not self.shortname:
            raise ValueError("TriggerRecord.shortname must be non-empty")
        if not self.system_id:
            raise ValueError("TriggerRecord.system_id must be non-empty")


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
    """One row of the Modelo Documental — RVI type to CM class (REBIRTH §4)."""

    clase_id: str
    id_rvi: str
    id_corto: str
    clase_name: str
    required_metadata_fields: tuple[str, ...]

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

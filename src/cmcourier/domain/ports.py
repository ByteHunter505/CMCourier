"""Abstract interfaces (ports) implemented by adapters in change 003+.

Constitution Principle I: only the standard library and ``cmcourier.domain``
itself may be imported here. No ``pydantic``, no ``requests``, no ``pyodbc``.

Concrete implementations live in ``cmcourier.adapters.*`` (data sources,
tracking, assembly, upload) and in the strategy implementations for stage S0
(``cmcourier.adapters.sources`` for CSV / AS400, plus a folder-scan strategy
in the local-scan pipeline).
"""

from __future__ import annotations

__all__ = [
    "IAssembler",
    "IDataSource",
    "ITrackingStore",
    "IUploader",
    "S0Strategy",
]

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from typing import Any, Literal

from cmcourier.domain.models import (
    BatchDetails,
    BatchInfo,
    MigrationRecord,
    RVABREPDocument,
    StagedFile,
    StageStatus,
    TriggerRecord,
)

# ---------------------------------------------------------------------------
# IDataSource — generic data source abstraction (CSV, AS400, …)
# ---------------------------------------------------------------------------


class IDataSource(ABC):
    """Generic data source. Concrete subclasses wrap CSV files, AS400 ODBC
    connections, or other sources and expose a uniform query API.

    Row values are typed as ``Any`` because data sources return heterogeneous
    primitives (str, int, datetime, Decimal, bytes, None). Callers convert
    rows into typed domain models before passing them on to services.
    """

    @abstractmethod
    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        """Execute a query and return all rows as dicts. Materializes the result."""

    @abstractmethod
    def query_stream(self, sql: str, params: list[Any] | None = None) -> Iterator[dict[str, Any]]:
        """Execute a query and stream rows lazily. Use for large result sets."""

    @abstractmethod
    def get_by_fields(self, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Fetch rows matching ``WHERE`` equality on the given fields."""

    @abstractmethod
    def get_by_fields_in(
        self,
        field: str,
        values: list[Any],
        fixed_filters: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Fetch rows where *field* IN *values* AND every *fixed_filter* matches.

        The split between the IN-list and the fixed equality filters lets the
        adapter chunk the IN clause efficiently (REBIRTH §10.1 batches of 50).
        """

    @abstractmethod
    def get_all(self) -> Iterator[dict[str, Any]]:
        """Stream every row from the underlying source. Used by metadata pre-fetch."""

    @abstractmethod
    def count(self) -> int:
        """Return the total row count of the underlying source."""

    @abstractmethod
    def close(self) -> None:
        """Release any resources (cursors, connections, file handles)."""


# ---------------------------------------------------------------------------
# ITrackingStore — idempotency + per-stage state (REBIRTH §9, §10.3)
# ---------------------------------------------------------------------------


class ITrackingStore(ABC):
    """Tracking store contract.

    Two layers of state:

    1. **Cross-batch idempotency**: ``is_uploaded(txn_num)`` answers "has this
       document ever been successfully uploaded?". The answer drives the
       skip-already-uploaded behavior at the start of any pipeline run.
    2. **Per-batch, per-stage state machine**: ``Sn_PENDING / Sn_DONE /
       Sn_FAILED`` for the current batch. Drives the resume / stage-by-stage
       execution semantics of REBIRTH §10.3.

    Tracking failures (raised by any of these methods) are non-blocking per
    REBIRTH §10.1's stage S6 description — implementations log and convert
    to ``TrackingError`` but the pipeline continues.
    """

    @abstractmethod
    def is_uploaded(self, txn_num: str) -> bool:
        """Cross-batch idempotency anchor. Returns True only when the document's
        terminal status is ``S5_DONE``."""

    @abstractmethod
    def is_stage_done(self, txn_num: str, batch_id: str, stage: StageStatus) -> bool:
        """Per-batch, per-stage check. ``stage`` MUST be a ``Sn_DONE`` value."""

    @abstractmethod
    def mark_stage_pending(self, record: MigrationRecord, stage: StageStatus) -> None:
        """Insert / update the row for *record* at ``Sn_PENDING``."""

    @abstractmethod
    def mark_stage_done(self, txn_num: str, batch_id: str, stage: StageStatus) -> None:
        """Transition the row for *txn_num* in *batch_id* to ``Sn_DONE``."""

    @abstractmethod
    def mark_stage_failed(
        self,
        txn_num: str,
        batch_id: str,
        stage: StageStatus,
        error: str,
    ) -> None:
        """Transition the row for *txn_num* in *batch_id* to ``Sn_FAILED`` and
        store the human-readable error message."""

    @abstractmethod
    def start_batch(self, total_records: int) -> str:
        """Create a new batch and return its identifier."""

    @abstractmethod
    def complete_batch(self, batch_id: str) -> None:
        """Mark the batch closed (no more rows will be added)."""

    @abstractmethod
    def list_txn_nums_for_batch(self, batch_id: str) -> set[str]:
        """Return every ``rvabrep_txn_num`` currently tracked under *batch_id*.

        Used by orchestrators to scope resume runs: re-running S0+S1 may emit
        documents that did not exist in the prior batch (e.g., the trigger CSV
        changed). The orchestrator filters the fresh S1 output through this
        set so only docs that belong to the prior batch are processed.

        Unknown ``batch_id`` MUST return an empty set, NOT raise.
        """

    @abstractmethod
    def flush(self) -> None:
        """Block until pending writes are durable on disk.

        Orchestrators call this before any read that depends on writes from
        the same run (the "read my own writes" anchor). Synchronous
        implementations MAY implement this as a no-op.
        """

    @abstractmethod
    def close(self) -> None:
        """Release any resources (writer thread, cursors, file handles)."""

    # -------------------------------------------------- operator-facing (021)

    @abstractmethod
    def list_batches(
        self,
        status: Literal["in_progress", "completed"] | None = None,
    ) -> list[BatchInfo]:
        """Enumerate batches, optionally filtered by completion state.

        Returned list is ordered by ``started_at`` DESC. Empty when no
        batches recorded. Used by ``cmcourier batch list``.
        """

    @abstractmethod
    def get_batch_details(self, batch_id: str) -> BatchDetails | None:
        """Aggregate per-stage counts + failed records for one batch.

        Returns ``None`` for unknown ``batch_id``. Used by
        ``cmcourier batch show``.
        """

    @abstractmethod
    def retry_failed(
        self,
        batch_id: str,
        stage: StageStatus | None = None,
    ) -> int:
        """Reset ``*_FAILED`` rows in ``batch_id`` back to ``*_PENDING``.

        When ``stage`` is None, ALL failed stages are reset. When
        ``stage`` is a ``Sn_FAILED`` value, only that stage is reset.
        Returns the number of rows touched. Idempotent: a clean batch
        returns 0. Used by ``cmcourier batch retry-failed``.
        """


# ---------------------------------------------------------------------------
# IAssembler — stage S4 (REBIRTH §7)
# ---------------------------------------------------------------------------


class IAssembler(ABC):
    """Assembles a multi-page document into a single staged PDF on disk."""

    @abstractmethod
    def assemble(self, document: RVABREPDocument) -> StagedFile:
        """Verify source files exist and produce an assembled PDF.

        Raises ``SourceFileMissingError`` if a page file is missing, and
        ``PDFAssemblyFailedError`` if the underlying tooling fails.
        """


# ---------------------------------------------------------------------------
# IUploader — stage S5 (REBIRTH §8)
# ---------------------------------------------------------------------------


class IUploader(ABC):
    """Uploads a staged file to IBM Content Manager via CMIS."""

    @abstractmethod
    def ensure_folder(self, folder_path: str) -> None:
        """Create *folder_path* on the CM server if it does not exist.

        Idempotent: HTTP 409 (Conflict) is treated as success per REBIRTH §8.3.
        """

    @abstractmethod
    def upload(
        self,
        file: StagedFile,
        folder_path: str,
        object_type_id: str,
        document_name: str,
        mime_type: str,
        properties: Mapping[str, str],
    ) -> str:
        """Upload *file* and return the resulting CMIS ``cmis:objectId``.

        Raises ``CMISClientError`` for HTTP 4xx (do not retry) and
        ``CMISServerError`` for HTTP 5xx (caller may retry).
        """

    @abstractmethod
    def test_connection(self) -> Mapping[str, str]:
        """Verify the CM endpoint is reachable and the credentials are valid.
        Returns a dict of repository info for diagnostics."""

    @abstractmethod
    def get_type_definition(self, object_type_id: str) -> Mapping[str, Any]:
        """Return the CMIS typeDefinition for *object_type_id*.

        Used by the pre-flight ``doctor`` command (REBIRTH §10.5) to verify
        that every ``cm_object_type`` referenced by the Modelo Documental
        exists on the CM server. Bypasses any retry policy — pre-flight
        prefers fail-loud over retry-quietly.

        Raises:
            CMISClientError: 4xx (typically 404 for missing types).
            CMISServerError: 5xx.
        """


# ---------------------------------------------------------------------------
# S0Strategy — stage S0 (REBIRTH §10.1)
# ---------------------------------------------------------------------------


class S0Strategy(ABC):
    """Stage S0 strategy: turn a source descriptor into a stream of TriggerRecords.

    The four trigger source modes from REBIRTH §5.1 each map to a concrete
    subclass:

    * ``CsvTriggerStrategy`` — reads a CSV file
    * ``As400TriggerStrategy`` — runs a custom AS400 query
    * ``DirectRvabrepStrategy`` — discovers triggers by querying RVABREP
      directly with filters
    * ``LocalScanStrategy`` — scans a folder for files, cross-references
      RVABREP for metadata

    Concrete strategies live in ``cmcourier.adapters.sources`` and land in
    later changes; this interface is the only contract this change ships.
    """

    @abstractmethod
    def acquire(self, source_descriptor: str) -> Iterator[TriggerRecord]:
        """Yield trigger records lazily. Trigger lists may be huge (200k+);
        callers iterate, never materialize."""

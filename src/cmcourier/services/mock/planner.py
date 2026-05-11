"""Pure planner: RVABREP rows → :class:`FilePlan` stream (031, REQ-006..REQ-016).

No I/O. No randomness. Order preserved from the input iterator. Side effects
limited to ``logging`` warnings on dedup conflicts.

The planner is the single place that translates RVABREP semantics
(``ABABST``/``ABABUN``/``ABAJCD``/...) into the on-disk layout the S4
:class:`cmcourier.adapters.assembly.pdf_assembler.PdfAssembler` consumes:

* PDF rows (``is_pdf_filename(file_name)``) yield one plan with
  ``extensions=(".PDF",)``.
* Image rows (``ABABST`` ∈ ``{B, C}``) yield one plan with
  ``extensions=(".001", …, f".{pages:03d}")``.

Unknown ``ABABST`` codes on non-PDF rows raise
:class:`~cmcourier.domain.exceptions.ConfigurationError`. ``image_path``
strings are normalized via :func:`normalize_image_path` (backslash → ``/``,
strip leading separators) before being used as a dedup key.
"""

from __future__ import annotations

__all__ = [
    "PlannerFilters",
    "SizeBounds",
    "normalize_image_path",
    "plan_files",
]

import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from cmcourier.config.schema import IndexingColumnsModel
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.models import is_pdf_filename
from cmcourier.services.mock.types import FileKind, FilePlan

_log = logging.getLogger(__name__)

# ABABST physical codes per pdf_assembler.py:55-57.
_TIFF_CODE = "B"
_JPEG_CODE = "C"
_PDF_CODE = "O"


@dataclass(frozen=True, slots=True)
class PlannerFilters:
    """Filtering options for :func:`plan_files`.

    Empty tuples mean "no filter" on that field. ``limit`` is applied to the
    count of FilePlans actually yielded (post-filter, post-dedup).
    """

    systems: tuple[str, ...] = ()
    document_types: tuple[str, ...] = ()
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class SizeBounds:
    """Per-format byte-count bounds parsed from the CLI suffix options."""

    pdf_min: int
    pdf_max: int
    img_min: int
    img_max: int


def normalize_image_path(s: str) -> Path:
    """Backslash → forward slash, strip leading separators, return a ``Path``.

    Empty / whitespace-only input is the caller's problem to detect; this
    function returns ``Path(".")`` in that case (callers must reject it).
    """
    cleaned = s.replace("\\", "/").lstrip("/").strip()
    return Path(cleaned) if cleaned else Path()


def plan_files(
    rows: Iterable[dict[str, object]],
    columns: IndexingColumnsModel,
    filters: PlannerFilters,
    size_bounds: SizeBounds,
    *,
    include_deleted: bool = False,
) -> Iterator[FilePlan]:
    """Translate RVABREP rows to a stream of :class:`FilePlan` objects.

    Logic order per row:
    1. skip if ``delete_code`` non-empty and ``include_deleted`` is false;
    2. apply ``systems`` and ``document_types`` filters;
    3. normalize ``image_path`` (rejecting empty);
    4. dispatch PDF vs image (raising ``ConfigurationError`` on unknown
       ``image_type`` for non-PDF rows);
    5. dedup by ``(image_path, file_code)``, first row wins;
    6. yield up to ``filters.limit`` plans.
    """
    seen: dict[tuple[Path, str], FilePlan] = {}
    seen_pages: dict[tuple[Path, str], tuple[str, int]] = {}  # (key) → (txn, pages)
    yielded = 0

    for row in rows:
        delete_code = _str(row.get(columns.delete_code_column))
        if delete_code and not include_deleted:
            continue

        system_id = _str(row.get(columns.system_id_column))
        if filters.systems and system_id not in filters.systems:
            continue

        id_rvi = _str(row.get(columns.index7_column))
        if filters.document_types and id_rvi not in filters.document_types:
            continue

        image_path_raw = _str(row.get(columns.image_path_column))
        if not image_path_raw:
            txn = _str(row.get(columns.txn_num_column))
            raise ConfigurationError(
                "row has empty image_path",
                txn_num=txn,
            )
        image_path = normalize_image_path(image_path_raw)

        file_name = _str(row.get(columns.file_name_column))
        file_code = file_name.split(".")[0] if "." in file_name else file_name

        total_pages = _safe_pages(row.get(columns.total_pages_column))
        txn = _str(row.get(columns.txn_num_column))

        if is_pdf_filename(file_name):
            plan = FilePlan(
                dir_path=image_path,
                file_code=file_code,
                kind="pdf",
                pages=total_pages,
                size_min=size_bounds.pdf_min,
                size_max=size_bounds.pdf_max,
                extensions=(".PDF",),
            )
        else:
            image_type = _str(row.get(columns.image_type_column))
            kind = _dispatch_image_kind(image_type, txn)
            plan = FilePlan(
                dir_path=image_path,
                file_code=file_code,
                kind=kind,
                pages=total_pages,
                size_min=size_bounds.img_min,
                size_max=size_bounds.img_max,
                extensions=tuple(f".{i:03d}" for i in range(1, total_pages + 1)),
            )

        key = (image_path, file_code)
        if key in seen:
            prev_txn, prev_pages = seen_pages[key]
            if prev_pages != plan.pages:
                _log.warning(
                    "page-count conflict on dedup; keeping first",
                    extra={
                        "image_path": str(image_path),
                        "file_code": file_code,
                        "first_txn": prev_txn,
                        "first_pages": prev_pages,
                        "dup_txn": txn,
                        "dup_pages": plan.pages,
                    },
                )
            continue
        seen[key] = plan
        seen_pages[key] = (txn, plan.pages)

        yield plan
        yielded += 1
        if filters.limit is not None and yielded >= filters.limit:
            return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _str(value: object) -> str:
    """Coerce a cell value to ``str``. ``None`` → empty string."""
    return "" if value is None else str(value).strip()


def _safe_pages(value: object) -> int:
    """Return ``max(1, int(value))``. Blank / non-numeric / negative → 1."""
    text = _str(value)
    if not text:
        return 1
    try:
        n = int(float(text))
    except (TypeError, ValueError):
        return 1
    return max(1, n)


def _dispatch_image_kind(image_type: str, txn: str) -> FileKind:
    if image_type == _TIFF_CODE:
        return "tiff"
    if image_type == _JPEG_CODE:
        return "jpeg"
    if image_type == _PDF_CODE:
        # A non-PDF filename with ABABST=O is contradictory data; treat as
        # an unknown code so the operator notices.
        raise ConfigurationError(
            "ABABST=O (PDF) on a row whose file_name is not .PDF",
            txn_num=txn,
            image_type=image_type,
        )
    raise ConfigurationError(
        "unknown image_type",
        txn_num=txn,
        image_type=image_type,
    )

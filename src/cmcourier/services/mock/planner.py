"""Planner puro: filas de RVABREP → `stream` de :class:`FilePlan`
(031, REQ-006..REQ-016).

Sin I/O. Sin aleatoriedad. Preserva el orden del iterador de
entrada. Los efectos colaterales se limitan a warnings vía
``logging`` ante conflictos de dedup.

El planner es el único lugar que traduce la semántica de RVABREP
(``ABABST``/``ABABUN``/``ABAJCD``/...) al layout en disco que
consume el
:class:`cmcourier.adapters.assembly.pdf_assembler.PdfAssembler` de
S4:

* Las filas PDF (``is_pdf_filename(file_name)``) yieldean un plan
  con ``extensions=(".PDF",)``.
* Las filas de imagen (``ABABST`` ∈ ``{B, C}``) yieldean un plan
  con ``extensions=(".001", …, f".{pages:03d}")``.

Los códigos ``ABABST`` desconocidos en filas no-PDF lanzan
:class:`~cmcourier.domain.exceptions.ConfigurationError`. Las
cadenas ``image_path`` se normalizan vía :func:`normalize_image_path`
(backslash → ``/``, strip de separadores iniciales) antes de
usarse como clave de dedup.
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

# Códigos físicos de ``ABABST`` según ``pdf_assembler.py:55-57``.
_TIFF_CODE = "B"
_JPEG_CODE = "C"
_PDF_CODE = "O"


@dataclass(frozen=True, slots=True)
class PlannerFilters:
    """Opciones de filtrado para :func:`plan_files`.

    Las tuplas vacías significan "sin filtro" sobre ese campo.
    ``limit`` se aplica a la cuenta de :class:`FilePlan`
    efectivamente yieldeados (post-filtro y post-dedup).
    """

    systems: tuple[str, ...] = ()
    document_types: tuple[str, ...] = ()
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class SizeBounds:
    """Cotas de bytes por formato, parseadas desde las opciones de
    sufijo del CLI."""

    pdf_min: int
    pdf_max: int
    img_min: int
    img_max: int


def normalize_image_path(s: str) -> Path:
    """Backslash → forward slash, strip de separadores iniciales y
    devuelve un ``Path``.

    El input vacío o solo whitespace es problema del caller; esta
    función devuelve ``Path(".")`` en ese caso (los callers deben
    rechazarlo).
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
    """Traduce filas de RVABREP a un `stream` de objetos
    :class:`FilePlan`.

    Orden lógico por fila:

    1. saltar si ``delete_code`` es no vacío e ``include_deleted`` es
       ``False``;
    2. aplicar los filtros ``systems`` y ``document_types``;
    3. normalizar ``image_path`` (rechazando vacío);
    4. `dispatch` entre PDF e imagen (lanzando ``ConfigurationError``
       ante un ``image_type`` desconocido en filas no-PDF);
    5. dedup por ``(image_path, file_code)``, gana la primera fila;
    6. yieldea hasta ``filters.limit`` planes.
    """
    seen: dict[tuple[Path, str], FilePlan] = {}
    seen_pages: dict[tuple[Path, str], tuple[str, int]] = {}  # (clave) → (txn, pages)
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
    """Coerciona el valor de una celda a ``str``. ``None`` → cadena vacía."""
    return "" if value is None else str(value).strip()


def _safe_pages(value: object) -> int:
    """Devuelve ``max(1, int(value))``. Valores vacíos, no numéricos o
    negativos resultan en ``1``."""
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
        # Un filename no-PDF con ``ABABST=O`` es data contradictoria;
        # se trata como código desconocido para que el operador lo
        # note.
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

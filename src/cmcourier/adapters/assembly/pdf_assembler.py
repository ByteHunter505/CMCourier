"""Stage S4 — :class:`PdfAssembler` (REBIRTH §7).

Concrete :class:`IAssembler` over the local file server. Two paths:

* **Native PDF** — ``shutil.copy2`` the source PDF to
  ``temp_dir / "{txn_num}.pdf"``. ``StagedFile.page_count`` is read from
  the document's ``total_pages`` (we trust RVABREP, do not parse).
* **Paged document** — glob ``FILECODE.*`` in the source directory, filter
  to numeric extensions (REBIRTH §3.4), sort by ``int(extension)``, then
  try :func:`img2pdf.convert` as the fast path. On any exception, fall
  back to Pillow + :class:`PyPDF2.PdfMerger`.

OneDrive temp-dir trap (REBIRTH §7.4) is handled in the constructor:
configured paths matching ``./tmp`` variants are diverted to the system
temp directory.

Constitution Principle I: this module imports ``img2pdf``, ``PIL``, and
``PyPDF2`` — all declared in ``pyproject.toml``. Domain models are
imported as types only. Principle VIII: logs identify operational keys
(``txn_num``, ``file_path``, page counts) but never image content or
metadata values.
"""

from __future__ import annotations

__all__ = ["AssemblerConfig", "PdfAssembler"]

import logging
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import img2pdf
from PIL import Image
from PyPDF2 import PdfMerger

from cmcourier.domain.exceptions import (
    PDFAssemblyFailedError,
    SourceFileMissingError,
)
from cmcourier.domain.models import RVABREPDocument, StagedFile

_log = logging.getLogger(__name__)


# OneDrive trap variants normalized for case-insensitive comparison.
_ONEDRIVE_TRAP_VARIANTS: frozenset[str] = frozenset({"tmp", "./tmp", "tmp/", ".\\tmp"})
_DIVERTED_DIR_NAME = "cmcourier_tmp"


def _default_image_type_map() -> dict[str, str]:
    """REBIRTH §7.5 mapping: image_type code → MIME hint."""
    return {"B": "image/tiff", "O": "application/pdf", "C": "image/jpeg"}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssemblerConfig:
    """Configuration for :class:`PdfAssembler`."""

    source_root: Path
    temp_dir: Path
    image_type_map: Mapping[str, str] = field(default_factory=_default_image_type_map)


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------


class PdfAssembler:
    """Concrete :class:`IAssembler` for stage S4."""

    def __init__(self, config: AssemblerConfig) -> None:
        self._cfg = config
        self.temp_dir = self._resolve_temp_dir(config.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------- public API

    def assemble(self, document: RVABREPDocument) -> StagedFile:
        """Turn *document* into a single staged PDF."""
        if document.is_pdf:
            return self._passthrough_native_pdf(document)
        return self._assemble_paged(document)

    # ----------------------------------------------------------- internals

    @staticmethod
    def _resolve_temp_dir(configured: Path) -> Path:
        if str(configured).strip().lower() in _ONEDRIVE_TRAP_VARIANTS:
            return Path(tempfile.gettempdir()) / _DIVERTED_DIR_NAME
        return configured

    def _passthrough_native_pdf(self, doc: RVABREPDocument) -> StagedFile:
        src = self._cfg.source_root / doc.image_path / doc.file_name
        if not src.is_file():
            raise SourceFileMissingError(file_path=str(src))
        dst = self.temp_dir / f"{doc.txn_num}.pdf"
        shutil.copy2(src, dst)
        return StagedFile(
            path=dst,
            size_bytes=dst.stat().st_size,
            page_count=doc.total_pages,
        )

    def _assemble_paged(self, doc: RVABREPDocument) -> StagedFile:
        pages = self._discover_pages(doc)
        output = self.temp_dir / f"{doc.txn_num}.pdf"
        try:
            self._try_img2pdf(pages, output)
        except Exception as primary:  # noqa: BLE001 — img2pdf raises a wide surface
            _log.info(
                "assembler: img2pdf fast path failed, falling back",
                extra={"txn_num": doc.txn_num, "reason": str(primary)},
            )
            try:
                self._fallback_pillow_pypdf2(pages, output)
            except Exception as secondary:
                raise PDFAssemblyFailedError(
                    txn_num=doc.txn_num,
                    reason=f"img2pdf and fallback both failed: {secondary!r}",
                ) from secondary
        return StagedFile(
            path=output,
            size_bytes=output.stat().st_size,
            page_count=len(pages),
        )

    def _discover_pages(self, doc: RVABREPDocument) -> list[Path]:
        source_dir = self._cfg.source_root / doc.image_path
        file_code = doc.file_name.split(".")[0]
        pattern = f"{file_code}.*"
        candidates = [p for p in source_dir.glob(pattern) if _is_numeric_ext(p.suffix.lstrip("."))]
        if not candidates:
            raise SourceFileMissingError(file_path=str(source_dir / pattern))
        candidates.sort(key=lambda p: int(p.suffix.lstrip(".")))
        if len(candidates) != doc.total_pages:
            _log.warning(
                "assembler: page count mismatch",
                extra={
                    "txn_num": doc.txn_num,
                    "expected": doc.total_pages,
                    "discovered": len(candidates),
                },
            )
        return candidates

    @staticmethod
    def _try_img2pdf(pages: list[Path], output: Path) -> None:
        pdf_bytes = img2pdf.convert([str(p) for p in pages])
        if not pdf_bytes:
            raise RuntimeError("img2pdf returned empty bytes")
        output.write_bytes(pdf_bytes)

    @staticmethod
    def _fallback_pillow_pypdf2(pages: list[Path], output: Path) -> None:
        merger = PdfMerger()
        try:
            for page in pages:
                with Image.open(page) as img:
                    rgb = img.convert("RGB") if img.mode != "RGB" else img
                    buf = BytesIO()
                    rgb.save(buf, format="PDF")
                    buf.seek(0)
                    merger.append(buf)
            with output.open("wb") as out:
                merger.write(out)
        finally:
            merger.close()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _is_numeric_ext(text: str) -> bool:
    return bool(text) and text.isdigit()

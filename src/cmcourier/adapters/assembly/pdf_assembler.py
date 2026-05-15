"""Etapa S4 — :class:`PdfAssembler`.

Implementación concreta de :class:`IAssembler` sobre el file server local.
Dos caminos:

* **PDF nativo** — ``shutil.copy2`` del PDF fuente a
  ``temp_dir / "{txn_num}.pdf"``. ``StagedFile.page_count`` se lee de
  ``total_pages`` del documento (confiamos en RVABREP, no parseamos).
* **Documento paginado** — glob de ``FILECODE.*`` en el directorio fuente,
  filtra extensiones numéricas, ordena por ``int(extension)``, y luego
  intenta :func:`img2pdf.convert` como camino rápido. Ante cualquier
  excepción, cae al fallback con Pillow + :class:`PyPDF2.PdfMerger`.

La trampa del directorio temporal en OneDrive se maneja en el constructor:
las rutas configuradas que coincidan con variantes de ``./tmp`` se desvían
al directorio temporal del sistema.

Principio I de la Constitución: este módulo importa ``img2pdf``, ``PIL`` y
``PyPDF2`` — todos declarados en ``pyproject.toml``. Los modelos de dominio
se importan solo como tipos. Principio VIII: los logs identifican claves
operacionales (``txn_num``, ``file_path``, conteos de páginas) pero nunca
contenido de imágenes ni valores de metadatos.
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
from cmcourier.domain.ports import IAssembler

_log = logging.getLogger(__name__)


# Variantes de la trampa de OneDrive normalizadas para comparación case-insensitive.
_ONEDRIVE_TRAP_VARIANTS: frozenset[str] = frozenset({"tmp", "./tmp", "tmp/", ".\\tmp"})
_DIVERTED_DIR_NAME = "cmcourier_tmp"


def _default_image_type_map() -> dict[str, str]:
    """Mapeo: código image_type → hint MIME."""
    return {"B": "image/tiff", "O": "application/pdf", "C": "image/jpeg"}


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssemblerConfig:
    """Configuración para :class:`PdfAssembler`."""

    source_root: Path
    temp_dir: Path
    image_type_map: Mapping[str, str] = field(default_factory=_default_image_type_map)


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------


class PdfAssembler(IAssembler):
    """Implementación concreta de :class:`IAssembler` para la etapa S4."""

    def __init__(self, config: AssemblerConfig) -> None:
        self._cfg = config
        self.temp_dir = self._resolve_temp_dir(config.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------- API pública

    def assemble(self, document: RVABREPDocument) -> StagedFile:
        """Convierte *document* en un único PDF staged."""
        if document.is_pdf:
            return self._passthrough_native_pdf(document)
        return self._assemble_paged(document)

    # ----------------------------------------------------------- internos

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
        except Exception as primary:  # noqa: BLE001 — img2pdf levanta una superficie amplia
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
# Helpers a nivel de módulo
# ---------------------------------------------------------------------------


def _is_numeric_ext(text: str) -> bool:
    return bool(text) and text.isdigit()

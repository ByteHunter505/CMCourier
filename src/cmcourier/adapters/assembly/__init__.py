"""PDF assembly adapter: img2pdf fast path + Pillow/PyPDF2 fallback."""

from __future__ import annotations

from cmcourier.adapters.assembly.pdf_assembler import AssemblerConfig, PdfAssembler

__all__ = ["AssemblerConfig", "PdfAssembler"]

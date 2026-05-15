"""PDF assembly adapter: img2pdf fast path + Pillow/PyPDF2 fallback."""

from __future__ import annotations

from cmcourier.adapters.assembly.pdf_assembler import AssemblerConfig, PdfAssembler
from cmcourier.adapters.assembly.pool import build_s4_process_pool

__all__ = ["AssemblerConfig", "PdfAssembler", "build_s4_process_pool"]

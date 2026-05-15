"""Tipos compartidos del generador de archivos mock (031, REQ-006).

``FilePlan`` vive acá (no en :mod:`planner`) para que tanto el
planner como el content writer puedan importarlo sin generar un
ciclo de imports.
"""

from __future__ import annotations

__all__ = ["FileKind", "FilePlan"]

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

FileKind = Literal["pdf", "tiff", "jpeg"]


@dataclass(frozen=True, slots=True)
class FilePlan:
    """Un documento mock planeado en disco (REQ-006).

    Un plan PDF emite un único archivo (``extensions=(".PDF",)``).
    Un plan de imagen paginada (TIFF o JPEG) emite ``pages``
    archivos llamados ``<file_code>.001`` … ``<file_code>.<pages>``.
    """

    dir_path: Path
    file_code: str
    kind: FileKind
    pages: int
    size_min: int
    size_max: int
    extensions: tuple[str, ...]

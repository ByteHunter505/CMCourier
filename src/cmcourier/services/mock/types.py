"""Shared types for the mock file generator (031, REQ-006).

``FilePlan`` lives here (not in :mod:`planner`) so the planner and content
writer can both import it without creating an import cycle.
"""

from __future__ import annotations

__all__ = ["FileKind", "FilePlan"]

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

FileKind = Literal["pdf", "tiff", "jpeg"]


@dataclass(frozen=True, slots=True)
class FilePlan:
    """One planned mock document on disk (REQ-006).

    A PDF plan emits a single file (``extensions=(".PDF",)``). A paged-image
    plan (TIFF or JPEG) emits ``pages`` files named ``<file_code>.001`` …
    ``<file_code>.<pages>``.
    """

    dir_path: Path
    file_code: str
    kind: FileKind
    pages: int
    size_min: int
    size_max: int
    extensions: tuple[str, ...]

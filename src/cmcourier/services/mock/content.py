"""Valid mock-file byte generator (031, REQ-017..REQ-026).

``MockContentWriter`` produces real PDFs (via :mod:`img2pdf`), real TIFFs
(LZW-compressed via :mod:`PIL`), and real JPEGs (via :mod:`PIL`) targeting a
byte-count band. The S4 :class:`cmcourier.adapters.assembly.pdf_assembler.PdfAssembler`
must be able to re-open every file produced here without exceptions
(REBIRTH §7).

Size targeting is iterative, not closed-form: ``img2pdf`` × JPEG quality ×
LZW × pixel entropy is non-linear. The writer iterates the fixed spectrum in
:data:`_PROFILES_SMALL_TO_LARGE` and picks the attempt whose output falls
inside ``[plan.size_min, plan.size_max]``; if none lands in-band, the
closest-to-band attempt is written and a warning is logged.
"""

from __future__ import annotations

__all__ = ["MockContentWriter"]

import logging
import random
from io import BytesIO
from pathlib import Path

import img2pdf
from PIL import Image

from cmcourier.services.mock.types import FilePlan

_log = logging.getLogger(__name__)

_DEFAULT_TOLERANCE = 0.10

# (dims_wh, jpeg_quality, fill_mode). Ordered small → large output.
# fill_mode: "grey" = solid grey (low entropy, compresses well); "random" =
# full RGB noise (near-incompressible). Spectrum spans ~1 KB to ~40 MB
# across the three formats: dense granularity in the 5-200 KB band (the
# typical operator target) plus two large profiles (1500×1800 and
# 3000×3600 random RGB) for production-realistic banking scans — TIFFs at
# 300 DPI routinely run 5-15 MB per page in the real RVABREP corpus.
_PROFILES_SMALL_TO_LARGE: tuple[tuple[tuple[int, int], int, str], ...] = (
    ((100, 120), 30, "grey"),
    ((300, 400), 50, "grey"),
    ((80, 100), 70, "random"),
    ((200, 250), 80, "random"),
    ((500, 600), 90, "random"),
    # Intermediates filling the 2-10 MB gap (TIFF LZW barely compresses random
    # data, so size ≈ w × h × 3 bytes minus a small constant).
    ((800, 1000), 90, "random"),  # TIFF ≈ 2.3 MB
    ((1100, 1400), 91, "random"),  # TIFF ≈ 4.5 MB
    ((1500, 1800), 92, "random"),  # TIFF ≈ 10 MB
    ((2100, 2500), 93, "random"),  # TIFF ≈ 16 MB
    ((3000, 3600), 95, "random"),  # TIFF ≈ 42 MB
)


class MockContentWriter:
    """Write valid PDF/TIFF/JPEG bytes for a :class:`FilePlan`.

    ``seed=None`` uses system entropy; any integer (including ``0``) is a
    deterministic seed. ``tolerance`` is retained for reporting symmetry with
    the band check but is not the primary acceptance criterion: a result is
    accepted when it lands inside ``[plan.size_min, plan.size_max]``.
    """

    def __init__(
        self,
        seed: int | None = None,
        tolerance: float = _DEFAULT_TOLERANCE,
    ) -> None:
        self._rng = random.Random(seed)
        self._tolerance = tolerance

    # ------------------------------------------------------------------ public

    def write(self, plan: FilePlan, target_dir: Path, *, force: bool) -> list[Path]:
        """Create ``target_dir`` and write the plan's file(s).

        Returns the list of paths actually written, or ``[]`` if every target
        already existed and ``force`` is false (idempotent re-run).
        """
        target_dir.mkdir(parents=True, exist_ok=True)
        targets = [target_dir / f"{plan.file_code}{ext}" for ext in plan.extensions]
        if not force and all(t.exists() for t in targets):
            return []
        if plan.kind == "pdf":
            targets[0].write_bytes(self._build_pdf(plan))
        elif plan.kind == "tiff":
            for path in targets:
                path.write_bytes(self._build_image_bytes(plan, "TIFF"))
        elif plan.kind == "jpeg":
            for path in targets:
                path.write_bytes(self._build_image_bytes(plan, "JPEG"))
        else:  # pragma: no cover — planner enforces the kind union
            raise ValueError(f"unknown FilePlan.kind {plan.kind!r}")
        return targets

    # ----------------------------------------------------------------- builders

    def _build_pdf(self, plan: FilePlan) -> bytes:
        best_dist: int | None = None
        best_bytes: bytes = b""
        best_size = 0
        for dims, quality, fill in _PROFILES_SMALL_TO_LARGE:
            page_bytes = [self._render_jpeg_bytes(dims, quality, fill) for _ in range(plan.pages)]
            # nodate=True suppresses img2pdf's default datetime.now() stamps so
            # output is byte-deterministic for a fixed seed (REQ-024).
            pdf_bytes: bytes = img2pdf.convert(page_bytes, nodate=True)
            size = len(pdf_bytes)
            dist = _distance_to_band(size, plan)
            if dist == 0:
                return pdf_bytes
            if best_dist is None or dist < best_dist:
                best_dist, best_bytes, best_size = dist, pdf_bytes, size
        _log.warning(
            "pdf size best attempt outside band",
            extra={
                "best_size": best_size,
                "band": (plan.size_min, plan.size_max),
                "distance": best_dist,
            },
        )
        return best_bytes

    def _build_image_bytes(self, plan: FilePlan, fmt: str) -> bytes:
        best_dist: int | None = None
        best_bytes: bytes = b""
        best_size = 0
        for dims, quality, fill in _PROFILES_SMALL_TO_LARGE:
            buf = BytesIO()
            img = self._make_image(dims, fill)
            if fmt == "TIFF":
                img.save(buf, format="TIFF", compression="tiff_lzw")
            else:  # JPEG
                img.save(buf, format="JPEG", quality=quality)
            size = buf.tell()
            data = buf.getvalue()
            dist = _distance_to_band(size, plan)
            if dist == 0:
                return data
            if best_dist is None or dist < best_dist:
                best_dist, best_bytes, best_size = dist, data, size
        _log.warning(
            "%s size best attempt outside band",
            fmt.lower(),
            extra={
                "best_size": best_size,
                "band": (plan.size_min, plan.size_max),
                "distance": best_dist,
            },
        )
        return best_bytes

    # ------------------------------------------------------------------ helpers

    def _render_jpeg_bytes(
        self,
        dims: tuple[int, int],
        quality: int,
        fill: str,
    ) -> bytes:
        img = self._make_image(dims, fill)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    def _make_image(self, dims: tuple[int, int], fill: str) -> Image.Image:
        w, h = dims
        if fill == "grey":
            return Image.new("RGB", (w, h), (128, 128, 128))
        # "random" → near-incompressible pixel data.
        data = self._rng.randbytes(w * h * 3)
        return Image.frombytes("RGB", (w, h), data)


def _distance_to_band(size: int, plan: FilePlan) -> int:
    """Return 0 if ``size`` is inside ``[plan.size_min, plan.size_max]``,
    otherwise the byte distance to the nearest band edge.
    """
    if size < plan.size_min:
        return plan.size_min - size
    if size > plan.size_max:
        return size - plan.size_max
    return 0

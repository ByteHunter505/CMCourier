"""Generador de bytes válidos para archivos mock (031, REQ-017..REQ-026).

``MockContentWriter`` produce PDFs reales (vía :mod:`img2pdf`), TIFFs
reales (comprimidos `LZW` vía :mod:`PIL`) y JPEGs reales (vía
:mod:`PIL`) apuntando a una banda objetivo de bytes. El
:class:`cmcourier.adapters.assembly.pdf_assembler.PdfAssembler` de S4
tiene que poder reabrir sin excepciones cada archivo producido acá.

La búsqueda del tamaño es iterativa, no cerrada: ``img2pdf`` ×
calidad de JPEG × `LZW` × entropía de pixel no es lineal. El writer
itera el espectro fijo de :data:`_PROFILES_SMALL_TO_LARGE` y elige
el intento cuyo output cae dentro de ``[plan.size_min,
plan.size_max]``; si ninguno aterriza dentro de la banda, escribe
el intento más cercano y loguea un warning.
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

# ``(dims_wh, jpeg_quality, fill_mode)``. Ordenado de output chico a
# grande. ``fill_mode``: "grey" = gris sólido (baja entropía,
# comprime bien); "random" = ruido RGB completo (casi
# incomprimible). El espectro va de ~1 KB a ~40 MB entre los tres
# formatos: granularidad densa en la banda de 5-200 KB (el objetivo
# típico del operador) más dos perfiles grandes (1500×1800 y
# 3000×3600 RGB aleatorio) para escaneos bancarios realistas de
# producción: los TIFFs a 300 DPI rutinariamente pesan 5-15 MB por
# página en el corpus RVABREP real.
_PROFILES_SMALL_TO_LARGE: tuple[tuple[tuple[int, int], int, str], ...] = (
    ((100, 120), 30, "grey"),
    ((300, 400), 50, "grey"),
    ((80, 100), 70, "random"),
    ((200, 250), 80, "random"),
    ((500, 600), 90, "random"),
    # Intermedios que rellenan el gap de 2-10 MB (`TIFF LZW` casi no
    # comprime datos aleatorios, así que size ≈ w × h × 3 bytes menos
    # una constante chica).
    ((800, 1000), 90, "random"),  # TIFF ≈ 2.3 MB
    ((1100, 1400), 91, "random"),  # TIFF ≈ 4.5 MB
    ((1500, 1800), 92, "random"),  # TIFF ≈ 10 MB
    ((2100, 2500), 93, "random"),  # TIFF ≈ 16 MB
    ((3000, 3600), 95, "random"),  # TIFF ≈ 42 MB
)


class MockContentWriter:
    """Escribe bytes válidos de PDF/TIFF/JPEG para un :class:`FilePlan`.

    ``seed=None`` usa la entropía del sistema; cualquier entero
    (incluido ``0``) es una `seed` determinista. ``tolerance`` se
    conserva por simetría de reporte con el chequeo de banda, pero
    no es el criterio primario de aceptación: un resultado se acepta
    cuando aterriza dentro de ``[plan.size_min, plan.size_max]``.
    """

    def __init__(
        self,
        seed: int | None = None,
        tolerance: float = _DEFAULT_TOLERANCE,
    ) -> None:
        self._rng = random.Random(seed)
        self._tolerance = tolerance

    # ------------------------------------------------------------------ público

    def write(self, plan: FilePlan, target_dir: Path, *, force: bool) -> list[Path]:
        """Crea ``target_dir`` y escribe el o los archivos del plan.

        Devuelve la lista de paths efectivamente escritos, o ``[]`` si
        cada destino ya existía y ``force`` es ``False`` (re-ejecución
        idempotente).
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
        else:  # pragma: no cover — el planner garantiza la unión de kinds
            raise ValueError(f"unknown FilePlan.kind {plan.kind!r}")
        return targets

    # ----------------------------------------------------------------- constructores

    def _build_pdf(self, plan: FilePlan) -> bytes:
        best_dist: int | None = None
        best_bytes: bytes = b""
        best_size = 0
        for dims, quality, fill in _PROFILES_SMALL_TO_LARGE:
            page_bytes = [self._render_jpeg_bytes(dims, quality, fill) for _ in range(plan.pages)]
            # ``nodate=True`` suprime los timestamps ``datetime.now()``
            # que img2pdf agrega por defecto, de modo que el output
            # sea byte-determinista para una `seed` fija (REQ-024).
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
        # "random" → datos de pixel casi incomprimibles.
        data = self._rng.randbytes(w * h * 3)
        return Image.frombytes("RGB", (w, h), data)


def _distance_to_band(size: int, plan: FilePlan) -> int:
    """Devuelve 0 si ``size`` está dentro de
    ``[plan.size_min, plan.size_max]``, en otro caso la distancia en
    bytes al borde más cercano de la banda.
    """
    if size < plan.size_min:
        return plan.size_min - size
    if size > plan.size_max:
        return size - plan.size_max
    return 0

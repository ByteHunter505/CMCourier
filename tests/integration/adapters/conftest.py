"""Generador de `fixtures` binarios para los tests de ensamblado de PDFs.

`fixture` con `scope=session` y `autouse` que materializa las entradas
TIFF / JPEG / PDF de prueba bajo ``tests/fixtures/assembly/``. La
generación es idempotente (saltea los archivos que ya existen) y
determinística (imágenes chiquitas de tamaño fijo con colores
hardcodeados). Los binarios resultantes están en `.gitignore`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ASSEMBLY_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "assembly"

# Colores distintos por página para que un chequeo visual aguas abajo
# (no incluido en esta suite) pueda distinguirlas.
_PAGE_COLORS = [
    (220, 20, 20),
    (20, 220, 20),
    (20, 20, 220),
    (220, 220, 20),
    (220, 20, 220),
]


@pytest.fixture(scope="session", autouse=True)
def _generate_assembly_fixtures() -> None:
    """Materializa todos los `fixtures` binarios que necesitan los tests de ensamblado."""
    from PIL import Image  # import perezoso para que las corridas no relacionadas sigan baratas

    _generate_native_pdf(Image)
    _generate_paged_tiff(Image)
    _generate_paged_jpeg(Image)
    _generate_variable_padding(Image)
    _generate_paged_mismatch(Image)
    _generate_with_unrelated_pdf(Image)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _make_image(image_mod: object, color_index: int, size: tuple[int, int] = (64, 64)) -> object:
    color = _PAGE_COLORS[color_index % len(_PAGE_COLORS)]
    return image_mod.new("RGB", size, color=color)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Generadores (uno por sub-árbol de `fixture`)
# ---------------------------------------------------------------------------


def _generate_native_pdf(image_mod: object) -> None:
    target_dir = _ensure_dir(_ASSEMBLY_FIXTURES / "native_pdf" / "PROD" / "2025" / "11" / "17")
    target = target_dir / "0AAAUI0K.PDF"
    if target.exists():
        return
    img = _make_image(image_mod, 0)
    img.save(target, format="PDF")  # type: ignore[attr-defined]


def _generate_paged_tiff(image_mod: object) -> None:
    target_dir = _ensure_dir(_ASSEMBLY_FIXTURES / "paged_tiff" / "PROD" / "2025" / "11" / "17")
    for n in (1, 2, 3):
        target = target_dir / f"DAAAH9X4.{n:03d}"
        if target.exists():
            continue
        img = _make_image(image_mod, n - 1)
        img.save(target, format="TIFF")  # type: ignore[attr-defined]


def _generate_paged_jpeg(image_mod: object) -> None:
    target_dir = _ensure_dir(_ASSEMBLY_FIXTURES / "paged_jpeg" / "PROD" / "2025" / "11" / "17")
    for n in (1, 2):
        target = target_dir / f"DBBBI0L5.{n:03d}"
        if target.exists():
            continue
        img = _make_image(image_mod, n - 1)
        img.save(target, format="JPEG")  # type: ignore[attr-defined]


def _generate_variable_padding(image_mod: object) -> None:
    target_dir = _ensure_dir(
        _ASSEMBLY_FIXTURES / "variable_padding" / "PROD" / "2025" / "01" / "01"
    )
    # .1, .2, .10 — el orden lexicográfico los pondría [1, 10, 2]; el
    # `assembler` TIENE QUE normalizar vía int(ext).
    for ext in ("1", "2", "10"):
        target = target_dir / f"DCCCH9X4.{ext}"
        if target.exists():
            continue
        img = _make_image(image_mod, int(ext) % len(_PAGE_COLORS))
        img.save(target, format="TIFF")  # type: ignore[attr-defined]


def _generate_paged_mismatch(image_mod: object) -> None:
    # 3 páginas en disco, pero el test va a declarar total_pages=5.
    target_dir = _ensure_dir(_ASSEMBLY_FIXTURES / "paged_mismatch" / "PROD" / "2025" / "11" / "17")
    for n in (1, 2, 3):
        target = target_dir / f"DEEEH9X4.{n:03d}"
        if target.exists():
            continue
        img = _make_image(image_mod, n - 1)
        img.save(target, format="TIFF")  # type: ignore[attr-defined]


def _generate_with_unrelated_pdf(image_mod: object) -> None:
    target_dir = _ensure_dir(
        _ASSEMBLY_FIXTURES / "with_unrelated_pdf" / "PROD" / "2025" / "11" / "17"
    )
    for n in (1, 2):
        target = target_dir / f"DFFFH9X4.{n:03d}"
        if target.exists():
            continue
        img = _make_image(image_mod, n - 1)
        img.save(target, format="TIFF")  # type: ignore[attr-defined]
    unrelated = target_dir / "OTHER.PDF"
    if not unrelated.exists():
        img = _make_image(image_mod, 4)
        img.save(unrelated, format="PDF")  # type: ignore[attr-defined]

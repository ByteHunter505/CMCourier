"""Binary fixture generator for the PDF assembly tests.

Session-scoped autouse fixture that materializes the TIFF / JPEG / PDF
test inputs under ``tests/fixtures/assembly/``. Generation is idempotent
(skips files that already exist) and deterministic (small fixed-size
images with hardcoded colors). The resulting binaries are gitignored.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ASSEMBLY_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "assembly"

# Distinct colors per page so a downstream visual check (not in this suite)
# can tell pages apart.
_PAGE_COLORS = [
    (220, 20, 20),
    (20, 220, 20),
    (20, 20, 220),
    (220, 220, 20),
    (220, 20, 220),
]


@pytest.fixture(scope="session", autouse=True)
def _generate_assembly_fixtures() -> None:
    """Materialize every binary fixture the assembly tests need."""
    from PIL import Image  # imported lazily so unrelated test runs stay cheap

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
# Generators (one per fixture sub-tree)
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
    # .1, .2, .10 — lexical sort would order them [1, 10, 2]; the assembler
    # MUST normalize via int(ext).
    for ext in ("1", "2", "10"):
        target = target_dir / f"DCCCH9X4.{ext}"
        if target.exists():
            continue
        img = _make_image(image_mod, int(ext) % len(_PAGE_COLORS))
        img.save(target, format="TIFF")  # type: ignore[attr-defined]


def _generate_paged_mismatch(image_mod: object) -> None:
    # 3 pages on disk, but the test will claim total_pages=5.
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

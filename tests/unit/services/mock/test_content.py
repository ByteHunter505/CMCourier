"""Unit tests for ``cmcourier.services.mock.content.MockContentWriter`` (031, REQ-017..REQ-026)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image
from PyPDF2 import PdfReader

from cmcourier.services.mock.content import MockContentWriter
from cmcourier.services.mock.types import FilePlan


def _pdf_plan(pages: int, dir_path: Path, *, code: str = "DOC001") -> FilePlan:
    return FilePlan(
        dir_path=dir_path,
        file_code=code,
        kind="pdf",
        pages=pages,
        size_min=10 * 1024,
        size_max=80 * 1024,
        extensions=(".PDF",),
    )


def _tiff_plan(pages: int, dir_path: Path, *, code: str = "IMG001") -> FilePlan:
    return FilePlan(
        dir_path=dir_path,
        file_code=code,
        kind="tiff",
        pages=pages,
        size_min=2 * 1024,
        size_max=30 * 1024,
        extensions=tuple(f".{i:03d}" for i in range(1, pages + 1)),
    )


def _jpeg_plan(pages: int, dir_path: Path, *, code: str = "JPG001") -> FilePlan:
    return FilePlan(
        dir_path=dir_path,
        file_code=code,
        kind="jpeg",
        pages=pages,
        size_min=2 * 1024,
        size_max=30 * 1024,
        extensions=tuple(f".{i:03d}" for i in range(1, pages + 1)),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestPdf:
    def test_pdf_pages_matches_plan(self, tmp_path: Path) -> None:
        writer = MockContentWriter(seed=1)
        plan = _pdf_plan(3, tmp_path)
        written = writer.write(plan, tmp_path, force=False)
        assert len(written) == 1
        reader = PdfReader(str(written[0]))
        assert len(reader.pages) == 3

    @pytest.mark.parametrize("pages", [1, 2, 5])
    def test_pdf_re_openable_pypdf2(self, tmp_path: Path, pages: int) -> None:
        writer = MockContentWriter(seed=1)
        plan = _pdf_plan(pages, tmp_path, code=f"DOC{pages}")
        written = writer.write(plan, tmp_path, force=False)
        reader = PdfReader(str(written[0]))
        assert len(reader.pages) == pages

    def test_pdf_size_within_band(self, tmp_path: Path) -> None:
        """REQ-023: best-effort size targeting. Each written file should
        either land in the plan's [size_min, size_max] band or be the closest
        achievable to that band given the 5 profile attempts."""
        writer = MockContentWriter(seed=1)
        sizes: list[int] = []
        for i in range(5):
            plan = _pdf_plan(2, tmp_path, code=f"BAND{i}")
            (written,) = writer.write(plan, tmp_path, force=True)
            sizes.append(written.stat().st_size)
        # At least 3 of 5 runs should land within the band (the rest within
        # ±100% of the band edge as the closest-to-band fallback).
        band_min = 10 * 1024
        band_max = 80 * 1024
        in_band = [s for s in sizes if band_min <= s <= band_max]
        assert len(in_band) >= 3, (
            f"only {len(in_band)}/5 runs landed in [{band_min}, {band_max}]; sizes={sizes}"
        )


class TestPaged:
    def test_tiff_is_lzw(self, tmp_path: Path) -> None:
        writer = MockContentWriter(seed=1)
        plan = _tiff_plan(2, tmp_path)
        written = writer.write(plan, tmp_path, force=False)
        assert len(written) == 2
        for p in written:
            with Image.open(p) as img:
                # TIFF tag 259 = Compression; value 5 = LZW per TIFF spec.
                assert img.format == "TIFF"
                assert img.tag_v2[259] == 5  # type: ignore[attr-defined]

    def test_jpeg_re_openable(self, tmp_path: Path) -> None:
        writer = MockContentWriter(seed=1)
        plan = _jpeg_plan(3, tmp_path)
        written = writer.write(plan, tmp_path, force=False)
        assert len(written) == 3
        for p in written:
            with Image.open(p) as img:
                assert img.format == "JPEG"

    def test_extensions_zero_padded(self, tmp_path: Path) -> None:
        writer = MockContentWriter(seed=1)
        plan = _tiff_plan(3, tmp_path)
        written = writer.write(plan, tmp_path, force=False)
        suffixes = sorted(p.suffix for p in written)
        assert suffixes == [".001", ".002", ".003"]


class TestDeterminism:
    def test_same_seed_byte_identical(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        writer_a = MockContentWriter(seed=42)
        writer_b = MockContentWriter(seed=42)
        plan_a = _pdf_plan(2, dir_a, code="DET")
        plan_b = _pdf_plan(2, dir_b, code="DET")
        (out_a,) = writer_a.write(plan_a, dir_a, force=False)
        (out_b,) = writer_b.write(plan_b, dir_b, force=False)
        assert _sha256(out_a) == _sha256(out_b)


class TestIdempotency:
    def test_skip_if_exists_returns_empty(self, tmp_path: Path) -> None:
        writer = MockContentWriter(seed=1)
        plan = _jpeg_plan(2, tmp_path)
        writer.write(plan, tmp_path, force=False)
        first_mtimes = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir() if p.is_file()}
        written_again = writer.write(plan, tmp_path, force=False)
        assert written_again == []
        second_mtimes = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir() if p.is_file()}
        assert first_mtimes == second_mtimes

    def test_force_overwrites(self, tmp_path: Path) -> None:
        plan = _jpeg_plan(1, tmp_path)
        (tmp_path / f"{plan.file_code}.001").write_bytes(b"sentinel")
        writer = MockContentWriter(seed=1)
        written = writer.write(plan, tmp_path, force=True)
        assert len(written) == 1
        assert (tmp_path / f"{plan.file_code}.001").read_bytes() != b"sentinel"
        with Image.open(written[0]) as img:
            assert img.format == "JPEG"

"""Integration tests for :class:`PdfAssembler`.

Exercises the adapter against real binary fixtures (TIFF / JPEG / PDF)
generated at session start by ``conftest.py``. No mocking of img2pdf or
Pillow — Constitution Principle VI. The single monkey-patched scenario
forces the fallback path by replacing ``img2pdf.convert`` to raise; the
fallback then runs against real Pillow + PyPDF2.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from PyPDF2 import PdfReader

from cmcourier.adapters.assembly import AssemblerConfig, PdfAssembler
from cmcourier.domain.exceptions import PDFAssemblyFailedError, SourceFileMissingError
from cmcourier.domain.models import RVABREPDocument

pytestmark = pytest.mark.integration

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "assembly"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(
    file_name: str,
    image_path: str,
    total_pages: int,
    txn_num: str = "TXN0000001",
    **overrides: object,
) -> RVABREPDocument:
    """Build a synthetic :class:`RVABREPDocument` for a specific fixture layout."""
    defaults: dict[str, object] = {
        "system_code": "1",
        "txn_num": txn_num,
        "index1": "TESTUSER001",
        "index2": "000000",
        "index3": "",
        "index4": "",
        "index5": "",
        "index6": "",
        "index7": "FF17",
        "image_type": "B",
        "image_path": image_path,
        "file_name": file_name,
        "creation_date": datetime(2025, 11, 17),
        "last_view_date": None,
        "total_pages": total_pages,
        "delete_code": "",
    }
    defaults.update(overrides)
    return RVABREPDocument(**defaults)  # type: ignore[arg-type]


def _config(tmp_path: Path, *, source_root: Path | None = None) -> AssemblerConfig:
    return AssemblerConfig(
        source_root=source_root or _FIXTURES,
        temp_dir=tmp_path / "staging",
    )


# ---------------------------------------------------------------------------
# Group 1 — Construction & temp dir
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_construction_creates_temp_dir(self, tmp_path: Path) -> None:
        cfg = AssemblerConfig(source_root=_FIXTURES, temp_dir=tmp_path / "fresh_dir")
        PdfAssembler(cfg)
        assert (tmp_path / "fresh_dir").is_dir()

    def test_onedrive_trap_diverts_to_system_temp(self) -> None:
        cfg = AssemblerConfig(source_root=_FIXTURES, temp_dir=Path("./tmp"))
        assembler = PdfAssembler(cfg)
        expected = Path(tempfile.gettempdir()) / "cmcourier_tmp"
        assert assembler.temp_dir == expected
        assert expected.is_dir()

    def test_default_image_type_map_matches_rebirth(self) -> None:
        cfg = AssemblerConfig(source_root=_FIXTURES, temp_dir=Path(tempfile.gettempdir()))
        assert cfg.image_type_map == {
            "B": "image/tiff",
            "O": "application/pdf",
            "C": "image/jpeg",
        }


# ---------------------------------------------------------------------------
# Group 2 — Native PDF passthrough
# ---------------------------------------------------------------------------


class TestNativePdfPassthrough:
    def test_native_pdf_copied_to_temp(self, tmp_path: Path) -> None:
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="0AAAUI0K.PDF",
            image_path="native_pdf/PROD/2025/11/17",
            total_pages=1,
            txn_num="TXN0000001",
        )
        staged = assembler.assemble(doc)
        assert staged.path == tmp_path / "staging" / "TXN0000001.pdf"
        assert staged.path.is_file()
        assert staged.size_bytes > 0
        assert staged.path.read_bytes()[:5] == b"%PDF-"

    def test_native_pdf_missing_raises(self, tmp_path: Path) -> None:
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="NOPE.PDF",
            image_path="native_pdf/PROD/2025/11/17",
            total_pages=1,
        )
        with pytest.raises(SourceFileMissingError):
            assembler.assemble(doc)

    def test_native_pdf_page_count_from_doc(self, tmp_path: Path) -> None:
        # Even if Pillow's PDF would say 1 page, we trust doc.total_pages.
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="0AAAUI0K.PDF",
            image_path="native_pdf/PROD/2025/11/17",
            total_pages=7,  # arbitrary value
            txn_num="TXN0000002",
        )
        staged = assembler.assemble(doc)
        assert staged.page_count == 7


# ---------------------------------------------------------------------------
# Group 3 — Paged-document assembly happy path
# ---------------------------------------------------------------------------


class TestPagedAssembly:
    def test_paged_tiff_assembly(self, tmp_path: Path) -> None:
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DAAAH9X4.001",
            image_path="paged_tiff/PROD/2025/11/17",
            total_pages=3,
            txn_num="TXN0000010",
        )
        staged = assembler.assemble(doc)
        assert staged.page_count == 3
        reader = PdfReader(str(staged.path))
        assert len(reader.pages) == 3

    def test_paged_jpeg_assembly(self, tmp_path: Path) -> None:
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DBBBI0L5.001",
            image_path="paged_jpeg/PROD/2025/11/17",
            total_pages=2,
            txn_num="TXN0000011",
        )
        staged = assembler.assemble(doc)
        assert staged.page_count == 2
        reader = PdfReader(str(staged.path))
        assert len(reader.pages) == 2

    def test_variable_padding_sorted_numerically(self, tmp_path: Path) -> None:
        # Pages on disk: .1, .2, .10 — lexical sort would order [1, 10, 2].
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DCCCH9X4.1",
            image_path="variable_padding/PROD/2025/01/01",
            total_pages=3,
            txn_num="TXN0000012",
        )
        staged = assembler.assemble(doc)
        assert staged.page_count == 3
        reader = PdfReader(str(staged.path))
        assert len(reader.pages) == 3

    def test_glob_excludes_unrelated_pdf(self, tmp_path: Path) -> None:
        # Same directory holds 2 paged TIFFs AND an unrelated OTHER.PDF.
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DFFFH9X4.001",
            image_path="with_unrelated_pdf/PROD/2025/11/17",
            total_pages=2,
            txn_num="TXN0000013",
        )
        staged = assembler.assemble(doc)
        assert staged.page_count == 2  # not 3 — OTHER.PDF excluded


# ---------------------------------------------------------------------------
# Group 4 — Page-count mismatch
# ---------------------------------------------------------------------------


class TestPageCountMismatch:
    def test_mismatch_emits_warning(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        # 3 pages on disk, doc claims 5.
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DEEEH9X4.001",
            image_path="paged_mismatch/PROD/2025/11/17",
            total_pages=5,
            txn_num="TXN0000020",
        )
        with caplog.at_level(logging.WARNING, logger="cmcourier.adapters.assembly.pdf_assembler"):
            staged = assembler.assemble(doc)
        assert staged.page_count == 3  # filesystem wins
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            r.__dict__.get("expected") == 5 and r.__dict__.get("discovered") == 3 for r in warnings
        )


# ---------------------------------------------------------------------------
# Group 5 — Source-files missing
# ---------------------------------------------------------------------------


class TestSourceFilesMissing:
    def test_no_pages_raises(self, tmp_path: Path) -> None:
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="ZZZZZZZZ.001",
            image_path="paged_tiff/PROD/2025/11/17",  # dir exists, file_code doesn't
            total_pages=1,
        )
        with pytest.raises(SourceFileMissingError):
            assembler.assemble(doc)


# ---------------------------------------------------------------------------
# Group 6 — Fallback path (monkey-patch img2pdf)
# ---------------------------------------------------------------------------


class TestFallbackPath:
    def test_img2pdf_failure_routes_to_fallback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from cmcourier.adapters.assembly import pdf_assembler as module

        def _boom(*_args: object, **_kw: object) -> bytes:
            raise RuntimeError("simulated img2pdf failure")

        monkeypatch.setattr(module.img2pdf, "convert", _boom)
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DAAAH9X4.001",
            image_path="paged_tiff/PROD/2025/11/17",
            total_pages=3,
            txn_num="TXN0000030",
        )
        with caplog.at_level(logging.INFO, logger="cmcourier.adapters.assembly.pdf_assembler"):
            staged = assembler.assemble(doc)
        assert staged.page_count == 3
        reader = PdfReader(str(staged.path))
        assert len(reader.pages) == 3
        # INFO log records the fast-path failure (message says "falling back").
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("img2pdf" in r.getMessage().lower() for r in info_records)
        assert any("falling back" in r.getMessage().lower() for r in info_records)

    def test_fallback_produces_valid_pdf_header(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from cmcourier.adapters.assembly import pdf_assembler as module

        monkeypatch.setattr(
            module.img2pdf,
            "convert",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("forced")),
        )
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DBBBI0L5.001",
            image_path="paged_jpeg/PROD/2025/11/17",
            total_pages=2,
            txn_num="TXN0000031",
        )
        staged = assembler.assemble(doc)
        assert staged.path.read_bytes()[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# Group 7 — Both paths fail
# ---------------------------------------------------------------------------


class TestBothPathsFail:
    def test_both_paths_failing_raise_assembly_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from cmcourier.adapters.assembly import pdf_assembler as module

        # Force img2pdf and the fallback to both fail.
        monkeypatch.setattr(
            module.img2pdf,
            "convert",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("img2pdf boom")),
        )

        class _BoomImage:
            @staticmethod
            def open(*_a: object, **_kw: object) -> object:
                raise RuntimeError("pillow boom")

        monkeypatch.setattr(module.Image, "open", _BoomImage.open)
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DAAAH9X4.001",
            image_path="paged_tiff/PROD/2025/11/17",
            total_pages=3,
            txn_num="TXN0000040",
        )
        with pytest.raises(PDFAssemblyFailedError) as ei:
            assembler.assemble(doc)
        assert ei.value.txn_num == "TXN0000040"


# ---------------------------------------------------------------------------
# Group 8 — Output validation (deeper PyPDF2 inspection)
# ---------------------------------------------------------------------------


class TestOutputValidation:
    def test_output_starts_with_pdf_header(self, tmp_path: Path) -> None:
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DAAAH9X4.001",
            image_path="paged_tiff/PROD/2025/11/17",
            total_pages=3,
            txn_num="TXN0000050",
        )
        staged = assembler.assemble(doc)
        assert staged.path.read_bytes()[:5] == b"%PDF-"

    def test_output_page_count_matches_disk(self, tmp_path: Path) -> None:
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DAAAH9X4.001",
            image_path="paged_tiff/PROD/2025/11/17",
            total_pages=3,
            txn_num="TXN0000051",
        )
        staged = assembler.assemble(doc)
        reader = PdfReader(str(staged.path))
        assert len(reader.pages) == staged.page_count == 3


# ---------------------------------------------------------------------------
# Group 9 — Logging discipline (Constitution VIII)
# ---------------------------------------------------------------------------


class TestLoggingDiscipline:
    def test_mismatch_warning_does_not_leak_image_bytes(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DEEEH9X4.001",
            image_path="paged_mismatch/PROD/2025/11/17",
            total_pages=5,
            txn_num="TXN0000060",
        )
        with caplog.at_level(logging.WARNING, logger="cmcourier.adapters.assembly.pdf_assembler"):
            assembler.assemble(doc)
        # The WARNING must carry txn_num and counts, never raw bytes.
        for record in caplog.records:
            message = record.getMessage()
            # No b'...' literals or huge integer dumps.
            assert "\\x" not in message
            assert "b'%" not in message

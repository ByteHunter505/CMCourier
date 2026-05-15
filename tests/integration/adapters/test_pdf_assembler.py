"""Tests de integración para :class:`PdfAssembler`.

Ejercita el adapter contra `fixtures` binarios reales (TIFF / JPEG / PDF)
generados al inicio de la sesión por ``conftest.py``. Sin `mockear`
img2pdf ni Pillow — Principio VI de la Constitución. El único escenario
con `monkey-patch` fuerza el camino de fallback reemplazando
``img2pdf.convert`` para que levante; el fallback después corre contra
Pillow + PyPDF2 reales.
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
    """Arma un :class:`RVABREPDocument` sintético para un layout de `fixture` dado."""
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
# Grupo 1 — Construcción y directorio temporal
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

    def test_default_image_type_map_matches_canonical_codes(self) -> None:
        cfg = AssemblerConfig(source_root=_FIXTURES, temp_dir=Path(tempfile.gettempdir()))
        assert cfg.image_type_map == {
            "B": "image/tiff",
            "O": "application/pdf",
            "C": "image/jpeg",
        }


# ---------------------------------------------------------------------------
# Grupo 2 — `Passthrough` de PDF nativo
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
        # Aunque el PDF de Pillow dijera 1 página, confiamos en doc.total_pages.
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="0AAAUI0K.PDF",
            image_path="native_pdf/PROD/2025/11/17",
            total_pages=7,  # valor arbitrario
            txn_num="TXN0000002",
        )
        staged = assembler.assemble(doc)
        assert staged.page_count == 7


# ---------------------------------------------------------------------------
# Grupo 3 — Happy path de ensamblado de documento paginado
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
        # Páginas en disco: .1, .2, .10 — el orden lexicográfico daría [1, 10, 2].
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
        # El mismo directorio tiene 2 TIFFs paginados Y un OTHER.PDF no relacionado.
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DFFFH9X4.001",
            image_path="with_unrelated_pdf/PROD/2025/11/17",
            total_pages=2,
            txn_num="TXN0000013",
        )
        staged = assembler.assemble(doc)
        assert staged.page_count == 2  # no 3 — OTHER.PDF queda excluido


# ---------------------------------------------------------------------------
# Grupo 4 — Mismatch de cantidad de páginas
# ---------------------------------------------------------------------------


class TestPageCountMismatch:
    def test_mismatch_emits_warning(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        # 3 páginas en disco, el doc declara 5.
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="DEEEH9X4.001",
            image_path="paged_mismatch/PROD/2025/11/17",
            total_pages=5,
            txn_num="TXN0000020",
        )
        with caplog.at_level(logging.WARNING, logger="cmcourier.adapters.assembly.pdf_assembler"):
            staged = assembler.assemble(doc)
        assert staged.page_count == 3  # gana el filesystem
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            r.__dict__.get("expected") == 5 and r.__dict__.get("discovered") == 3 for r in warnings
        )


# ---------------------------------------------------------------------------
# Grupo 5 — Source files faltantes
# ---------------------------------------------------------------------------


class TestSourceFilesMissing:
    def test_no_pages_raises(self, tmp_path: Path) -> None:
        assembler = PdfAssembler(_config(tmp_path))
        doc = _make_doc(
            file_name="ZZZZZZZZ.001",
            image_path="paged_tiff/PROD/2025/11/17",  # el dir existe, el file_code no
            total_pages=1,
        )
        with pytest.raises(SourceFileMissingError):
            assembler.assemble(doc)


# ---------------------------------------------------------------------------
# Grupo 6 — Camino de fallback (monkey-patch a img2pdf)
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
        # El log INFO registra la falla del fast-path (el mensaje dice "falling back").
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
# Grupo 7 — Fallan los dos caminos
# ---------------------------------------------------------------------------


class TestBothPathsFail:
    def test_both_paths_failing_raise_assembly_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from cmcourier.adapters.assembly import pdf_assembler as module

        # Fuerza a que fallen tanto img2pdf como el fallback.
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
# Grupo 8 — Validación de output (inspección más profunda con PyPDF2)
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
# Grupo 9 — Disciplina de logging (Principio VIII de la Constitución)
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
        # El WARNING tiene que llevar txn_num y contadores, nunca bytes crudos.
        for record in caplog.records:
            message = record.getMessage()
            # Sin literales b'...' ni dumps gigantes de enteros.
            assert "\\x" not in message
            assert "b'%" not in message


# ---------------------------------------------------------------------------
# Grupo 10 — Conformidad del port (019, Principio I de la Constitución)
# ---------------------------------------------------------------------------


class TestPortConformance:
    def test_pdf_assembler_is_iassembler(self, tmp_path: Path) -> None:
        from cmcourier.domain.ports import IAssembler

        assembler = PdfAssembler(_config(tmp_path))
        assert isinstance(assembler, IAssembler)

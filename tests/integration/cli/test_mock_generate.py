"""Tests de integración para ``cmcourier mock generate`` (031, REQ-034)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from textwrap import dedent

import pytest
from click.testing import CliRunner
from PIL import Image
from PyPDF2 import PdfReader

from cmcourier.cli.app import main

pytestmark = pytest.mark.integration


_FIXTURE_CSV = dedent(
    """\
    ABABCD,ABAACD,ABACST,ABAANB,ABACCD,ABADCD,ABAECD,ABAFCD,ABAGCD,ABAHCD,ABABST,ABAICD,ABAJCD,ABAADT,ABABDT,ABABUN
    SH1,SYS,,TXN001,c1,d1,e1,f1,g1,RVI1,O,docs/2024/pdf,DOC001.PDF,1240101,,2
    SH2,SYS,,TXN002,c2,d2,e2,f2,g2,RVI1,B,docs/2024/tif,IMG001.001,1240101,,3
    SH3,SYS,,TXN003,c3,d3,e3,f3,g3,RVI1,C,docs/2024/jpg,JPG001.001,1240101,,1
    """
)


@pytest.fixture
def fixture_csv(tmp_path: Path) -> Path:
    p = tmp_path / "rvabrep.csv"
    p.write_text(_FIXTURE_CSV, encoding="utf-8")
    return p


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _invoke(*args: str) -> tuple[int, str, str]:
    runner = CliRunner()
    result = runner.invoke(main, list(args), catch_exceptions=False)
    return result.exit_code, result.stdout, result.stderr


class TestHappyPath:
    def test_decodable_files_under_root(self, fixture_csv: Path, tmp_path: Path) -> None:
        root = tmp_path / "out"
        code, stdout, _ = _invoke(
            "mock",
            "generate",
            "--rvabrep-csv",
            str(fixture_csv),
            "--root",
            str(root),
            "--pdf-min",
            "10kb",
            "--pdf-max",
            "100kb",
            "--img-min",
            "2kb",
            "--img-max",
            "30kb",
            "--seed",
            "1",
        )
        assert code == 0, stdout

        pdf = root / "docs/2024/pdf/DOC001.PDF"
        tif1 = root / "docs/2024/tif/IMG001.001"
        tif2 = root / "docs/2024/tif/IMG001.002"
        tif3 = root / "docs/2024/tif/IMG001.003"
        jpg1 = root / "docs/2024/jpg/JPG001.001"

        # Los archivos existen.
        for p in [pdf, tif1, tif2, tif3, jpg1]:
            assert p.is_file(), f"falta {p}"

        # El PDF se abre con la cantidad correcta de páginas.
        reader = PdfReader(str(pdf))
        assert len(reader.pages) == 2

        # TIFFs decodificables.
        for p in [tif1, tif2, tif3]:
            with Image.open(p) as img:
                assert img.format == "TIFF"

        # JPEG decodificable.
        with Image.open(jpg1) as img:
            assert img.format == "JPEG"

        # La línea de resumen se emitió.
        assert "wrote" in stdout
        assert "5" in stdout  # se crearon 5 archivos


class TestDryRun:
    def test_dry_run_writes_nothing_and_lists_plans(
        self, fixture_csv: Path, tmp_path: Path
    ) -> None:
        root = tmp_path / "out"
        code, stdout, _ = _invoke(
            "mock",
            "generate",
            "--rvabrep-csv",
            str(fixture_csv),
            "--root",
            str(root),
            "--pdf-min",
            "10kb",
            "--pdf-max",
            "100kb",
            "--img-min",
            "2kb",
            "--img-max",
            "30kb",
            "--dry-run",
        )
        assert code == 0
        # Tres planes (1 fila pdf, 1 fila tiff, 1 fila jpeg).
        plan_lines = [line for line in stdout.splitlines() if line.startswith("[plan]")]
        # 5 archivos = 1 PDF + 3 páginas TIFF + 1 JPEG (una línea [plan] por archivo).
        assert len(plan_lines) == 5
        # El root o no existe O está vacío.
        if root.exists():
            assert not any(root.rglob("*")), "el dry-run escribió archivos"


class TestDeterminism:
    def test_seed_byte_identical_across_runs(self, fixture_csv: Path, tmp_path: Path) -> None:
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        common_args = (
            "--rvabrep-csv",
            str(fixture_csv),
            "--pdf-min",
            "10kb",
            "--pdf-max",
            "100kb",
            "--img-min",
            "2kb",
            "--img-max",
            "30kb",
            "--seed",
            "42",
        )
        code_a, _, _ = _invoke("mock", "generate", "--root", str(root_a), *common_args)
        code_b, _, _ = _invoke("mock", "generate", "--root", str(root_b), *common_args)
        assert code_a == 0 and code_b == 0

        files_a = sorted(p for p in root_a.rglob("*") if p.is_file())
        files_b = sorted(p for p in root_b.rglob("*") if p.is_file())
        assert len(files_a) == len(files_b) == 5

        for fa, fb in zip(files_a, files_b, strict=True):
            assert fa.relative_to(root_a) == fb.relative_to(root_b)
            assert _sha256(fa) == _sha256(fb), f"`mismatch` en {fa.name}"


class TestValidationErrors:
    def test_pdf_band_inverted_exits_2(self, fixture_csv: Path, tmp_path: Path) -> None:
        code, _, stderr = _invoke(
            "mock",
            "generate",
            "--rvabrep-csv",
            str(fixture_csv),
            "--root",
            str(tmp_path / "out"),
            "--pdf-min",
            "200kb",
            "--pdf-max",
            "100kb",
            "--img-min",
            "2kb",
            "--img-max",
            "30kb",
        )
        assert code == 2
        assert "pdf-min" in stderr.lower() or "pdf_min" in stderr.lower()

    def test_no_source_exits_2(self, tmp_path: Path) -> None:
        code, _, stderr = _invoke(
            "mock",
            "generate",
            "--root",
            str(tmp_path / "out"),
            "--pdf-min",
            "10kb",
            "--pdf-max",
            "100kb",
            "--img-min",
            "2kb",
            "--img-max",
            "30kb",
        )
        assert code == 2
        assert "source" in stderr.lower() or "rvabrep" in stderr.lower()

    def test_both_sources_exit_2(self, fixture_csv: Path, tmp_path: Path) -> None:
        code, _, stderr = _invoke(
            "mock",
            "generate",
            "--rvabrep-csv",
            str(fixture_csv),
            "--rvabrep-as400",
            "--root",
            str(tmp_path / "out"),
            "--pdf-min",
            "10kb",
            "--pdf-max",
            "100kb",
            "--img-min",
            "2kb",
            "--img-max",
            "30kb",
        )
        assert code == 2
        assert "mutually" in stderr.lower() or "exactly one" in stderr.lower()

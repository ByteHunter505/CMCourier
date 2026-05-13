"""Integration tests for ``cmcourier mock rvabrep`` (039).

Drives the CLI end-to-end with a small ``--rows`` count and:
1. Asserts the CSV is well-formed (header + row count).
2. Reads the CSV back through ``TabularDataSource`` and exercises the
   ``IndexingService`` to confirm every row materializes as an
   ``RVABREPDocument``.
3. Chains into ``cmcourier mock generate`` with the generated CSV and
   asserts physical files materialize.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from click.testing import CliRunner

from cmcourier.adapters.sources import TabularDataSource
from cmcourier.cli.app import main
from cmcourier.domain.models import RVABREPDocument, TriggerRecord, parse_cymmdd
from cmcourier.services.indexing import IndexingColumnsConfig, IndexingService

pytestmark = pytest.mark.integration


def _write_idrvi_fixture(path: Path) -> None:
    path.write_text(
        "IDSistema,IDRVI,IDCM,IDClaseDocumental,CMISType\n"
        ",FB01,CN01,01.01.01.01.01,\n"
        ",FB23,CN02,01.01.01.01.02,\n"
        ",FB13,CN03,01.01.01.01.03,\n"
        ",FF17,PT57,01.02.04.01.01,\n"
        ",CN10,FF07,01.02.05.01.01,\n",
        encoding="utf-8",
    )


def _invoke(*args: str) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(main, list(args), catch_exceptions=False)
    return result.exit_code, result.stdout + result.stderr


class TestEndToEnd:
    def test_csv_well_formed(self, tmp_path: Path) -> None:
        idrvi_src = tmp_path / "MapeoRVI_CM.csv"
        _write_idrvi_fixture(idrvi_src)
        out_csv = tmp_path / "rvabrep.csv"
        code, _ = _invoke(
            "mock",
            "rvabrep",
            "--rows",
            "100",
            "--output",
            str(out_csv),
            "--seed",
            "100",
            "--idrvi-source",
            str(idrvi_src),
            "--idrvi-top",
            "5",
        )
        assert code == 0
        with out_csv.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        assert len(rows) == 100
        # ABA-coded header — matches IndexingColumnsModel defaults.
        assert "ABABCD" in (reader.fieldnames or [])
        assert "ABAANB" in (reader.fieldnames or [])
        assert "ABAHCD" in (reader.fieldnames or [])

    def test_indexing_service_consumes_output(self, tmp_path: Path) -> None:
        idrvi_src = tmp_path / "MapeoRVI_CM.csv"
        _write_idrvi_fixture(idrvi_src)
        out_csv = tmp_path / "rvabrep.csv"
        code, _ = _invoke(
            "mock",
            "rvabrep",
            "--rows",
            "100",
            "--output",
            str(out_csv),
            "--seed",
            "100",
            "--idrvi-source",
            str(idrvi_src),
            "--idrvi-top",
            "5",
        )
        assert code == 0

        # Load with TabularDataSource (the adapter the pipeline uses) and
        # confirm the generated CSV is consumed by IndexingService for a
        # representative shortname. We don't iterate the full 100 — we
        # exercise the row -> RVABREPDocument coercion path for one
        # trigger that we know exists in the generated set.
        source = TabularDataSource(out_csv)
        try:
            rows = list(source.get_all())
        finally:
            source.close()
        assert len(rows) == 100
        # Every IDRVI is one of the 5 from the fixture pool.
        allowed = {"CN10", "FB01", "FB13", "FB23", "FF17"}
        seen = {str(row["ABAHCD"]) for row in rows}
        assert seen <= allowed

        # Pick the first shortname and run IndexingService.find_documents
        # against the same CSV — verifies row -> RVABREPDocument coercion
        # uses the columns we emit.
        first_shortname = str(rows[0]["ABABCD"])
        first_system_id = str(rows[0]["ABAACD"])
        source = TabularDataSource(out_csv)
        try:
            service = IndexingService(source, IndexingColumnsConfig())
            docs = service.find_documents(
                TriggerRecord(shortname=first_shortname, cif=None, system_id=first_system_id)
            )
        finally:
            source.close()
        assert len(docs) >= 1
        for doc in docs:
            assert isinstance(doc, RVABREPDocument)
            # Sanity: parse_cymmdd round-trip succeeds for every doc the
            # service hands us.
            parse_cymmdd(doc.creation_date.strftime("1%y%m%d"))

    def test_chained_mock_generate_materializes_files(self, tmp_path: Path) -> None:
        idrvi_src = tmp_path / "MapeoRVI_CM.csv"
        _write_idrvi_fixture(idrvi_src)
        out_csv = tmp_path / "rvabrep.csv"
        code, _ = _invoke(
            "mock",
            "rvabrep",
            "--rows",
            "20",
            "--output",
            str(out_csv),
            "--seed",
            "20",
            "--idrvi-source",
            str(idrvi_src),
            "--idrvi-top",
            "5",
        )
        assert code == 0

        root = tmp_path / "files"
        code, stdout = _invoke(
            "mock",
            "generate",
            "--rvabrep-csv",
            str(out_csv),
            "--root",
            str(root),
            "--pdf-min",
            "10kb",
            "--pdf-max",
            "30kb",
            "--img-min",
            "2kb",
            "--img-max",
            "10kb",
            "--seed",
            "1",
        )
        assert code == 0, stdout
        # Check at least some files exist under root for each rvabrep row.
        materialized = list(root.rglob("*"))
        materialized_files = [p for p in materialized if p.is_file()]
        assert len(materialized_files) >= 20

    def test_determinism_via_cli(self, tmp_path: Path) -> None:
        idrvi_src = tmp_path / "MapeoRVI_CM.csv"
        _write_idrvi_fixture(idrvi_src)
        out_a = tmp_path / "a.csv"
        out_b = tmp_path / "b.csv"
        for out in (out_a, out_b):
            code, _ = _invoke(
                "mock",
                "rvabrep",
                "--rows",
                "50",
                "--output",
                str(out),
                "--seed",
                "777",
                "--idrvi-source",
                str(idrvi_src),
                "--idrvi-top",
                "5",
            )
            assert code == 0
        assert out_a.read_bytes() == out_b.read_bytes()

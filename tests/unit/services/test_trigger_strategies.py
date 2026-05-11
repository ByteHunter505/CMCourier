"""Unit tests for the S0 trigger strategies.

Real ``TabularDataSource`` over CSV fixtures (consistent with 004 / 005). The
SUT (the strategies) does no I/O of its own; the data source is wiring.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cmcourier.adapters.sources import TabularDataSource
from cmcourier.domain.exceptions import ConfigurationError
from cmcourier.domain.ports import S0Strategy
from cmcourier.services.triggers import (
    CsvTriggerColumnsConfig,
    CsvTriggerStrategy,
    DirectRvabrepTriggerStrategy,
    LocalScanTriggerStrategy,
    RvabrepFilters,
    SingleDocTriggerStrategy,
)

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "services" / "triggers"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# CsvTriggerStrategy
# ---------------------------------------------------------------------------


class TestCsvTriggerStrategy:
    @pytest.fixture
    def source(self) -> Iterator[TabularDataSource]:
        src = TabularDataSource(_FIXTURES / "trigger_list.csv")
        yield src
        src.close()

    def test_yields_records(self, source: TabularDataSource) -> None:
        strategy = CsvTriggerStrategy(source)
        records = list(strategy.acquire())
        # 5 fixture rows minus 1 blank ShortName = 4 yielded.
        assert len(records) == 4
        assert records[0].shortname == "JUANPEREZ01"
        assert records[0].cif == "123456"
        assert records[0].system_id == "1"

    def test_yields_cif_none_when_blank(self, source: TabularDataSource) -> None:
        strategy = CsvTriggerStrategy(source)
        records = list(strategy.acquire())
        # PEPELOPEZ03 has a blank CIF.
        pepe = next(r for r in records if r.shortname == "PEPELOPEZ03")
        assert pepe.cif is None

    def test_blank_rows_skipped(self, source: TabularDataSource) -> None:
        strategy = CsvTriggerStrategy(source)
        records = list(strategy.acquire())
        # The fifth row has blank ShortName; not yielded.
        for r in records:
            assert r.shortname  # non-empty

    def test_custom_columns(self) -> None:
        src = TabularDataSource(_FIXTURES / "trigger_list_alt_columns.csv")
        try:
            cfg = CsvTriggerColumnsConfig(
                col_shortname="Cliente", col_cif="Doc", col_system_id="Sistema"
            )
            strategy = CsvTriggerStrategy(src, columns=cfg)
            records = list(strategy.acquire())
            assert len(records) == 1
            assert records[0].shortname == "JUANPEREZ01"
            assert records[0].cif == "123456"
            assert records[0].system_id == "1"
        finally:
            src.close()

    def test_missing_required_column_raises(self) -> None:
        src = TabularDataSource(_FIXTURES / "trigger_list_missing_col.csv")
        try:
            strategy = CsvTriggerStrategy(src)
            with pytest.raises(ConfigurationError) as exc:
                list(strategy.acquire())
            assert exc.value.context.get("missing_column") == "ShortName"
        finally:
            src.close()

    def test_source_descriptor_ignored(self, source: TabularDataSource) -> None:
        strategy = CsvTriggerStrategy(source)
        # Non-empty descriptor must not raise; behavior identical to empty.
        records = list(strategy.acquire("some-descriptor-ignored"))
        assert len(records) == 4

    def test_is_s0strategy(self, source: TabularDataSource) -> None:
        strategy = CsvTriggerStrategy(source)
        assert isinstance(strategy, S0Strategy)


# ---------------------------------------------------------------------------
# DirectRvabrepTriggerStrategy
# ---------------------------------------------------------------------------


class TestDirectRvabrepTriggerStrategy:
    @pytest.fixture
    def source(self) -> Iterator[TabularDataSource]:
        src = TabularDataSource(_FIXTURES / "rvabrep_export.csv")
        yield src
        src.close()

    def test_no_filters_yields_unique_pairs(self, source: TabularDataSource) -> None:
        strategy = DirectRvabrepTriggerStrategy(source)
        records = list(strategy.acquire())
        # 8 rows total → 1 blank skipped → 7 valid → 4 unique pairs.
        assert len(records) == 4
        keys = {(r.shortname, r.system_id) for r in records}
        assert keys == {
            ("JUANPEREZ01", "1"),
            ("MARIAGOMEZ02", "5"),
            ("PEPELOPEZ03", "1"),
            ("EMPRESA04", "2"),
        }

    def test_filter_by_systems(self, source: TabularDataSource) -> None:
        strategy = DirectRvabrepTriggerStrategy(source, filters=RvabrepFilters(systems=("1",)))
        records = list(strategy.acquire())
        assert all(r.system_id == "1" for r in records)
        assert {r.shortname for r in records} == {"JUANPEREZ01", "PEPELOPEZ03"}

    def test_filter_by_document_types(self, source: TabularDataSource) -> None:
        strategy = DirectRvabrepTriggerStrategy(
            source, filters=RvabrepFilters(document_types=("FF17",))
        )
        records = list(strategy.acquire())
        # FF17 rows: JUANPEREZ01/1, MARIAGOMEZ02/5, EMPRESA04/2 (and the blank
        # row also FF17 but skipped because blank shortname).
        keys = {(r.shortname, r.system_id) for r in records}
        assert keys == {
            ("JUANPEREZ01", "1"),
            ("MARIAGOMEZ02", "5"),
            ("EMPRESA04", "2"),
        }

    def test_filter_by_both(self, source: TabularDataSource) -> None:
        strategy = DirectRvabrepTriggerStrategy(
            source, filters=RvabrepFilters(systems=("1",), document_types=("FF17",))
        )
        records = list(strategy.acquire())
        assert len(records) == 1
        assert records[0].shortname == "JUANPEREZ01"
        assert records[0].system_id == "1"

    def test_blank_rows_skipped(self, source: TabularDataSource) -> None:
        strategy = DirectRvabrepTriggerStrategy(source)
        for r in strategy.acquire():
            assert r.shortname  # non-empty
            assert r.system_id

    def test_cif_extracted_when_present(self, source: TabularDataSource) -> None:
        strategy = DirectRvabrepTriggerStrategy(source)
        records = list(strategy.acquire())
        juan = next(r for r in records if r.shortname == "JUANPEREZ01")
        assert juan.cif == "123456"

    def test_cif_none_when_blank(self, source: TabularDataSource) -> None:
        strategy = DirectRvabrepTriggerStrategy(source)
        records = list(strategy.acquire())
        pepe = next(r for r in records if r.shortname == "PEPELOPEZ03")
        assert pepe.cif is None

    def test_source_descriptor_ignored(self, source: TabularDataSource) -> None:
        strategy = DirectRvabrepTriggerStrategy(source)
        records = list(strategy.acquire("any-descriptor"))
        assert len(records) == 4

    def test_is_s0strategy(self, source: TabularDataSource) -> None:
        strategy = DirectRvabrepTriggerStrategy(source)
        assert isinstance(strategy, S0Strategy)


# ---------------------------------------------------------------------------
# LocalScanTriggerStrategy (REBIRTH §5.1 mode local_scan)
# ---------------------------------------------------------------------------


_RVABREP_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "pipeline" / "rvabrep.csv"


def _friendly_columns() -> RvabrepColumnsConfig:  # noqa: F821 — forward ref
    from cmcourier.services.triggers.direct_rvabrep import RvabrepColumnsConfig

    return RvabrepColumnsConfig(
        col_shortname="shortname",
        col_cif="index2",
        col_system_id="system_id",
        col_id_rvi="index7",
        file_name_column="file_name",
    )


class TestLocalScanStrategy:
    def test_yields_trigger_per_matched_file(self, tmp_path: Path) -> None:
        # rvabrep.csv has TESTCLIENT01 with file_name=DAAAH9X4.001.
        (tmp_path / "DAAAH9X4.001").touch()
        src = TabularDataSource(_RVABREP_FIXTURE)
        try:
            strategy = LocalScanTriggerStrategy(tmp_path, src, columns=_friendly_columns())
            triggers = list(strategy.acquire())
        finally:
            src.close()
        shortnames = {t.shortname for t in triggers}
        assert "TESTCLIENT01" in shortnames

    def test_filters_non_trigger_files(self, tmp_path: Path) -> None:
        # Build a focused rvabrep with exactly one .001 match so the count
        # is unambiguous.
        rvabrep = tmp_path / "rvabrep_focused.csv"
        rvabrep.write_text(
            "shortname,system_id,index2,index7,file_name\nFOCUSED,1,123456,FF17,DZZZZ.001\n"
        )
        # .002, .tmp, .txt should be ignored; only .001 reaches RVABREP.
        for name in ("DZZZZ.001", "DZZZZ.002", "stray.txt", "DZZZZ.PDF.tmp"):
            (tmp_path / name).touch()
        src = TabularDataSource(rvabrep)
        try:
            triggers = list(
                LocalScanTriggerStrategy(tmp_path, src, columns=_friendly_columns()).acquire()
            )
        finally:
            src.close()
        # Exactly one trigger from the one matching row.
        assert [t.shortname for t in triggers] == ["FOCUSED"]

    def test_unmatched_file_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "STRAY.PDF").touch()
        src = TabularDataSource(_RVABREP_FIXTURE)
        try:
            import logging as _logging

            with caplog.at_level(_logging.WARNING, logger="cmcourier.services.triggers.local_scan"):
                triggers = list(
                    LocalScanTriggerStrategy(tmp_path, src, columns=_friendly_columns()).acquire()
                )
        finally:
            src.close()
        assert triggers == []
        assert any(r.__dict__.get("file_name") == "STRAY.PDF" for r in caplog.records)

    def test_missing_scan_path_raises(self) -> None:
        src = TabularDataSource(_RVABREP_FIXTURE)
        try:
            strategy = LocalScanTriggerStrategy(
                Path("/this/path/does/not/exist"),
                src,
                columns=_friendly_columns(),
            )
            with pytest.raises(ConfigurationError) as ei:
                list(strategy.acquire())
        finally:
            src.close()
        assert ei.value.context["scan_path"].endswith("/exist")

    def test_blank_shortname_dropped(self, tmp_path: Path) -> None:
        # Build a tiny rvabrep CSV in tmp_path with a blank shortname row.
        rvabrep = tmp_path / "rvabrep_blank.csv"
        rvabrep.write_text(
            "shortname,system_id,index2,index7,file_name\n"
            ",1,123456,FF17,DXXX1.001\n"
            "TESTOK,1,123456,FF17,DXXX2.001\n"
        )
        (tmp_path / "DXXX1.001").touch()
        (tmp_path / "DXXX2.001").touch()
        src = TabularDataSource(rvabrep)
        try:
            triggers = list(
                LocalScanTriggerStrategy(tmp_path, src, columns=_friendly_columns()).acquire()
            )
        finally:
            src.close()
        shortnames = {t.shortname for t in triggers}
        assert shortnames == {"TESTOK"}

    def test_native_pdf_case_insensitive(self, tmp_path: Path) -> None:
        # Build a rvabrep with two PDF entries, lower- and upper-case file_name.
        rvabrep = tmp_path / "rvabrep_pdf.csv"
        rvabrep.write_text(
            "shortname,system_id,index2,index7,file_name\n"
            "PDFCLIENT1,1,123456,FF18,0AAAUI0K.PDF\n"
            "PDFCLIENT2,1,123456,FF18,0AAAUI0K.pdf\n"
        )
        # Filesystem entries.
        (tmp_path / "0AAAUI0K.PDF").touch()
        (tmp_path / "0AAAUI0K.pdf").touch()
        src = TabularDataSource(rvabrep)
        try:
            triggers = list(
                LocalScanTriggerStrategy(tmp_path, src, columns=_friendly_columns()).acquire()
            )
        finally:
            src.close()
        # Both files match (case-insensitive on .PDF extension).
        # Each filesystem entry is queried; the CSV match is exact so each
        # filesystem name finds its own row.
        shortnames = {t.shortname for t in triggers}
        assert shortnames == {"PDFCLIENT1", "PDFCLIENT2"}

    def test_empty_directory(self, tmp_path: Path) -> None:
        src = TabularDataSource(_RVABREP_FIXTURE)
        try:
            triggers = list(
                LocalScanTriggerStrategy(tmp_path, src, columns=_friendly_columns()).acquire()
            )
        finally:
            src.close()
        assert triggers == []

    def test_empty_cif_becomes_none(self, tmp_path: Path) -> None:
        # Build a tiny rvabrep where one row has empty index2.
        rvabrep = tmp_path / "rvabrep_cif_blank.csv"
        rvabrep.write_text(
            "shortname,system_id,index2,index7,file_name\nNOCIFCLIENT,1,,FF17,DBLANK.001\n"
        )
        (tmp_path / "DBLANK.001").touch()
        src = TabularDataSource(rvabrep)
        try:
            triggers = list(
                LocalScanTriggerStrategy(tmp_path, src, columns=_friendly_columns()).acquire()
            )
        finally:
            src.close()
        assert len(triggers) == 1
        assert triggers[0].cif is None

    def test_is_s0strategy(self, tmp_path: Path) -> None:
        src = TabularDataSource(_RVABREP_FIXTURE)
        try:
            strategy = LocalScanTriggerStrategy(tmp_path, src, columns=_friendly_columns())
            assert isinstance(strategy, S0Strategy)
        finally:
            src.close()

    def test_default_columns_use_physical_names(self, tmp_path: Path) -> None:
        # When columns is None, defaults are AS400 physical names (ABABCD etc.).
        # We can't query CSV friendly columns with those defaults — just assert
        # construction succeeds and returns the default columns config.
        from cmcourier.services.triggers.direct_rvabrep import RvabrepColumnsConfig

        src = TabularDataSource(_RVABREP_FIXTURE)
        try:
            strategy = LocalScanTriggerStrategy(tmp_path, src)
            assert strategy._columns == RvabrepColumnsConfig()  # type: ignore[attr-defined]
        finally:
            src.close()


# ---------------------------------------------------------------------------
# SingleDocTriggerStrategy (017)
# ---------------------------------------------------------------------------


class TestSingleDocStrategy:
    def test_yields_exactly_one_trigger(self) -> None:
        strategy = SingleDocTriggerStrategy(shortname="JUANPEREZ01", system_id="1", cif="123456")
        records = list(strategy.acquire())
        assert len(records) == 1
        assert records[0].shortname == "JUANPEREZ01"
        assert records[0].system_id == "1"
        assert records[0].cif == "123456"

    def test_cif_none_propagates(self) -> None:
        strategy = SingleDocTriggerStrategy(shortname="X", system_id="1", cif=None)
        records = list(strategy.acquire())
        assert records[0].cif is None

    def test_empty_cif_treated_as_none(self) -> None:
        strategy = SingleDocTriggerStrategy(shortname="X", system_id="1", cif="")
        records = list(strategy.acquire())
        assert records[0].cif is None

    def test_is_s0strategy(self) -> None:
        strategy = SingleDocTriggerStrategy(shortname="X", system_id="1")
        assert isinstance(strategy, S0Strategy)

    def test_empty_shortname_raises(self) -> None:
        with pytest.raises(ValueError, match="shortname"):
            SingleDocTriggerStrategy(shortname="", system_id="1")

    def test_empty_system_id_raises(self) -> None:
        with pytest.raises(ValueError, match="system_id"):
            SingleDocTriggerStrategy(shortname="X", system_id="")

    def test_acquire_ignores_source_descriptor(self) -> None:
        strategy = SingleDocTriggerStrategy(shortname="X", system_id="1")
        records_a = list(strategy.acquire(""))
        records_b = list(strategy.acquire("ignored"))
        assert records_a[0].shortname == records_b[0].shortname == "X"

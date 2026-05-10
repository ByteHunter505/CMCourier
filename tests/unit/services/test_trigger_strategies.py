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
    As400TriggerStrategy,
    CsvTriggerColumnsConfig,
    CsvTriggerStrategy,
    DirectRvabrepTriggerStrategy,
    LocalScanTriggerStrategy,
    RvabrepFilters,
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
# Stubs
# ---------------------------------------------------------------------------


class TestStubStrategies:
    def test_as400_construction_succeeds(self) -> None:
        # Constructor must not raise so orchestrators can dispatch.
        strategy = As400TriggerStrategy(query="SELECT * FROM RVILIB.TRIGGER_TABLE")
        assert strategy is not None

    def test_as400_acquire_raises(self) -> None:
        strategy = As400TriggerStrategy(query="SELECT 1")
        with pytest.raises(NotImplementedError) as exc:
            list(strategy.acquire())
        assert "AS400" in str(exc.value)

    def test_local_scan_construction_succeeds(self) -> None:
        strategy = LocalScanTriggerStrategy(scan_path=Path("/tmp/nope"))
        assert strategy is not None

    def test_local_scan_acquire_raises(self) -> None:
        strategy = LocalScanTriggerStrategy(scan_path=Path("/tmp/nope"))
        with pytest.raises(NotImplementedError) as exc:
            list(strategy.acquire())
        assert "local-scan" in str(exc.value).lower()

    def test_both_are_s0strategies(self) -> None:
        a = As400TriggerStrategy(query="x")
        b = LocalScanTriggerStrategy(scan_path=Path("/tmp/x"))
        assert isinstance(a, S0Strategy)
        assert isinstance(b, S0Strategy)

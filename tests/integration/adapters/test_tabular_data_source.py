"""Integration tests for ``TabularDataSource``.

Exercises the real adapter against real CSV and XLSX files in
``tests/fixtures/sources/``. Parametrized over both formats where the
contract is identical; format-specific tests live in their own classes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cmcourier.adapters.sources import TabularDataSource
from cmcourier.domain.exceptions import ConfigurationError

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "sources"
_SAMPLE_CSV = _FIXTURES / "sample.csv"
_SAMPLE_XLSX = _FIXTURES / "sample.xlsx"


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Parametrized contract tests (both formats must behave identically)
# ---------------------------------------------------------------------------


@pytest.fixture(params=["csv", "xlsx"], ids=["csv", "xlsx"])
def adapter(request: pytest.FixtureRequest) -> Iterator[TabularDataSource]:
    path = _SAMPLE_CSV if request.param == "csv" else _SAMPLE_XLSX
    src = TabularDataSource(path)
    yield src
    src.close()


class TestContract:
    """Behaviors expected to hold for both CSV and XLSX (parametrized)."""

    def test_count(self, adapter: TabularDataSource) -> None:
        assert adapter.count() == 5

    def test_get_all_yields_dicts(self, adapter: TabularDataSource) -> None:
        rows = list(adapter.get_all())
        assert len(rows) == 5
        assert all(isinstance(r, dict) for r in rows)
        assert set(rows[0].keys()) == {"Name", "Age", "Birth"}

    def test_nan_normalized_to_none(self, adapter: TabularDataSource) -> None:
        # MARIAGOMEZ02 has a blank Age; must surface as None, not NaN, not "".
        rows = list(adapter.get_all())
        maria = next(r for r in rows if r["Name"] == "MARIAGOMEZ02")
        assert maria["Age"] is None

    def test_get_by_fields_equality(self, adapter: TabularDataSource) -> None:
        result = adapter.get_by_fields({"Name": "JUANPEREZ01"})
        assert len(result) == 2
        assert all(r["Name"] == "JUANPEREZ01" for r in result)

    def test_get_by_fields_empty_filters_returns_all(self, adapter: TabularDataSource) -> None:
        result = adapter.get_by_fields({})
        assert len(result) == 5

    def test_get_by_fields_missing_key_raises(self, adapter: TabularDataSource) -> None:
        with pytest.raises(KeyError):
            adapter.get_by_fields({"DoesNotExist": "x"})

    def test_get_by_fields_in(self, adapter: TabularDataSource) -> None:
        result = adapter.get_by_fields_in(
            field="Name",
            values=["JUANPEREZ01", "PEPELOPEZ03"],
            fixed_filters={},
        )
        names = {r["Name"] for r in result}
        assert names == {"JUANPEREZ01", "PEPELOPEZ03"}
        assert len(result) == 3  # JUANPEREZ01 twice + PEPELOPEZ03 once

    def test_get_by_fields_in_with_fixed_filters(self, adapter: TabularDataSource) -> None:
        result = adapter.get_by_fields_in(
            field="Name",
            values=["JUANPEREZ01", "PEPELOPEZ03"],
            fixed_filters={"Age": "30"},
        )
        # Only JUANPEREZ01 with Age=30 matches.
        assert len(result) == 1
        assert result[0]["Name"] == "JUANPEREZ01"
        assert result[0]["Age"] == "30"

    def test_get_by_fields_in_missing_field_raises(self, adapter: TabularDataSource) -> None:
        with pytest.raises(KeyError):
            adapter.get_by_fields_in(field="Nope", values=["x"], fixed_filters={})

    def test_query_raises(self, adapter: TabularDataSource) -> None:
        with pytest.raises(NotImplementedError) as exc:
            adapter.query("SELECT * FROM whatever")
        assert "get_by_fields" in str(exc.value)

    def test_query_stream_raises(self, adapter: TabularDataSource) -> None:
        with pytest.raises(NotImplementedError):
            list(adapter.query_stream("SELECT 1"))


class TestLifecycle:
    def test_close(self) -> None:
        src = TabularDataSource(_SAMPLE_CSV)
        src.close()  # should not raise

    def test_close_is_idempotent(self) -> None:
        src = TabularDataSource(_SAMPLE_CSV)
        src.close()
        src.close()  # second call must NOT raise

    def test_get_all_after_close_raises(self) -> None:
        src = TabularDataSource(_SAMPLE_CSV)
        src.close()
        with pytest.raises(RuntimeError, match="closed"):
            list(src.get_all())

    def test_count_after_close_raises(self) -> None:
        src = TabularDataSource(_SAMPLE_CSV)
        src.close()
        with pytest.raises(RuntimeError, match="closed"):
            src.count()

    def test_get_by_fields_after_close_raises(self) -> None:
        src = TabularDataSource(_SAMPLE_CSV)
        src.close()
        with pytest.raises(RuntimeError, match="closed"):
            src.get_by_fields({})


class TestExtensionDispatch:
    def test_unknown_extension_raises_configuration_error(self) -> None:
        bad = _FIXTURES / "bad_extension.txt"
        with pytest.raises(ConfigurationError, match="extension"):
            TabularDataSource(bad)

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            TabularDataSource(tmp_path / "nope.csv")

    def test_extension_case_insensitive(self, tmp_path: Path) -> None:
        # Copy sample.csv to a path with uppercase extension.
        upper_path = tmp_path / "SAMPLE.CSV"
        upper_path.write_text(_SAMPLE_CSV.read_text())
        src = TabularDataSource(upper_path)
        assert src.count() == 5
        src.close()


class TestEncoding:
    def test_encoding_override_latin1(self) -> None:
        latin1 = _FIXTURES / "latin1.csv"
        src = TabularDataSource(latin1, encoding="latin-1")
        rows = list(src.get_all())
        assert len(rows) == 2
        assert any("ñ" in str(r.get("Name", "")) for r in rows)
        src.close()

    def test_encoding_mismatch_raises_configuration_error(self) -> None:
        latin1 = _FIXTURES / "latin1.csv"
        with pytest.raises(ConfigurationError):
            TabularDataSource(latin1, encoding="utf-8")


class TestXlsxSpecific:
    def test_multi_sheet_default_is_first(self) -> None:
        path = _FIXTURES / "multi_sheet.xlsx"
        src = TabularDataSource(path)  # sheet_name=0 by default
        rows = list(src.get_all())
        assert len(rows) == 1
        assert rows[0]["Col"] == "sheet1_value"
        src.close()

    def test_multi_sheet_select_by_name(self) -> None:
        path = _FIXTURES / "multi_sheet.xlsx"
        src = TabularDataSource(path, sheet_name="Sheet2")
        rows = list(src.get_all())
        assert len(rows) == 2
        cols = {r["Col"] for r in rows}
        assert cols == {"sheet2_value_a", "sheet2_value_b"}
        src.close()

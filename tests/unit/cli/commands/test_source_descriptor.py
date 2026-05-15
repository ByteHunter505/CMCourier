"""Tests unitarios para ``parse_source_descriptor`` (023)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cmcourier.cli.commands._source_descriptor import parse_source_descriptor
from cmcourier.domain.exceptions import ConfigurationError

pytestmark = pytest.mark.unit


class TestParseSourceDescriptor:
    def test_csv_scheme(self) -> None:
        parsed = parse_source_descriptor("csv:./data/t.csv")
        assert parsed.scheme == "csv"
        assert parsed.path == Path("./data/t.csv")

    def test_csv_expands_tilde(self) -> None:
        parsed = parse_source_descriptor("csv:~/triggers.csv")
        assert parsed.path is not None
        assert "~" not in str(parsed.path)

    def test_single_doc_without_cif(self) -> None:
        parsed = parse_source_descriptor("single_doc:JUANPEREZ01,1")
        assert parsed.scheme == "single_doc"
        assert parsed.shortname == "JUANPEREZ01"
        assert parsed.system_id == "1"
        assert parsed.cif is None

    def test_single_doc_with_cif(self) -> None:
        parsed = parse_source_descriptor("single_doc:JUANPEREZ01,1,123456")
        assert parsed.scheme == "single_doc"
        assert parsed.shortname == "JUANPEREZ01"
        assert parsed.system_id == "1"
        assert parsed.cif == "123456"

    def test_rvabrep_rejected_with_yaml_hint(self) -> None:
        with pytest.raises(ConfigurationError) as ei:
            parse_source_descriptor("rvabrep:")
        assert "use the YAML" in str(ei.value) or "trigger.kind" in str(ei.value)

    def test_as400_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            parse_source_descriptor("as400:SELECT *")

    def test_local_scan_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            parse_source_descriptor("local_scan:/data")

    def test_unknown_scheme_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            parse_source_descriptor("ftp://example.com/triggers")

    def test_no_colon_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            parse_source_descriptor("just_a_string")

    def test_single_doc_missing_system_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            parse_source_descriptor("single_doc:ONLY_SHORTNAME")

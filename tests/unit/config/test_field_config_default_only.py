"""083: ``FieldConfig`` permite ``sources: []`` cuando hay
``default_value`` — para campos constantes hardcodeados sin
necesidad de inventar un source dummy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cmcourier.config.schema import FieldConfig, FieldSourceItem

pytestmark = pytest.mark.unit


class TestDefaultOnly:
    def test_default_only_no_sources_is_accepted(self) -> None:
        cfg = FieldConfig(default_value="FAC")
        assert cfg.sources == []
        assert cfg.default_value == "FAC"

    def test_default_only_explicit_empty_sources_is_accepted(self) -> None:
        cfg = FieldConfig(sources=[], default_value="constant-value")
        assert cfg.sources == []
        assert cfg.default_value == "constant-value"

    def test_sources_with_no_default_still_accepted(self) -> None:
        cfg = FieldConfig(
            sources=[
                FieldSourceItem(
                    source_type="trigger",
                    lookup_value_column="cif",
                )
            ]
        )
        assert cfg.default_value is None
        assert len(cfg.sources) == 1

    def test_both_sources_and_default_are_accepted(self) -> None:
        cfg = FieldConfig(
            sources=[
                FieldSourceItem(
                    source_type="trigger",
                    lookup_value_column="cif",
                )
            ],
            default_value="fallback",
        )
        assert cfg.default_value == "fallback"
        assert len(cfg.sources) == 1


class TestRejected:
    def test_empty_sources_and_no_default_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            FieldConfig(sources=[], default_value=None)
        assert "at least one" in str(excinfo.value).lower()

    def test_completely_empty_is_rejected(self) -> None:
        # default_value es None implícito; sources default a [].
        with pytest.raises(ValidationError):
            FieldConfig()

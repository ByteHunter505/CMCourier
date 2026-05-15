"""Unit tests for ``cmcourier.services.mapping.MappingService``.

Uses a real ``TabularDataSource`` over a CSV fixture (no IDataSource mocks)
because the SUT — the service — does no I/O of its own. The adapter is
test wiring, not part of the unit under test. Constitution Principle VI:
we do not mock our own ports when the real adapter is fast and local.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from cmcourier.adapters.sources import TabularDataSource
from cmcourier.domain.exceptions import ConfigurationError, IDRViNotMappedError
from cmcourier.domain.models import CMMapping
from cmcourier.services.mapping import MappingColumnsConfig, MappingService

_FIXTURE_PATH = (
    Path(__file__).parent.parent.parent / "fixtures" / "services" / "modelo_documental.csv"
)

pytestmark = pytest.mark.unit


@pytest.fixture
def source() -> Iterator[TabularDataSource]:
    src = TabularDataSource(_FIXTURE_PATH)
    yield src
    src.close()


@pytest.fixture
def service(source: TabularDataSource) -> MappingService:
    return MappingService(source)


# ---------------------------------------------------------------------------
# Public API basics
# ---------------------------------------------------------------------------


class TestPublicApi:
    def test_count_excludes_empty_id_and_duplicates(self, service: MappingService) -> None:
        # 8 fixture rows: 1 empty id_rvi + 1 duplicate FF17 + 6 unique = 6 cached.
        assert service.count() == 6

    def test_get_mapping_vanilla(self, service: MappingService) -> None:
        m = service.get_mapping("FF17")
        assert isinstance(m, CMMapping)
        assert m.clase_id == "01.02.04.01.01"
        assert m.id_rvi == "FF17"
        assert m.id_corto == "PT57"
        assert m.clase_name == "Autorizacion SMS"
        assert m.required_metadata_fields == ("CIF", "NUM_CUENTA_TARJETA")

    def test_get_mapping_propagates_computed_properties(self, service: MappingService) -> None:
        m = service.get_mapping("FF17")
        # CMMapping computes cm_folder + cm_object_type from clase_id.
        assert m.cm_folder == "/$type/BAC_01_02_04_01_01"
        assert m.cm_object_type == "$t!-2_BAC_01_02_04_01_01v-1"

    def test_get_mapping_unknown_raises(self, service: MappingService) -> None:
        with pytest.raises(IDRViNotMappedError) as excinfo:
            service.get_mapping("ZZ99")
        assert excinfo.value.id_rvi == "ZZ99"
        assert "ZZ99" in str(excinfo.value)

    def test_contains_for_known_id(self, service: MappingService) -> None:
        assert "FF17" in service
        assert "AA01" in service

    def test_contains_for_unknown_id(self, service: MappingService) -> None:
        assert "ZZ99" not in service

    def test_contains_non_string_returns_false(self, service: MappingService) -> None:
        assert (123 in service) is False  # type: ignore[operator]
        assert (None in service) is False  # type: ignore[operator]

    def test_get_all_yields_in_insertion_order(self, service: MappingService) -> None:
        ids = [m.id_rvi for m in service.get_all()]
        # Source order: FF17, AA01, BB02, CC03, DD04, EE05 (DUP FF17 dropped, empty skipped).
        assert ids == ["FF17", "AA01", "BB02", "CC03", "DD04", "EE05"]


# ---------------------------------------------------------------------------
# METADATOS parsing edge cases
# ---------------------------------------------------------------------------


class TestMetadatosParsing:
    def test_multi_field(self, service: MappingService) -> None:
        m = service.get_mapping("AA01")
        assert m.required_metadata_fields == ("CIF", "NUM_PRESTAMO", "Fecha_Firma")

    def test_empty_cell_becomes_empty_tuple(self, service: MappingService) -> None:
        m = service.get_mapping("BB02")
        assert m.required_metadata_fields == ()

    def test_whitespace_stripped(self, service: MappingService) -> None:
        m = service.get_mapping("CC03")
        assert m.required_metadata_fields == ("CIF", "Nombre_Cliente")

    def test_trailing_comma_handled(self, service: MappingService) -> None:
        m = service.get_mapping("DD04")
        assert m.required_metadata_fields == ("CIF",)

    def test_doubled_comma_filtered(self, service: MappingService) -> None:
        m = service.get_mapping("EE05")
        assert m.required_metadata_fields == ("CIF", "NUM_CUENTA")


# ---------------------------------------------------------------------------
# Logging side-effects (duplicate, empty id_rvi)
# ---------------------------------------------------------------------------


class TestLoggingSideEffects:
    def test_duplicate_id_rvi_first_wins(
        self, source: TabularDataSource, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="cmcourier.services.mapping")
        svc = MappingService(source)
        m = svc.get_mapping("FF17")
        # First occurrence has id_corto="PT57"; the duplicate has "PT58".
        assert m.id_corto == "PT57"

    def test_duplicate_emits_warning(
        self, source: TabularDataSource, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="cmcourier.services.mapping")
        MappingService(source)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "FF17" in warnings[0].getMessage()
        assert "duplicate" in warnings[0].getMessage().lower()

    def test_empty_id_rvi_row_skipped(self, service: MappingService) -> None:
        # The row with empty id_rvi (id_corto="GN19") has clase_name="Empty ID RVI Row".
        # It should not be retrievable under any id_rvi key.
        for m in service.get_all():
            assert m.id_corto != "GN19"

    def test_empty_id_rvi_emits_info(
        self, source: TabularDataSource, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO, logger="cmcourier.services.mapping")
        MappingService(source)
        infos = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(infos) == 1
        msg = infos[0].getMessage()
        assert "skipped" in msg.lower()
        assert "1" in msg  # one empty-id row in the fixture


# ---------------------------------------------------------------------------
# Custom MappingColumnsConfig
# ---------------------------------------------------------------------------


class TestCustomColumnsConfig:
    def test_construction_with_custom_columns(self, tmp_path: Path) -> None:
        custom_csv = tmp_path / "custom.csv"
        custom_csv.write_text(
            "Code,RVI,Short,Name,Meta\n01.01.01.01.01,XX99,SH99,Custom Class,CIF\n",
            encoding="utf-8",
        )
        src = TabularDataSource(custom_csv)
        cfg = MappingColumnsConfig(
            col_clase_id="Code",
            col_id_rvi="RVI",
            col_id_corto="Short",
            col_clase_name="Name",
            col_metadata_list="Meta",
        )
        svc = MappingService(src, columns=cfg)
        m = svc.get_mapping("XX99")
        assert m.clase_id == "01.01.01.01.01"
        assert m.id_corto == "SH99"
        assert m.required_metadata_fields == ("CIF",)
        src.close()

    def test_columns_config_is_frozen(self) -> None:
        cfg = MappingColumnsConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.col_id_rvi = "OTHER"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_required_column_raises(self, tmp_path: Path) -> None:
        bad_csv = tmp_path / "bad.csv"
        # Missing the "ID RVI" column.
        bad_csv.write_text(
            "ID CLASE DOCUMENTAL,ID Corto,CLASE DOCUMENTAL,METADATOS\n"
            "01.01.01.01.01,SH01,Bad,CIF\n",
            encoding="utf-8",
        )
        src = TabularDataSource(bad_csv)
        with pytest.raises(ConfigurationError) as excinfo:
            MappingService(src)
        assert excinfo.value.context.get("missing_column") == "ID RVI"
        src.close()

    def test_empty_source_constructs_with_empty_cache(self, tmp_path: Path) -> None:
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text(
            "ID CLASE DOCUMENTAL,ID RVI,ID Corto,CLASE DOCUMENTAL,METADATOS\n",
            encoding="utf-8",
        )
        src = TabularDataSource(empty_csv)
        svc = MappingService(src)
        assert svc.count() == 0
        with pytest.raises(IDRViNotMappedError):
            svc.get_mapping("ANY")
        src.close()

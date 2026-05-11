"""Unit tests for ``MappingService`` in split mode (035).

Split mode reads two ``IDataSource`` instances:

* ``rvi_cm`` — ``MapeoRVI_CM.csv``: one row per IDRVI with the columns
  IDSistema, IDRVI, IDCM, IDClaseDocumental, CMISType.
* ``metadatos`` — ``MetadatosCM.csv``: many rows per IDCorto with the
  columns IDCorto, Metadato, Requerido.

Tests use an in-memory ``IDataSource`` (a thin tuple-wrapping fake)
because the SUT is the service, not the adapter. Constitution
Principle VI: don't mock the port the SUT consumes; provide a real,
fast, deterministic implementation.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from cmcourier.domain.ports import IDataSource
from cmcourier.services.mapping import MappingColumnsConfig, MappingService

pytestmark = pytest.mark.unit


class _FakeSource:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def get_all(self) -> Iterator[dict[str, object]]:
        return iter(self._rows)

    def close(self) -> None:  # pragma: no cover - protocol completeness
        pass


def _rvi_cm_rows(*items: tuple[str, str, str, str]) -> list[dict[str, object]]:
    """Build MapeoRVI_CM rows from ``(idrvi, idcm, idclase, cmis_type)`` tuples."""
    return [
        {
            "IDSistema": "",
            "IDRVI": idrvi,
            "IDCM": idcm,
            "IDClaseDocumental": idclase,
            "CMISType": cmis_type,
        }
        for idrvi, idcm, idclase, cmis_type in items
    ]


def _metadatos_rows(*items: tuple[str, str, str]) -> list[dict[str, object]]:
    """Build MetadatosCM rows from ``(idcorto, metadato, requerido)`` tuples."""
    return [
        {"IDCorto": idcorto, "Metadato": meta, "Requerido": req} for idcorto, meta, req in items
    ]


class TestSplitModeBasics:
    def test_joins_two_sources(self) -> None:
        rvi_cm: IDataSource = _FakeSource(  # type: ignore[assignment]
            _rvi_cm_rows(
                ("FB01", "CN01", "01.01.01.01.01", "ClaseDocCN01"),
                ("FB23", "CN02", "01.01.01.01.02", "ClaseDocCN02"),
            )
        )
        metadatos: IDataSource = _FakeSource(  # type: ignore[assignment]
            _metadatos_rows(
                ("CN01", "CIF", "Yes"),
                ("CN01", "Nombre_Cliente", "Yes"),
                ("CN02", "CIF", "Yes"),
            )
        )
        svc = MappingService(rvi_cm, metadata_source=metadatos)
        assert svc.count() == 2

        m1 = svc.get_mapping("FB01")
        assert m1.clase_id == "01.01.01.01.01"
        assert m1.id_corto == "CN01"
        assert m1.cmis_type == "ClaseDocCN01"
        assert m1.required_metadata_fields == ("CIF", "Nombre_Cliente")

        m2 = svc.get_mapping("FB23")
        assert m2.id_corto == "CN02"
        assert m2.required_metadata_fields == ("CIF",)

    def test_uses_clase_id_as_clase_name(self) -> None:
        rvi_cm = _FakeSource(_rvi_cm_rows(("FB01", "CN01", "01.01.01.01.01", "X")))
        metadatos = _FakeSource(_metadatos_rows(("CN01", "CIF", "Yes")))
        svc = MappingService(rvi_cm, metadata_source=metadatos)  # type: ignore[arg-type]
        m = svc.get_mapping("FB01")
        # Production CSV has no human-readable name column. The service
        # falls back to clase_id so logs / inspect output still have
        # something printable.
        assert m.clase_name == m.clase_id == "01.01.01.01.01"


class TestSplitModeRequiredFilter:
    def test_filters_non_required_metadata(self) -> None:
        rvi_cm = _FakeSource(_rvi_cm_rows(("FB01", "CN01", "01.01.01.01.01", "")))
        metadatos = _FakeSource(
            _metadatos_rows(
                ("CN01", "CIF", "Yes"),
                ("CN01", "Optional_Field", "No"),
                ("CN01", "Nombre_Cliente", "Yes"),
            )
        )
        svc = MappingService(rvi_cm, metadata_source=metadatos)  # type: ignore[arg-type]
        m = svc.get_mapping("FB01")
        assert m.required_metadata_fields == ("CIF", "Nombre_Cliente")

    @pytest.mark.parametrize(
        "marker",
        ["Yes", "YES", "yes", "Sí", "SÍ", "si", "True", "true", "1"],
    )
    def test_required_marker_case_insensitive_and_synonyms(self, marker: str) -> None:
        rvi_cm = _FakeSource(_rvi_cm_rows(("FB01", "CN01", "01.01.01.01.01", "")))
        metadatos = _FakeSource(_metadatos_rows(("CN01", "CIF", marker)))
        svc = MappingService(rvi_cm, metadata_source=metadatos)  # type: ignore[arg-type]
        assert svc.get_mapping("FB01").required_metadata_fields == ("CIF",)

    @pytest.mark.parametrize("marker", ["No", "NO", "False", "0", ""])
    def test_non_required_markers_drop_field(self, marker: str) -> None:
        rvi_cm = _FakeSource(_rvi_cm_rows(("FB01", "CN01", "01.01.01.01.01", "")))
        metadatos = _FakeSource(_metadatos_rows(("CN01", "Maybe", marker)))
        svc = MappingService(rvi_cm, metadata_source=metadatos)  # type: ignore[arg-type]
        assert svc.get_mapping("FB01").required_metadata_fields == ()


class TestSplitModeEdgeCases:
    def test_strips_whitespace_in_metadata_fields(self) -> None:
        # Real MetadatosCM.csv has " Short_Name" with a leading space.
        rvi_cm = _FakeSource(_rvi_cm_rows(("FB01", "CN01", "01.01.01.01.01", "")))
        metadatos = _FakeSource(
            _metadatos_rows(
                ("CN01", " Short_Name", "Yes"),
                ("CN01", "  CIF  ", "Yes"),
            )
        )
        svc = MappingService(rvi_cm, metadata_source=metadatos)  # type: ignore[arg-type]
        m = svc.get_mapping("FB01")
        assert m.required_metadata_fields == ("Short_Name", "CIF")

    def test_id_corto_with_no_metadata_rows_yields_empty_tuple(self) -> None:
        rvi_cm = _FakeSource(_rvi_cm_rows(("FB01", "CN01", "01.01.01.01.01", "")))
        metadatos: _FakeSource = _FakeSource([])
        svc = MappingService(rvi_cm, metadata_source=metadatos)  # type: ignore[arg-type]
        m = svc.get_mapping("FB01")
        assert m.required_metadata_fields == ()

    def test_empty_cmis_type_defaults_to_empty_string(self) -> None:
        rvi_cm = _FakeSource(_rvi_cm_rows(("FB01", "CN01", "01.01.01.01.01", "")))
        metadatos = _FakeSource(_metadatos_rows(("CN01", "CIF", "Yes")))
        svc = MappingService(rvi_cm, metadata_source=metadatos)  # type: ignore[arg-type]
        assert svc.get_mapping("FB01").cmis_type == ""

    def test_duplicate_idrvi_drops_subsequent(self, caplog: pytest.LogCaptureFixture) -> None:
        rvi_cm = _FakeSource(
            _rvi_cm_rows(
                ("FB01", "CN01", "01.01.01.01.01", ""),
                ("FB01", "CN02", "01.01.01.01.02", ""),  # dup IDRVI
            )
        )
        metadatos = _FakeSource(_metadatos_rows(("CN01", "CIF", "Yes")))
        with caplog.at_level(logging.WARNING):
            svc = MappingService(rvi_cm, metadata_source=metadatos)  # type: ignore[arg-type]
        assert svc.count() == 1
        assert svc.get_mapping("FB01").id_corto == "CN01"
        assert any("FB01" in r.message for r in caplog.records)

    def test_blank_idrvi_rows_skipped(self) -> None:
        rvi_cm = _FakeSource(
            [
                {
                    "IDSistema": "",
                    "IDRVI": "",
                    "IDCM": "CN99",
                    "IDClaseDocumental": "junk",
                    "CMISType": "",
                },
                *_rvi_cm_rows(("FB01", "CN01", "01.01.01.01.01", "")),
            ]
        )
        metadatos = _FakeSource(_metadatos_rows(("CN01", "CIF", "Yes")))
        svc = MappingService(rvi_cm, metadata_source=metadatos)  # type: ignore[arg-type]
        assert svc.count() == 1
        assert "FB01" in svc


class TestSplitModeColumnOverrides:
    def test_custom_column_names_propagate(self) -> None:
        rvi_cm = _FakeSource(
            [
                {
                    "Sys": "",
                    "RVI": "FB01",
                    "ShortID": "CN01",
                    "ClassID": "01.01.01.01.01",
                    "DocType": "myType",
                }
            ]
        )
        metadatos = _FakeSource([{"Short": "CN01", "Field": "CIF", "Req": "Yes"}])
        cols = MappingColumnsConfig(
            col_rvi_cm_id_rvi="RVI",
            col_rvi_cm_id_cm="ShortID",
            col_rvi_cm_clase_id="ClassID",
            col_rvi_cm_cmis_type="DocType",
            col_metadatos_id_corto="Short",
            col_metadatos_metadata="Field",
            col_metadatos_required="Req",
        )
        svc = MappingService(rvi_cm, columns=cols, metadata_source=metadatos)  # type: ignore[arg-type]
        m = svc.get_mapping("FB01")
        assert m.id_corto == "CN01"
        assert m.clase_id == "01.01.01.01.01"
        assert m.cmis_type == "myType"
        assert m.required_metadata_fields == ("CIF",)

    def test_custom_required_marker(self) -> None:
        rvi_cm = _FakeSource(_rvi_cm_rows(("FB01", "CN01", "01.01.01.01.01", "")))
        metadatos = _FakeSource(
            _metadatos_rows(
                ("CN01", "CIF", "REQUIRED"),
                ("CN01", "Optional", "OPTIONAL"),
            )
        )
        cols = MappingColumnsConfig(required_marker="REQUIRED")
        svc = MappingService(rvi_cm, columns=cols, metadata_source=metadatos)  # type: ignore[arg-type]
        assert svc.get_mapping("FB01").required_metadata_fields == ("CIF",)

"""Tests unitarios para ``cmcourier.observability.pii.is_pii_name`` y
``mask_dict`` (038).

El clásico ``PiiMaskingFilter`` (filtro de logging) se ejercita de
forma indirecta a través de los tests de logging existentes; estos
tests apuntan a los nuevos helpers de conveniencia usados por los
eventos de traza del `payload` de upload.
"""

from __future__ import annotations

import pytest

from cmcourier.observability.pii import MASK, is_pii_name, mask_dict

pytestmark = pytest.mark.unit


class TestIsPiiName:
    @pytest.mark.parametrize(
        "field_name",
        [
            "cif",
            "CIF",
            "customer_name",
            "Customer_Name",
            "account_number",
            "nombre",
            "phone",
            "dni",
        ],
    )
    def test_denylist_match_case_insensitive(self, field_name: str) -> None:
        assert is_pii_name(field_name) is True

    @pytest.mark.parametrize(
        "field_name",
        [
            "pii_anything",
            "pii_random_field",
            "PII_uppercase",
        ],
    )
    def test_pii_prefix_match(self, field_name: str) -> None:
        assert is_pii_name(field_name) is True

    @pytest.mark.parametrize(
        "field_name",
        [
            "clbNonGroup.BAC_CIF",
            "clbNonGroup.CIF",
            "cmcourier:BAC_CIF",
            "cmcourier:Nombre_Cliente",
        ],
    )
    def test_wire_property_id_normalization(self, field_name: str) -> None:
        """Los ids de propiedad `cmis` (`wire`) strippean el prefijo grupo + banco."""
        assert is_pii_name(field_name) is True

    @pytest.mark.parametrize(
        "field_name",
        [
            "txn_num",
            "cmis:objectTypeId",
            "cmis:name",
            "url",
            "duration_ms",
            "status",
        ],
    )
    def test_safe_fields_not_pii(self, field_name: str) -> None:
        assert is_pii_name(field_name) is False


class TestMaskDict:
    def test_masks_pii_keys(self) -> None:
        result = mask_dict({"cif": "00123456", "cmis:name": "foo.pdf"})
        assert result["cif"] == MASK
        assert result["cmis:name"] == "foo.pdf"

    def test_masks_wire_level_property_ids(self) -> None:
        result = mask_dict(
            {
                "clbNonGroup.BAC_CIF": "00123456",
                "cmcourier:Nombre_Cliente": "Juan Perez",
                "cmis:objectTypeId": "D:cmcourier:bacDoc",
            }
        )
        assert result["clbNonGroup.BAC_CIF"] == MASK
        assert result["cmcourier:Nombre_Cliente"] == MASK
        assert result["cmis:objectTypeId"] == "D:cmcourier:bacDoc"

    def test_unmask_returns_input_verbatim(self) -> None:
        original = {"cif": "00123456", "cmis:name": "foo.pdf"}
        result = mask_dict(original, unmask=True)
        assert result == original
        # Y es una copia, no la misma referencia de dict.
        assert result is not original

    def test_keys_preserved_verbatim(self) -> None:
        result = mask_dict({"cif": "x", "phone": "y"})
        assert set(result.keys()) == {"cif", "phone"}

    def test_empty_input_returns_empty(self) -> None:
        assert mask_dict({}) == {}

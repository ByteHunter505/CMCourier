"""Tests unitarios para ``_normalize_row`` en ``As400DataSource`` (074).

Los campos ``CHAR(N)`` de DB2 / iSeries vuelven *padded* a longitud
fija con espacios. El adapter strippea esa padding en la frontera
adapter-dominio para que los consumers (S1 indexing, S3 metadata,
mock generate) trabajen con strings limpios.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from cmcourier.adapters.sources.as400 import _normalize_row

pytestmark = pytest.mark.unit


class TestNormalizeRowStrings:
    """Strings con whitespace se strippean — el problema central."""

    def test_single_space_becomes_empty_string(self) -> None:
        # El caso real que rompía: CHAR(1) con valor lógico vacío
        # vuelve como ``" "`` y el check de "deleted" lo trataba como
        # truthy.
        assert _normalize_row(["ABACST"], [" "]) == {"ABACST": ""}

    def test_trailing_padding_is_stripped(self) -> None:
        assert _normalize_row(["ABABCD"], ["SHORT1  "]) == {"ABABCD": "SHORT1"}

    def test_leading_and_trailing_whitespace_both_stripped(self) -> None:
        assert _normalize_row(["X"], ["  YES  "]) == {"X": "YES"}

    def test_empty_string_stays_empty(self) -> None:
        assert _normalize_row(["X"], [""]) == {"X": ""}

    def test_string_with_only_whitespace_becomes_empty(self) -> None:
        # CHAR(4) padded entero con espacios.
        assert _normalize_row(["X"], ["    "]) == {"X": ""}

    def test_internal_whitespace_preserved(self) -> None:
        # Strippeamos solo los bordes; un campo con espacio en el
        # medio (`"JUAN PEREZ"`) no se toca.
        assert _normalize_row(["NAME"], ["JUAN PEREZ"]) == {"NAME": "JUAN PEREZ"}


class TestNormalizeRowNonStrings:
    """Tipos no-``str`` pasan sin modificación."""

    def test_int_passes_through(self) -> None:
        assert _normalize_row(["N"], [5]) == {"N": 5}

    def test_float_passes_through(self) -> None:
        assert _normalize_row(["F"], [1.5]) == {"F": 1.5}

    def test_decimal_passes_through(self) -> None:
        # DB2 NUMERIC / DECIMAL vuelve como ``Decimal`` desde pyodbc.
        result = _normalize_row(["D"], [Decimal("12345.67")])
        assert result["D"] == Decimal("12345.67")
        assert isinstance(result["D"], Decimal)

    def test_bool_passes_through(self) -> None:
        assert _normalize_row(["B"], [True]) == {"B": True}

    def test_none_passes_through(self) -> None:
        assert _normalize_row(["N"], [None]) == {"N": None}

    def test_date_passes_through(self) -> None:
        d = date(2026, 5, 17)
        result = _normalize_row(["DA"], [d])
        assert result["DA"] == d
        assert isinstance(result["DA"], date)

    def test_datetime_passes_through(self) -> None:
        dt = datetime(2026, 5, 17, 12, 30, 0)
        result = _normalize_row(["DT"], [dt])
        assert result["DT"] == dt
        assert isinstance(result["DT"], datetime)

    def test_bytes_pass_through(self) -> None:
        assert _normalize_row(["BLOB"], [b"binary"]) == {"BLOB": b"binary"}


class TestNormalizeRowMixed:
    """Filas reales mezclan str padded + numerics + dates + null."""

    def test_realistic_rvabrep_row(self) -> None:
        # Simula una fila RVABREP típica con CHAR padded.
        row = _normalize_row(
            ["ABABCD", "ABAACD", "ABACST", "ABAANB", "ABABUN", "ABAADT", "ABAJCD"],
            [
                "SHORT1  ",  # CHAR(8), shortname padded
                "BAC ",  # CHAR(4), system_id padded
                " ",  # CHAR(1), delete_code vacío como espacio
                "RV12345678",  # CHAR(10), txn_num lleno (sin padding)
                5,  # INTEGER, total_pages
                date(2026, 5, 17),  # DATE, creation_date
                None,  # NULLable column
            ],
        )
        assert row == {
            "ABABCD": "SHORT1",
            "ABAACD": "BAC",
            "ABACST": "",
            "ABAANB": "RV12345678",
            "ABABUN": 5,
            "ABAADT": date(2026, 5, 17),
            "ABAJCD": None,
        }

    def test_more_columns_than_values_truncates_at_zip(self) -> None:
        # Edge: pyodbc no debería devolver esto, pero ``zip(strict=False)``
        # silencia el desajuste — documentamos el comportamiento.
        result = _normalize_row(["A", "B", "C"], ["x  "])
        assert result == {"A": "x"}

    def test_empty_columns_and_row_returns_empty_dict(self) -> None:
        assert _normalize_row([], []) == {}

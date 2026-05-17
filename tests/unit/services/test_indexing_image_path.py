"""Tests unitarios para ``_normalize_image_path`` en IndexingService (075)."""

from __future__ import annotations

import pytest

from cmcourier.services.indexing import _normalize_image_path

pytestmark = pytest.mark.unit


class TestNormalizeImagePath:
    """El RVI escribe ``ABAICD`` con leading separators (paths "absolutos"
    desde la raíz del file share). Pre-075 ese leading separator hacía
    que ``pathlib.Path / Path`` descartara ``source_root`` silenciosamente.
    """

    def test_relative_path_passes_through(self) -> None:
        assert _normalize_image_path("RVI9/020526/0004") == "RVI9/020526/0004"

    def test_leading_forward_slash_is_stripped(self) -> None:
        # El caso real del banco — ``/RVI9/020526/0004``.
        assert _normalize_image_path("/RVI9/020526/0004") == "RVI9/020526/0004"

    def test_leading_backslash_is_stripped_and_separators_normalized(self) -> None:
        # Banco Windows-style (raro pero posible en RVI exportado a PC).
        assert _normalize_image_path("\\RVI9\\020526\\0004") == "RVI9/020526/0004"

    def test_mixed_separators_normalized_to_forward_slash(self) -> None:
        assert _normalize_image_path("/RVI9\\020526/0004") == "RVI9/020526/0004"

    def test_double_leading_slashes_stripped(self) -> None:
        assert _normalize_image_path("//RVI9/020526/0004") == "RVI9/020526/0004"

    def test_whitespace_around_stripped(self) -> None:
        assert _normalize_image_path("  /RVI9/020526/0004  ") == "RVI9/020526/0004"

    def test_empty_string_stays_empty(self) -> None:
        assert _normalize_image_path("") == ""

    def test_only_separators_becomes_empty(self) -> None:
        # Edge: si llega "///" (data corrupta o vacía), no rompemos —
        # devolvemos "" y el callsite decide qué hacer.
        assert _normalize_image_path("///") == ""

    def test_internal_separators_preserved(self) -> None:
        # No strippeamos en el medio — esos son separadores reales.
        assert _normalize_image_path("/a/b/c/d") == "a/b/c/d"

    def test_trailing_slash_preserved(self) -> None:
        # Solo strippeamos al inicio. Un trailing ``/`` no nos molesta
        # — pathlib lo absorbe al concatenar.
        assert _normalize_image_path("/RVI9/020526/0004/") == "RVI9/020526/0004/"

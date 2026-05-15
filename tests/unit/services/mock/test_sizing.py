"""Tests unitarios para ``cmcourier.services.mock.sizing.parse_size`` (031, REQ-001..REQ-005)."""

from __future__ import annotations

import pytest

from cmcourier.services.mock.sizing import parse_size


class TestParseSizeHappyPath:
    """REQ-001/002/003: parsea conteos de bytes con sufijos binarios opcionales."""

    def test_bytes_no_suffix(self) -> None:
        assert parse_size("500") == 500

    def test_bytes_b_suffix(self) -> None:
        assert parse_size("500b") == 500

    def test_kilobytes(self) -> None:
        assert parse_size("10kb") == 10 * 1024

    def test_megabytes(self) -> None:
        assert parse_size("2mb") == 2 * 1024 * 1024

    def test_gigabytes(self) -> None:
        assert parse_size("1gb") == 1024 * 1024 * 1024

    def test_decimal_value(self) -> None:
        assert parse_size("2.5kb") == 2560

    def test_decimal_value_mb(self) -> None:
        assert parse_size("1.5mb") == int(1.5 * 1024 * 1024)

    def test_whitespace_around_value_and_suffix(self) -> None:
        assert parse_size("  10  kb  ") == 10 * 1024

    @pytest.mark.parametrize("text", ["10KB", "10Kb", "10kB", "10MB", "10mB"])
    def test_case_insensitive_suffix(self, text: str) -> None:
        # Los dos primeros dan 10 kb; el resto da 10 mb — el valor se parsea
        # primero.
        value = 10 * (1024 if text.lower().endswith("kb") else 1024 * 1024)
        assert parse_size(text) == value

    def test_zero_bytes_is_legal(self) -> None:
        assert parse_size("0") == 0
        assert parse_size("0kb") == 0


class TestParseSizeRejects:
    """REQ-004: entradas inválidas levantan ``ValueError``."""

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "abc",
            "-5kb",
            "5tb",
            "5 5kb",
            "kb",
            "1.2.3kb",
            "1e3kb",
        ],
    )
    def test_invalid_inputs_raise(self, bad: str) -> None:
        with pytest.raises(ValueError, match="invalid size"):
            parse_size(bad)

    def test_error_message_quotes_input(self) -> None:
        with pytest.raises(ValueError, match=r"'totally not a size'"):
            parse_size("totally not a size")

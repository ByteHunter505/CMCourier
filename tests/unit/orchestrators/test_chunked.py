"""Tests unitarios para el helper de `chunk`er (028, REQ-005)."""

from __future__ import annotations

import pytest

from cmcourier.orchestrators.chunked import chunked


class TestChunked:
    def test_empty_input_yields_nothing(self) -> None:
        assert list(chunked([], 3)) == []

    def test_exact_multiple(self) -> None:
        assert list(chunked([1, 2, 3, 4, 5, 6], 3)) == [[1, 2, 3], [4, 5, 6]]

    def test_uneven_last_chunk_is_smaller(self) -> None:
        assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]

    def test_size_larger_than_input_returns_one_chunk(self) -> None:
        assert list(chunked([1, 2, 3], 100)) == [[1, 2, 3]]

    def test_size_one(self) -> None:
        assert list(chunked([1, 2, 3], 1)) == [[1], [2], [3]]

    def test_size_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            list(chunked([1, 2, 3], 0))

    def test_preserves_order(self) -> None:
        items = list(range(20))
        flattened = [x for chunk in chunked(items, 7) for x in chunk]
        assert flattened == items

    def test_accepts_iterator(self) -> None:
        def gen():
            yield from range(5)

        assert list(chunked(gen(), 2)) == [[0, 1], [2, 3], [4]]

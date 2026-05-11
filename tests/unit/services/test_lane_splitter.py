"""Unit tests for :func:`cmcourier.services.lane_splitter.split` (036).

The splitter is a pure function. Tests exercise:

* Small batch → single-lane fallback (no split overhead worth it).
* Bimodal batch → correct partition by ``threshold_bytes``.
* All-small / all-large degenerate batches → single-lane fallback
  (a "lane" with zero items has no benefit over single).
* Order preservation within each lane.
* Polymorphic ``size_of`` accessor (works for any item type).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cmcourier.services.lane_splitter import LaneAssignment, split

pytestmark = pytest.mark.unit


@dataclass(frozen=True, slots=True)
class _Item:
    txn: str
    size: int


def _size_of(item: _Item) -> int:
    return item.size


_KB = 1024
_MB = 1024 * 1024


class TestSmallBatchFallback:
    def test_below_min_batch_returns_single_lane(self) -> None:
        items = [_Item(f"t{i:03d}", 50 * _MB) for i in range(10)]
        result = split(items, threshold_bytes=10 * _MB, min_batch=50, size_of=_size_of)
        assert result.is_single_lane is True
        assert result.heavy == ()
        assert result.light == tuple(items)

    def test_at_min_batch_runs_split(self) -> None:
        items = [_Item(f"t{i:03d}", (50 if i < 5 else 1) * _MB) for i in range(50)]
        result = split(items, threshold_bytes=10 * _MB, min_batch=50, size_of=_size_of)
        assert result.is_single_lane is False
        assert len(result.heavy) == 5
        assert len(result.light) == 45


class TestPartitioning:
    def test_bimodal_batch_partitions_by_threshold(self) -> None:
        items = [_Item(f"h{i:03d}", 50 * _MB) for i in range(5)] + [
            _Item(f"l{i:03d}", 200 * _KB) for i in range(45)
        ]
        result = split(items, threshold_bytes=10 * _MB, min_batch=10, size_of=_size_of)
        assert result.is_single_lane is False
        assert {it.txn for it in result.heavy} == {f"h{i:03d}" for i in range(5)}
        assert {it.txn for it in result.light} == {f"l{i:03d}" for i in range(45)}

    def test_exact_threshold_lands_in_heavy(self) -> None:
        items = [_Item(f"t{i:03d}", 10 * _MB) for i in range(50)] + [_Item("small", 1 * _KB)]
        result = split(items, threshold_bytes=10 * _MB, min_batch=10, size_of=_size_of)
        assert result.is_single_lane is False
        # >= threshold → heavy. The 10 MB items all go heavy.
        assert len(result.heavy) == 50
        assert len(result.light) == 1

    def test_strictly_above_threshold_lands_in_heavy(self) -> None:
        item_heavy = _Item("h", 10 * _MB + 1)
        item_light = _Item("l", 10 * _MB - 1)
        items = [item_heavy, item_light] * 25  # 50 items, 25/25 split
        result = split(items, threshold_bytes=10 * _MB, min_batch=10, size_of=_size_of)
        assert all(it.size >= 10 * _MB for it in result.heavy)
        assert all(it.size < 10 * _MB for it in result.light)


class TestDegenerateFallback:
    def test_all_small_collapses_to_single_lane(self) -> None:
        items = [_Item(f"l{i:03d}", 200 * _KB) for i in range(50)]
        result = split(items, threshold_bytes=10 * _MB, min_batch=10, size_of=_size_of)
        # Every item < threshold → heavy lane is empty → single-lane.
        assert result.is_single_lane is True
        assert result.heavy == ()
        assert result.light == tuple(items)

    def test_all_large_collapses_to_single_lane(self) -> None:
        items = [_Item(f"h{i:03d}", 50 * _MB) for i in range(50)]
        result = split(items, threshold_bytes=10 * _MB, min_batch=10, size_of=_size_of)
        # Every item >= threshold → light lane is empty → single-lane.
        assert result.is_single_lane is True
        assert result.heavy == ()
        assert result.light == tuple(items)


class TestOrderAndStability:
    def test_order_preserved_within_each_lane(self) -> None:
        items: list[_Item] = []
        for i in range(50):
            size = (50 if i % 5 == 0 else 1) * _MB
            items.append(_Item(f"t{i:03d}", size))
        result = split(items, threshold_bytes=10 * _MB, min_batch=10, size_of=_size_of)
        heavy_txns = [it.txn for it in result.heavy]
        light_txns = [it.txn for it in result.light]
        assert heavy_txns == sorted(heavy_txns)
        assert light_txns == sorted(light_txns)

    def test_empty_input_returns_single_lane_empty(self) -> None:
        empty: list[_Item] = []
        result = split(empty, threshold_bytes=10 * _MB, min_batch=10, size_of=_size_of)
        assert result.is_single_lane is True
        assert result.heavy == ()
        assert result.light == ()


class TestPolymorphicSizeAccessor:
    def test_works_with_arbitrary_item_type(self) -> None:
        items: list[dict[str, int]] = [
            {"size": 50 * _MB},
            {"size": 200 * _KB},
        ] * 30  # 60 items
        result: LaneAssignment[dict[str, int]] = split(
            items,
            threshold_bytes=10 * _MB,
            min_batch=10,
            size_of=lambda d: d["size"],
        )
        assert result.is_single_lane is False
        assert len(result.heavy) == 30
        assert len(result.light) == 30


class TestLaneAssignmentDataclass:
    def test_assignment_is_frozen(self) -> None:
        la: LaneAssignment[_Item] = LaneAssignment(heavy=(), light=(), is_single_lane=True)
        with pytest.raises(AttributeError):
            la.is_single_lane = False  # type: ignore[misc]

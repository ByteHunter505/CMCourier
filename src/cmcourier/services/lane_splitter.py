"""Heavy/Light lane splitter for S5 upload dispatch (POST-MVP §1, 036).

Pure-function service: takes a list of items and returns a
:class:`LaneAssignment` partitioning them into a ``heavy`` lane and a
``light`` lane based on per-item size.

Rules:

1. If ``len(items) < min_batch`` → ``is_single_lane = True``, all
   items go in ``light`` (caller falls back to single-pool path).
2. Otherwise partition by ``size_of(item) >= threshold_bytes``.
3. **Degenerate fallback**: if either partition would be empty after
   the split, collapse back to single-lane
   (``is_single_lane = True``) — running a "dual lane" with one side
   empty is the same as single, only with extra coordination cost.

Constitution Principle I: domain-only imports + stdlib. No adapter
or service dependencies.
"""

from __future__ import annotations

__all__ = ["Lane", "LaneAssignment", "split"]

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

Lane = Literal["heavy", "light"]

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class LaneAssignment(Generic[_T]):
    """Result of a lane split.

    ``is_single_lane`` is the gate the caller uses to pick the
    legacy single-pool path. When ``True``, ``heavy`` is empty and
    ``light`` carries every input item.
    """

    heavy: tuple[_T, ...]
    light: tuple[_T, ...]
    is_single_lane: bool


def split(
    items: Sequence[_T],
    *,
    threshold_bytes: int,
    min_batch: int,
    size_of: Callable[[_T], int],
) -> LaneAssignment[_T]:
    """Partition *items* into heavy/light lanes.

    Stable order: each lane keeps the input order of the items that
    landed in it.
    """
    if len(items) < min_batch:
        return LaneAssignment(heavy=(), light=tuple(items), is_single_lane=True)

    heavy: list[_T] = []
    light: list[_T] = []
    for item in items:
        if size_of(item) >= threshold_bytes:
            heavy.append(item)
        else:
            light.append(item)

    if not heavy or not light:
        # Degenerate: every item landed on one side. Single-lane is
        # equivalent and skips the coordination overhead.
        return LaneAssignment(heavy=(), light=tuple(items), is_single_lane=True)

    return LaneAssignment(
        heavy=tuple(heavy),
        light=tuple(light),
        is_single_lane=False,
    )

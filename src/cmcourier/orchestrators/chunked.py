"""Pure chunker helper (028).

Used by the multi-batch orchestrator to split a trigger
iterable into batches of ``size`` for producer-consumer
pipelining.
"""

from __future__ import annotations

__all__ = ["chunked"]

from collections.abc import Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")


def chunked(items: Iterable[T], size: int) -> Iterator[list[T]]:
    """Yield successive ``size``-long lists from ``items``.

    The last chunk may be smaller. Order is preserved.
    Accepts any iterable (lists, generators, etc.). Empty
    input yields nothing. ``size`` must be ≥ 1.
    """
    if size < 1:
        raise ValueError(f"chunk size must be >= 1, got {size}")
    chunk: list[T] = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk

"""Helper puro de `chunk`ing (028).

Lo usa el orchestrator multi-batch para partir un iterable de
triggers en `batch`es de ``size`` para `pipelining` producer-consumer.
"""

from __future__ import annotations

__all__ = ["chunked"]

from collections.abc import Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")


def chunked(items: Iterable[T], size: int) -> Iterator[list[T]]:
    """Emite listas sucesivas de longitud ``size`` desde ``items``.

    El último `chunk` puede ser más chico. El orden se preserva.
    Acepta cualquier iterable (listas, generadores, etc.). Una
    entrada vacía no emite nada. ``size`` debe ser ≥ 1.
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

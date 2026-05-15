"""Splitter de lanes `heavy`/`light` para el `dispatch` de upload en
S5 (POST-MVP §1, 036).

Servicio de función pura: toma una lista de ítems y devuelve un
:class:`LaneAssignment` que los particiona en un lane ``heavy`` y un
lane ``light`` según el tamaño por ítem.

Reglas:

1. Si ``len(items) < min_batch`` → ``is_single_lane = True`` y
   todos los ítems van al lane ``light`` (el caller cae al path de
   `pool` único).
2. En caso contrario, particiona por ``size_of(item) >= threshold_bytes``.
3. **Fallback degenerado**: si alguna de las particiones quedaría
   vacía tras el split, colapsa de vuelta a lane único
   (``is_single_lane = True``): correr "lane dual" con un lado vacío
   es equivalente al lane único, solo con costo adicional de
   coordinación.

Principio I de la Constitución: imports solo de domain + stdlib.
Sin dependencias de adapter ni de service.
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
    """Resultado de un split de lane.

    ``is_single_lane`` es el `gate` que usa el caller para elegir el
    path legacy de `pool` único. Cuando es ``True``, ``heavy`` está
    vacío y ``light`` contiene cada ítem de entrada.
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
    """Particiona *items* en lanes `heavy`/`light`.

    Orden estable: cada lane conserva el orden de entrada de los
    ítems que cayeron en él.
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
        # Degenerado: todos los ítems cayeron en un lado. El lane único
        # es equivalente y evita el overhead de coordinación.
        return LaneAssignment(heavy=(), light=tuple(items), is_single_lane=True)

    return LaneAssignment(
        heavy=tuple(heavy),
        light=tuple(light),
        is_single_lane=False,
    )

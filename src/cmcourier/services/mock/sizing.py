"""Parser de conteo de bytes con conciencia de sufijos para el
generador de archivos mock (031, REQ-001..REQ-004).

Módulo puro. Unidades binarias (``1 kb = 1024``). Tolera whitespace.
Sufijo opcional (se trata como bytes crudos). Input inválido lanza
:class:`ValueError`.
"""

from __future__ import annotations

__all__ = ["parse_size"]

import re

_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(b|kb|mb|gb)?\s*$",
    re.IGNORECASE,
)

_MULT: dict[str | None, int] = {
    None: 1,
    "b": 1,
    "kb": 1024,
    "mb": 1024 * 1024,
    "gb": 1024 * 1024 * 1024,
}


def parse_size(text: str) -> int:
    """Devuelve la cantidad de bytes codificada por *text*.

    Acepta un valor entero o decimal no negativo seguido por un
    sufijo opcional de unidad binaria (``b``/``kb``/``mb``/``gb``,
    case-insensitive). Sin sufijo se interpreta como bytes. Tolera
    whitespace alrededor del valor y el sufijo.

    Lanza ``ValueError`` si *text* no matchea esta gramática.
    """
    match = _RE.match(text)
    if match is None:
        raise ValueError(f"invalid size {text!r}")
    value_text, suffix = match.group(1), match.group(2)
    mult = _MULT[suffix.lower() if suffix else None]
    return int(float(value_text) * mult)

"""Suffix-aware byte-count parser for the mock file generator (031, REQ-001..REQ-004).

Pure module. Binary units (``1 kb = 1024``). Whitespace tolerated. Suffix optional
(treated as raw bytes). Invalid input raises :class:`ValueError`.
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
    """Return the byte count encoded by *text*.

    Accepts a non-negative integer or decimal value followed by an optional
    binary-unit suffix (``b``/``kb``/``mb``/``gb``, case-insensitive). Missing
    suffix is treated as bytes. Whitespace around the value and suffix is
    tolerated.

    Raises ``ValueError`` if *text* does not match this grammar.
    """
    match = _RE.match(text)
    if match is None:
        raise ValueError(f"invalid size {text!r}")
    value_text, suffix = match.group(1), match.group(2)
    mult = _MULT[suffix.lower() if suffix else None]
    return int(float(value_text) * mult)

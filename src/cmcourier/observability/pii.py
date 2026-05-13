"""PII masking filter (Constitution Principle VIII).

Denylist-based: fields whose names match a known PII pattern are
redacted to :data:`MASK` before any handler formats them. The
contract for callers is: pass PII via ``extra={"cif": "..."}`` —
the filter catches it. PII embedded in the message string itself
is the caller's bug; we do not regex the message body in MVP.

The filter also emits a DEBUG-level audit record naming the
redacted fields (NOT their values) so PII discipline can be
verified post-hoc without leaking content.
"""

from __future__ import annotations

__all__ = [
    "DENYLIST",
    "MASK",
    "PII_PREFIX",
    "PiiMaskingFilter",
    "is_pii_name",
    "mask_dict",
]

import logging
from collections.abc import Mapping

MASK: str = "***"
PII_PREFIX: str = "pii_"

# Field names whose VALUES are PII. The names themselves are safe to
# log (they identify what was redacted, not who). Lowercased for
# case-insensitive matching.
#
# NOTE: ``name`` is intentionally NOT here even though customer-name is
# PII — it collides with ``LogRecord.name`` (the logger name), which
# would mask the logger identity and triggers an infinite audit-log
# recursion. Use ``customer_name`` / ``nombre`` for the bank-customer
# field instead.
DENYLIST: frozenset[str] = frozenset(
    {
        "cif",
        "customer_name",
        "account_number",
        "nombre",
        "phone",
        "email",
        "address",
        "dni",
    }
)


_audit = logging.getLogger("cmcourier.observability.pii")


class PiiMaskingFilter(logging.Filter):
    """Redact PII values from every ``LogRecord`` in-place.

    Matches field names case-insensitively against :data:`DENYLIST`
    OR any field starting with :data:`PII_PREFIX`. Names are kept
    intact; values are replaced with :data:`MASK`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        masked: list[str] = []
        for key in list(record.__dict__):
            if self._is_pii(key) and record.__dict__[key] != MASK:
                record.__dict__[key] = MASK
                masked.append(key)
        if masked:
            _audit.debug(
                "pii_masked",
                extra={"fields": ",".join(sorted(masked))},
            )
        return True

    @staticmethod
    def _is_pii(field_name: str) -> bool:
        return is_pii_name(field_name)


def is_pii_name(field_name: str) -> bool:
    """Return ``True`` when *field_name* names a PII-bearing field.

    Matches case-insensitively against :data:`DENYLIST` OR any prefix
    starting with :data:`PII_PREFIX`. CMIS property ids carry their
    domain in the suffix after the last ``:`` or ``.`` separator
    (e.g. ``clbNonGroup.BAC_CIF`` -> ``bac_cif``; ``cmcourier:Nombre_Cliente``
    -> ``nombre_cliente``). The suffix is checked against ``DENYLIST``
    after the same normalization the legacy filter uses, so wire-level
    property names map to the same redaction set as ``extra={"cif": ...}``.
    """
    lower = field_name.lower()
    if lower in DENYLIST or lower.startswith(PII_PREFIX):
        return True
    suffix = lower
    for sep in (".", ":"):
        if sep in suffix:
            suffix = suffix.rsplit(sep, 1)[1]
    # Strip a leading bank prefix (e.g. ``bac_cif`` -> ``cif``) so the
    # denylist's friendly names cover wire-level variants.
    bare = suffix.removeprefix("bac_")
    if suffix in DENYLIST or bare in DENYLIST:
        return True
    return any(token in DENYLIST for token in suffix.split("_") if token)


def mask_dict(properties: Mapping[str, str], *, unmask: bool = False) -> dict[str, str]:
    """Return a copy of *properties* with PII values redacted to :data:`MASK`.

    Keys are preserved verbatim — the field names themselves are safe
    to log (they identify what was redacted, not who). Values are
    redacted when the key matches :func:`is_pii_name`. ``unmask=True``
    returns the input verbatim (used by the
    ``observability.unmask_pii`` debugging escape hatch).
    """
    if unmask:
        return dict(properties)
    return {k: (MASK if is_pii_name(k) else v) for k, v in properties.items()}

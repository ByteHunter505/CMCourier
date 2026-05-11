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

__all__ = ["DENYLIST", "MASK", "PII_PREFIX", "PiiMaskingFilter"]

import logging

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
        lower = field_name.lower()
        if lower in DENYLIST:
            return True
        return lower.startswith(PII_PREFIX)

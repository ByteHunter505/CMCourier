"""JSON Lines log formatter for REBIRTH §17.4 tier 1+.

One JSON object per ``logging.LogRecord``. Promotes a whitelist of
structured ``extra={}`` fields to top-level keys so log shippers
and ``jq`` queries can index them directly. Unknown extras are
dropped to keep the schema stable (callers add new field names by
updating ``_ALLOWED_EXTRA_FIELDS`` here).
"""

from __future__ import annotations

__all__ = ["ALLOWED_EXTRA_FIELDS", "JsonFormatter"]

import datetime as _dt
import json
import logging

# Fields the formatter promotes from ``extra`` to top-level JSON keys.
# Anything not listed here stays inside the record's __dict__ but is
# not serialized — keeps the schema predictable for downstream tools.
ALLOWED_EXTRA_FIELDS: frozenset[str] = frozenset(
    {
        "pipeline",
        "stage",
        "batch_id",
        "txn_num",
        "outcome",
        "duration_ms",
        "kind",
        "sql_prefix",
        "row_count",
        "size_bytes",
        "status",
        "url_prefix",
        "total_docs",
        "elapsed_s",
        "throughput_docs_per_s",
        "stages",
        "rank",
        "reason",
        "fields",
    }
)


class JsonFormatter(logging.Formatter):
    """Render a ``LogRecord`` as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": _dt.datetime.fromtimestamp(record.created, tz=_dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ALLOWED_EXTRA_FIELDS:
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_type"] = record.exc_info[0].__name__
            payload["exc_msg"] = str(record.exc_info[1])
        return json.dumps(payload, default=str, ensure_ascii=False)

"""REBIRTH §17.4 observability package.

Tiered structured logging for CMCourier. Layers:

* **Tier 1** — app log (JSON Lines) to ``logs/app-{date}.log``.
* **Tier 2** — pipeline metrics (per-batch summary with p50/p95/p99)
  to ``logs/metrics-{date}.jsonl``.
* **Tier 3** — network metrics (AS400 + CMIS per-request timing)
  to ``logs/network-{date}.jsonl``.
* **Tier 4** — slow-ops report (top-N per batch) to
  ``logs/slow-ops-{batch_id}.jsonl``.
* **Tier 5** — system metrics (CPU/RAM/IO) is deferred to POST-MVP §2.

PII discipline (Constitution VIII): all handlers run through
``PiiMaskingFilter`` which redacts known PII field names.
"""

from __future__ import annotations

__all__ = [
    "BatchSummary",
    "JsonFormatter",
    "MetricsRecorder",
    "NetworkEvent",
    "PiiMaskingFilter",
    "SlowOpAggregator",
    "StageTimer",
    "configure",
]

from cmcourier.observability.formatter import JsonFormatter
from cmcourier.observability.metrics import (
    BatchSummary,
    MetricsRecorder,
    NetworkEvent,
    SlowOpAggregator,
    StageTimer,
)
from cmcourier.observability.pii import PiiMaskingFilter
from cmcourier.observability.setup import configure

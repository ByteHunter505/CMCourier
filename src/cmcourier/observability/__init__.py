"""Paquete de observabilidad por `tiers`.

Logging estructurado en capas para CMCourier. Niveles:

* **`Tier` 1** — log de aplicación (JSON Lines) en ``logs/app-{date}.log``.
* **`Tier` 2** — métricas de pipeline (resumen por batch con p50/p95/p99)
  en ``logs/metrics-{date}.jsonl``.
* **`Tier` 3** — métricas de red (timing por request de AS400 + CMIS)
  en ``logs/network-{date}.jsonl``.
* **`Tier` 4** — reporte de `slow ops` (top-N por batch) en
  ``logs/slow-ops-{batch_id}.jsonl``.
* **`Tier` 5** — métricas de sistema (CPU/RAM/IO), diferido a POST-MVP §2.

Disciplina de `PII` (Principio VIII de la Constitución): todos los handlers
pasan por ``PiiMaskingFilter`` que redacta los nombres de campos `PII`
conocidos.
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

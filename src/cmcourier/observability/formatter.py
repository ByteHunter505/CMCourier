"""Formatter de logs en JSON Lines para la capa de observabilidad `tier` 1+.

Un objeto JSON por cada ``logging.LogRecord``. Promueve un whitelist de
campos estructurados de ``extra={}`` a claves de nivel superior para que
los log shippers y queries de ``jq`` los puedan indexar directamente. Los
extras no listados se descartan para mantener un schema estable (quien
agrega nuevos nombres de campo lo hace actualizando
``_ALLOWED_EXTRA_FIELDS`` acá).
"""

from __future__ import annotations

__all__ = ["ALLOWED_EXTRA_FIELDS", "JsonFormatter"]

import datetime as _dt
import json
import logging

# Campos que el formatter promueve desde ``extra`` a claves de nivel
# superior del JSON. Lo que no esté listado queda dentro del __dict__
# del record pero no se serializa — mantiene el schema predecible para
# las herramientas downstream.
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
        "worker",
        "p95_observed_ms",
        "p95_target_ms",
        "workers_before",
        "workers_after",
        "timeout_before_s",
        "timeout_after_s",
        "action",
        # 038: eventos de trace del payload s5_upload_attempt / s5_upload_failed.
        "event",
        "url",
        "object_type_id",
        "document_name",
        "mime_type",
        "content_bytes",
        "properties_json",
        "status_code",
        "response_body",
        "curl_equivalent",
        # 045: campos de auditoría de s5_upload_409_recovery.
        "recovered_object_id",
        "detail",
    }
)


class JsonFormatter(logging.Formatter):
    """Renderiza un ``LogRecord`` como un objeto JSON de una sola línea."""

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

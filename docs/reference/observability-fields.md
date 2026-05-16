> [← Volver al índice](../INDEX.md) · [Reference](README.md)

# Observability fields

Cada estructura de telemetría que CMCourier emite o expone para la TUI. Los campos salen directo de `src/cmcourier/observability/` y de `src/cmcourier/services/`. Tier sigue la convención del proyecto:

| Tier | Qué es |
|------|--------|
| 1 | App log (`logs/app-*.log`). |
| 2 | Pipeline metrics — `batch_summary` JSON al cerrar batch. |
| 3 | Network events — `NetworkEvent` vía logger `cmcourier.metrics.network`. |
| 4 | Slow ops top-N — `logs/slow-ops-{batch_id}.jsonl`. |
| 5 | System metrics — `logs/system-{date}.jsonl` (psutil). |

---

## `NetworkEvent` (Tier 3)

`observability/metrics.py:41` — frozen dataclass. Los adapters de AS400 y CMIS la emiten como `extra={...}` sobre el logger `cmcourier.metrics.network`. No se escribe sola a disco; el formatter JSON la materializa en el log app.

| Field | Type | Units | Source |
|-------|------|-------|--------|
| `kind` | str | — | `"as400_query"`, `"cmis_request"`, `"cmis_upload"`, etc. |
| `duration_ms` | float | ms | `time.monotonic()` delta del request. |
| `sql_prefix` | str | — | Primeros 80 chars del SQL (truncado, never PII-clean). |
| `row_count` | `int \| None` | rows | Filas devueltas (AS400). |
| `size_bytes` | `int \| None` | bytes | Tamaño del body (CMIS upload). |
| `status` | `int \| None` | HTTP code | 200, 201, 4xx, 5xx (CMIS). |
| `url_prefix` | str | — | Primeros 80 chars de la URL. |
| `txn_num` | str | — | Para correlacionar con `migration_log`. |

Sirve para: análisis offline (`cmcourier analyze`), debug de connectividad, top-N de slow ops.

---

## `SystemSample` (Tier 5)

`observability/system_metrics.py:45` — frozen dataclass. Lo escribe el daemon `SystemMetricsSampler` cada `system_metrics.sample_interval_s` (default 5 s) a `{log_dir}/system-{date}.jsonl`. El primer sample tiene deltas en `0.0` (no hay baseline).

| Field | Type | Units | Source/Calculation |
|-------|------|-------|--------------------|
| `ts_iso` | str | ISO-8601 UTC | `datetime.now(UTC).replace(microsecond=0).isoformat()`. |
| `cpu_pct` | float | % | `psutil.cpu_percent(interval=None)`. |
| `ram_used_mb` | int | MiB | `psutil.virtual_memory().used / 1048576`. |
| `ram_total_mb` | int | MiB | `psutil.virtual_memory().total / 1048576`. |
| `disk_read_mbps` | float | Mb/s (megabits) | Delta `disk_io_counters().read_bytes` × 8 / elapsed / 1048576. |
| `disk_write_mbps` | float | Mb/s | Idem `write_bytes`. |
| `net_in_mbps` | float | Mb/s | Delta `net_io_counters().bytes_recv`. |
| `net_out_mbps` | float | Mb/s | Idem `bytes_sent`. |
| `process_pid` | int | — | `psutil.Process().pid`. |
| `process_threads` | int | count | `psutil.Process().num_threads()`. |
| `process_cpu_pct` | float | % | `psutil.Process().cpu_percent(interval=None)`. |
| `process_rss_mb` | int | MiB | `Process().memory_info().rss / 1048576`. |
| `active_workers` | `int \| None` | count | `WorkerPoolStats.snapshot().busy`. `None` si no hay pool aún. |

Sirve para: detectar saturación host, correlacionar p95 spikes con presión CPU/RAM, capacity planning offline.

---

## `WorkerPoolStatsSnapshot`

`services/worker_pool_stats.py:25` — frozen dataclass. Lectura atómica de los counters del pool S5. Se toma con `WorkerPoolStats.snapshot()`. No se escribe a disco; consume la TUI y `LaneSnapshot`.

| Field | Type | Units | Source |
|-------|------|-------|--------|
| `pool_size` | int | threads | Capacidad actual (resizable por AIMD). |
| `busy` | int | threads | Workers ejecutando upload ahora. |
| `idle` | int | threads | `max(0, pool_size - busy)`. |
| `queue_depth` | int | items | Profundidad de la cola de `as_completed`. |
| `completed` | int | docs | Acumulado de `mark_completed()`. |
| `failed` | int | docs | Acumulado de `mark_failed()`. |

Sirve para: tab UPLOAD de TUI, decisiones del LaneController, system metrics (`active_workers`).

---

## `LaneSnapshot`

`services/lane_controller.py:43` — frozen dataclass. Vista de ambos lanes en un instante. La consume la TUI cuando `heavy_light_lanes.enabled = true`. Se toma con `LaneController.snapshot()`.

| Field | Type | Units | Source |
|-------|------|-------|--------|
| `heavy` | `WorkerPoolStatsSnapshot` | — | Stats de la lane heavy. |
| `light` | `WorkerPoolStatsSnapshot` | — | Stats de la lane light. |
| `total_budget` | int | threads | Budget agregado (heavy.pool_size + light.pool_size). |

Sirve para: sub-bloque LANES de los tabs UPLOAD y BUCKET; debug del rebalance heurístico.

---

## `StreamingSnapshot`

`orchestrators/streaming.py:110` — frozen dataclass. Sólo se llena en `processing.mode = "streaming"`. Consume el tab BUCKET de la TUI. Se toma con `StreamingOrchestrator.streaming_snapshot()`.

| Field | Type | Units | Source |
|-------|------|-------|--------|
| `bucket_level` | int | items | `bucket.qsize()`. |
| `bucket_cap` | int | items | `streaming.bucket_size` del YAML. |
| `bucket_peak` | int | items | Max observado durante la corrida (`_peak_qsize`). |
| `prep_workers` | int | threads | `processing.prep_workers`. |
| `prep_in_flight` | int | docs | Docs ahora mismo en S1–S4. |
| `upload_workers` | int | threads | `cmis.workers` (resizable). |
| `prep_docs_per_s` | float | docs/s | `_ThroughputWindow` 5 s sobre eventos prep-done. |
| `upload_docs_per_s` | float | docs/s | Idem sobre upload-done. |
| `lane_snapshot` | `LaneSnapshot \| None` | — | `None` en single-lane. |

Sirve para: tab BUCKET, detección de cuellos de botella (prep < upload o viceversa).

---

## `_BandwidthSampler` (069)

`observability/metrics.py:170` — clase no congelada. Alimenta el chart de bandwidth del tab UPLOAD. Vive en `MetricsRecorder.bandwidth` (uno por chunk). Se actualiza vía `record_upload(size, *, started_at, completed_at)`, que distribuye los bytes uniformemente sobre los segundos del intervalo `[started_at, completed_at]`.

| Method/Property | Returns | Units | Notes |
|-----------------|---------|-------|-------|
| `record_upload(size_bytes, *, started_at, completed_at)` | — | — | Bytes distribuidos uniformemente. |
| `cumulative_bytes()` | int | bytes | Total desde que arrancó el sampler (por chunk). |
| `current_mbps()` | float | MB/s | Bucket de 1 s anterior al actual (el actual aún se está llenando). |
| `peak_mbps()` | float | MB/s | Max sobre la rolling window de 60 buckets. |
| `series(seconds=60)` | `list[tuple[int, float]]` | — | `[(offset_s_negative, mbps)...]` con el más nuevo al final. |

Ventana rolling: 60 segundos. Más allá, los buckets se descartan.

Sirve para: tab UPLOAD (sparkline + métrica current/peak), correlación con `max_bandwidth_mbps`.

---

## Archivos de salida

| File | Contains | Tier |
|------|----------|------|
| `{log_dir}/app-{date}.log` | App log estructurado (JSON o text). | 1 |
| `{log_dir}/system-{date}.jsonl` | `SystemSample` por línea. | 5 |
| `{log_dir}/slow-ops-{batch_id}.jsonl` | Top-N slow ops del batch. | 4 |
| `{log_dir}/cmcourier.metrics.pipeline.log` | `batch_summary` JSON. | 2 |

Rotación: `rotation_mb` (default 100 MB), `retention_days` (default 30).

## Ver también

- [`config-schema.md`](config-schema.md) — `ObservabilityConfig`, `SystemMetricsConfig`.
- [How-to: log analysis](../how-to/log-analysis.md) — usar `cmcourier analyze` para procesar estos archivos.
- [Explanation: architecture overview](../explanation/architecture-overview.md) — cómo se usan los samples para AIMD.

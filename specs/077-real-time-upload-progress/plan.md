# 077 — Plan

## Cambio 1: `_BandwidthSampler.record_progress`

Agregar al `_BandwidthSampler` en `observability/metrics.py`:

```python
def record_progress(self, bytes_delta: int, ts: float | None = None) -> None:
    """077: agrega ``bytes_delta`` al bucket del segundo current.

    A diferencia de :meth:`record_upload` (que distribuye un total
    sobre ``[started_at, completed_at]`` al completar el upload),
    este método agrega bytes parciales al wall-clock second en
    que se transmiten. Lo llama ``_BandwidthHandler`` con cada
    evento ``cmis_upload_progress`` emitido por el
    ``MultipartEncoderMonitor`` del uploader.

    El bucket se elige según ``ts`` (default ``time.time()``).
    Thread-safe vía el lock interno del sampler.
    """
    if bytes_delta <= 0:
        return
    ts = ts if ts is not None else time.time()
    bucket = int(ts)
    cutoff = bucket - self._WINDOW_SECONDS
    with self._lock:
        self._cumulative_bytes += int(bytes_delta)
        self._buckets[bucket] = self._buckets.get(bucket, 0) + int(bytes_delta)
        stale = [k for k in self._buckets if k < cutoff]
        for k in stale:
            del self._buckets[k]
```

## Cambio 2: `_BandwidthHandler.emit` procesa el nuevo kind

Modificar la función ``emit`` para reconocer `cmis_upload_progress`
además de `cmis_upload`. Estructura final:

```python
def emit(self, record: logging.LogRecord) -> None:
    kind = getattr(record, "kind", "")
    if kind == "cmis_upload_progress":
        if getattr(record, "batch_id", None) != self._batch_id:
            return
        delta = getattr(record, "bytes_delta", None)
        if delta is None or delta <= 0:
            return
        self._sampler.record_progress(int(delta))
        return
    if kind == "cmis_upload":
        if getattr(record, "batch_id", None) != self._batch_id:
            return
        size = getattr(record, "size_bytes", None)
        if size is None:
            return
        # 077: si hubo progress events, ya se contaron — restamos
        # esos bytes del total para evitar double-counting. El
        # residuo es lo que NO alcanzó el threshold del callback.
        progress_bytes = int(getattr(record, "progress_bytes", 0) or 0)
        residual = max(0, int(size) - progress_bytes)
        if residual == 0:
            return  # todo el upload reportado via progress
        # ... lógica 069 existente con residual en lugar de size ...
```

## Cambio 3: uploader usa `MultipartEncoderMonitor`

```python
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

# Constante a nivel de módulo:
_PROGRESS_THRESHOLD_BYTES = 1_048_576  # 1 MB

# En _post_with_retries, dentro del while loop, donde se construye el encoder:

encoder = MultipartEncoder(fields={**data_fields, "content": file_field})
reported_state = {"bytes": 0}  # mutable closure (dict porque python closure rules)

def progress_callback(monitor: MultipartEncoderMonitor) -> None:
    current = monitor.bytes_read
    delta = current - reported_state["bytes"]
    if delta < _PROGRESS_THRESHOLD_BYTES:
        return
    reported_state["bytes"] = current
    _network_log.info(
        "cmis_upload_progress",
        extra={
            "kind": "cmis_upload_progress",
            "batch_id": batch_id,
            "txn_num": txn_num,
            "bytes_delta": delta,
        },
    )

monitored = MultipartEncoderMonitor(encoder, progress_callback)

def _read_chunk(enc: MultipartEncoderMonitor = monitored) -> bytes:
    return bytes(enc.read(8192))

resp = self._client.post(
    url,
    content=iter(_read_chunk, b""),
    headers={
        "Content-Type": monitored.content_type,
        "Content-Length": str(monitored.len),
    },
    timeout=self._timeout_s,
)
```

Después del `client.post`, en `_emit_network` pasamos el contador
acumulado:

```python
self._emit_network(
    kind, t0, status, size_bytes, url, batch_id,
    progress_bytes=reported_state["bytes"],
)
```

Y `_emit_network` agrega `progress_bytes` al `extra={...}` del log
record.

## Tests

`tests/unit/observability/test_bandwidth_progress.py` nuevo:

1. `test_record_progress_adds_to_current_bucket`: llamar
   `record_progress(1024)` y verificar que `current_mbps()` lo
   refleja en el bucket del segundo actual.
2. `test_record_progress_thread_safe`: 10 threads sumando bytes
   concurrentemente, el total es exacto.
3. `test_cumulative_bytes_includes_progress`: progress events
   suman al cumulative igual que record_upload.
4. `test_handler_processes_progress_event`: emitir un
   `cmis_upload_progress` LogRecord y verificar que el sampler
   se actualizó.
5. `test_completion_subtracts_progress_bytes`: emitir progress
   de 8 MB + completion de 10 MB con `progress_bytes=8MB`,
   verificar que el sampler suma 10 MB total (no 18 MB).
6. `test_completion_with_zero_progress_bytes_works_as_pre_077`:
   uploads chiquitos sin progress events, el completion sigue
   con la lógica 069 existente.

## Phased commits

1. `feat: add 077 spec, plan, tasks`
2. `feat(observability): add _BandwidthSampler.record_progress (077)`
3. `feat(observability): process cmis_upload_progress events in handler (077)`
4. `feat(upload): emit cmis_upload_progress events via MultipartEncoderMonitor (077)`
5. `test: cover real-time upload progress (077)`
6. `docs(077): CHANGELOG 0.79.0 + version bump`

## Verificación

```bash
pytest -m unit
cmcourier --version       # 0.79.0
```

Smoke productivo: correr local-scan-pipeline con un archivo de
500 MB y observar la TUI tab UPLOAD. El `current_mbps` debe
moverse cada segundo durante el upload, no quedarse en 0 hasta
que termine.

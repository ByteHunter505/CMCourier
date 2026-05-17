# 077 — Progress de upload en tiempo real

## Por qué

Pre-077, el `_BandwidthSampler` (TUI tab UPLOAD: `current_mbps`,
`peak_mbps`, sparkline) recibe datos **únicamente cuando un
upload completa**. El evento `cmis_upload` se emite en
``CmisUploader._emit_network`` después del `client.post()`, y el
``_BandwidthHandler`` solo reacciona a ese kind de evento.

Para uploads cortos (docs típicos < 1 MB), la TUI actualiza cada
~100-500 ms — fluido a ojo humano. Pero para **uploads grandes**:

* Un archivo de 500 MB tarda ~5-10 segundos contra LAN de 1 Gbps.
* Durante esos 5-10 segundos, **la TUI muestra 0 MB/s**, `peak`
  estancado, sparkline plana.
* Al completar, el sampler procesa el evento, distribuye los
  bytes uniformemente sobre `[started_at, completed_at]` (069),
  y los datos aparecen **de golpe** — pero ya es tarde para
  diagnóstico operativo.

El operador no puede ver "estoy a 60 MB/s sostenido" mientras
sube — solo ve "subió el archivo, el sampler dice que el promedio
fue 60 MB/s" cinco segundos después.

Para producción real con docs grandes (escaneados de 50-200 MB),
saber el progreso EN VIVO es crítico para:

* Diagnosticar uploads colgados (si el progress no avanza, el
  socket está estancado).
* Validar el throughput real de un upload puntual sin esperar el
  completion.
* Detectar throttling intermedio del servidor (progress que cae
  durante el upload).

## Qué

### Arquitectura del fix

`requests-toolbelt` trae `MultipartEncoderMonitor` exactamente
para esto: envuelve un `MultipartEncoder` y llama a un callback
después de cada `.read()`. Pasamos un callback que emite eventos
**parciales** al logging — el ``_BandwidthHandler`` los procesa y
suma al bucket del segundo current del sampler.

```
upload start
   │
   ├─► encoder.read(8KB) → monitor callback(monitor)
   │       └─► si delta >= 1MB: emit "cmis_upload_progress" event
   │       │       _BandwidthHandler.emit() → sampler.record_progress(delta)
   │       │       sampler bucket[now] += delta
   │       │       TUI ve current_mbps actualizado en próximo refresh
   │       │
   │       └─► loop continúa
   │
   ├─► ... más reads, más progress events ...
   │
   └─► upload complete
           └─► "cmis_upload" event con progress_bytes=N
                   _BandwidthHandler procesa: distribuye (size - N) sobre
                   [start, end] usando lógica 069 existente
                   (el delta es el "último chunk" que no alcanzó el
                   threshold; uploads chiquitos con progress_bytes=0
                   funcionan igual que pre-077)
```

### Alcance

* **`observability/metrics.py`**:
  * Agregar `_BandwidthSampler.record_progress(bytes_delta, ts=None)`
    que suma `bytes_delta` al bucket del segundo `int(ts or now)`.
    Mantiene thread-safety y `cumulative_bytes`. Lock compartido
    con `record_upload`.
  * Modificar `_BandwidthHandler.emit` para procesar también el
    kind `cmis_upload_progress`. Cuando el evento llega, llama
    `sampler.record_progress(bytes_delta)`.
  * Modificar el branch de `cmis_upload` (completion) en
    `_BandwidthHandler.emit` para restar `progress_bytes`
    (campo nuevo en el record, default 0) del `size_bytes`
    antes de pasar a `record_upload`. Evita double-counting.

* **`adapters/upload/cmis_uploader.py`**:
  * Importar `MultipartEncoderMonitor` además de `MultipartEncoder`.
  * Construir un `MultipartEncoderMonitor(encoder, callback)` en
    cada attempt; el callback es una closure que:
    * Mantiene un contador local `reported_so_far` (int).
    * Cada vez que el callback dispara (después de cada read),
      calcula `delta = monitor.bytes_read - reported_so_far`.
    * Si `delta >= PROGRESS_THRESHOLD_BYTES` (1 MB), emite
      `_network_log.info("cmis_upload_progress", extra={...})`
      con `bytes_delta`, `batch_id`, `txn_num`, `kind`,
      `duration_ms` (acumulado desde el inicio).
    * Actualiza `reported_so_far = monitor.bytes_read`.
  * Cuando `client.post(...)` retorna (en cualquier branch:
    success, 4xx, 5xx, exception), `_emit_network` incluye el
    nuevo campo `progress_bytes = reported_so_far` en el evento
    `cmis_upload`.

* **Configuración**: el threshold `PROGRESS_THRESHOLD_BYTES` queda
  hardcoded en `cmis_uploader.py` a `1_048_576` (1 MB). Es un
  detalle de telemetría — si aparece necesidad de tuning, se
  expone en config en otra spec.

### Fuera de alcance

* **No tocar la lógica 069** (distribución uniforme sobre
  `[start, end]`). Sigue aplicando al residuo que no se reportó
  como progress events.
* **No agregar progress callback al GET de warmup ni a la
  navegación de carpetas**. Solo el POST de upload.
* **No exponer eventos de progress per-segundo individuales en la
  TUI** (UI no se toca). Solo cambian los samplers internos —
  la TUI ya consulta `current_mbps()` cada 250 ms y verá los
  datos automáticamente.

## Criterios de aceptación

1. Para un upload de 500 MB que tarda 5 segundos, el sampler
   recibe ~500 events `cmis_upload_progress` (uno por cada 1 MB
   transmitido) durante los 5 segundos.
2. La TUI muestra `current_mbps` updateándose continuamente
   durante el upload (cada refresh, no solo al final).
3. **No hay double-counting**: el `cumulative_bytes` final del
   sampler coincide exactamente con `size_bytes` del upload
   (suma de todos los progress events == size_bytes;
   completion event no agrega más).
4. Uploads chicos (sin progress events disparados porque nunca
   superan el threshold) siguen funcionando igual que pre-077 —
   el `cmis_upload` event sigue siendo procesado con la lógica
   069.
5. `cumulative_bytes` es consistente: la suma de todos los
   `bytes_delta` + `(size_bytes - progress_bytes)` del completion
   == `size_bytes`.
6. Tests unit cubren los 4 escenarios.
7. `pytest -m unit` pasa.
8. Pre-commit verde.

## Riesgos

* **Volumen de eventos**: 500 events por upload de 500 MB es OK
  (logs JSON estructurados, el sampler los procesa en <100µs
  cada uno). Si en el futuro aparecen uploads de varios GB, se
  ajusta el threshold.
* **Callback ejecuta en el worker thread del POST**: el callback
  hace `_network_log.info(...)` que es sync; el handler llama
  `sampler.record_progress` que es thread-safe con lock. Sin
  riesgo de deadlock.
* **Si el upload falla a mitad** (5xx, timeout): el handler ya
  procesó N events de progress; el sampler tiene los bytes en
  sus buckets. Al hacer retry, el upload re-emite progress
  desde el inicio + un completion final. **Bytes son contados
  doble en el caso de retry exitoso**. Mitigación: la TUI ya
  muestra `cumulative_bytes` que es informativo, no contractual.
  En condiciones normales sin retry, los números son exactos.
  Aceptable para telemetría — no nos importa precisión al byte
  cuando hay errores transitorios.
* **`MultipartEncoderMonitor` overhead**: callback Python por
  cada chunk de 8 KB. ~125000 callbacks por upload de 1 GB.
  Threshold de 1 MB filtra el 99% del trabajo (solo emite log
  evento cada 128 chunks). Overhead despreciable.

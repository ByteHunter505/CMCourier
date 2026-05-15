# 069 — Sampler de bandwidth: distribuir bytes sobre la ventana de transmisión real

## Por qué

Reportado por el operador durante el mismo run de staging
de 068: bandwidth pico `<20 MB/s` incluso después de que
068 escalara workers agresivamente. Parte de eso es
throughput genuino (el cuello-siguiente es velocidad
per-upload contra Alfresco), pero la **medición misma es
buggy para archivos pesados**.

`_BandwidthSampler.record_upload(size_bytes, completed_at)`
pre-069:

```python
def record_upload(self, size_bytes: int, completed_at: float) -> None:
    ts = int(completed_at)
    self._buckets[ts] = self._buckets.get(ts, 0) + int(size_bytes)
```

Acredita el **tamaño completo del archivo al segundo de
completion**. Para un upload de 30 MB que tomó 3 segundos
(T → T+3), los 30 MB aterrizan en el bucket `T+3`. Los
buckets `T+1`, `T+2` muestran **cero** bytes para ese
upload — aunque estaba transmitiendo activamente durante
ellos.

Consecuencias:

* **Lectura spikeada**: `current_mbps()` (que lee el bucket
  completo anterior) se da vuelta entre "spike" y "valle"
  dependiendo de si una completion ocurrió en ese bucket.
  El operador ve p. ej. `current 11 MB/s` un segundo,
  `current 0 MB/s` el siguiente.
* **Forma de sparkline incorrecta**: el chart rolling de
  60 buckets muestra spikes en los momentos de completion
  en vez de la forma de transmisión continua.
* **Pico engañoso**: una sola completion de 30 MB en un
  segundo reporta `peak 30 MB/s` aun cuando el throughput
  sostenido real es ~10 MB/s.
* **Diagnóstico bloqueado**: el operador no puede
  distinguir "el pipe es genuinamente lento" de "la
  medición está mal" sin re-derivar
  `cumulative_bytes / elapsed_s` manualmente.

## Qué

`record_upload` toma una ventana de transmisión —
`started_at` y `completed_at` — y **distribuye los bytes
uniformemente a través de los segundos que la transmisión
realmente abarcó**. Para un upload de 30 MB de T=10.5 a
T=13.5 (3 segundos), aterrizan 10 MB en cada uno de los
buckets {10, 11, 12, 13} (con segundos fraccionarios
manejados por asignaciones parciales).

### Nueva firma

```python
def record_upload(
    self,
    size_bytes: int,
    *,
    started_at: float,
    completed_at: float,
) -> None:
```

La firma posicional vieja `(size_bytes, completed_at)` se
descarta. Los callers deben pasar los dos timestamps. Hay
exactamente un caller adentro de CMCourier:
`_BandwidthHandler.emit` (el log handler que alimenta el
sampler desde los eventos de red `cmis_upload`). El handler
ya tiene los dos — `record.created` es `completed_at`, y
el payload del evento `cmis_upload` lleva `duration_ms`
(derivamos `started_at = completed_at - duration_ms/1000`).

### Algoritmo de distribución

```python
def record_upload(self, size_bytes, *, started_at, completed_at):
    duration = max(completed_at - started_at, 1e-6)
    bytes_per_s = size_bytes / duration
    start_ts = int(math.floor(started_at))
    end_ts = int(math.floor(completed_at))
    cutoff = end_ts - self._WINDOW_SECONDS
    with self._lock:
        self._cumulative_bytes += int(size_bytes)
        for ts in range(start_ts, end_ts + 1):
            # Solapamiento de [ts, ts+1) con [started_at, completed_at]
            overlap_start = max(started_at, float(ts))
            overlap_end = min(completed_at, float(ts) + 1.0)
            overlap = overlap_end - overlap_start
            if overlap <= 0:
                continue
            bytes_in_bucket = int(bytes_per_s * overlap)
            self._buckets[ts] = self._buckets.get(ts, 0) + bytes_in_bucket
        # Desalojar buckets viejos
        stale = [k for k in self._buckets if k < cutoff]
        for k in stale:
            del self._buckets[k]
```

Se asume que la tasa de transmisión es constante adentro
de un upload (distribución uniforme). Para uploads largos
en redes estables esto es fiel; para uploads con
transmisión interna bursty está ligeramente smootheado —
aceptable para una view agregada.

### Cambio en `_BandwidthHandler`

```python
def emit(self, record: logging.LogRecord) -> None:
    ...
    duration_ms = getattr(record, "duration_ms", 0.0)
    completed_at = record.created
    started_at = completed_at - (float(duration_ms) / 1000.0)
    self._sampler.record_upload(
        int(size),
        started_at=started_at,
        completed_at=completed_at,
    )
```

El evento `cmis_upload` siempre lleva `duration_ms`
(seteado por `_emit_network` en el CmisUploader). Cuando
está sin setear o en cero, el handler hace fallback a
acreditar todos los bytes al segundo de completion
(comportamiento pre-069, solo defensivo — no debería
disparar en la práctica).

## Fuera de alcance

- Medición de bandwidth per-stream (per-host,
  per-conexión).
- Medición de bandwidth durante la transmisión misma (vs
  después de completion). Requeriría callbacks de
  progreso streaming de httpx, una superficie mucho más
  grande.

## Criterios de aceptación

- `_BandwidthSampler.record_upload(size, *, started_at, completed_at)`
  distribuye los bytes uniformemente sobre los buckets de
  segundos que solapan `[started_at, completed_at]`.
- Un upload de 30 MB de `T+0.5` a `T+3.5` (span de 3.0
  s) aterriza ~5 MB en bucket `T`, 10 MB en `T+1`, 10 MB
  en `T+2`, 5 MB en `T+3` (dentro de la tolerancia de
  floor-rounding).
- `cumulative_bytes` sigue siendo la suma de todos los
  uploads (sin double-counting).
- `peak_mbps` es la tasa más alta de un solo bucket
  (ahora refleja throughput sostenido real, no el spike
  de completion).
- `series(seconds)` devuelve el chart windoweado con la
  nueva forma suave.
- `_BandwidthHandler.emit` lee `duration_ms` del log
  record y deriva `started_at`. Default a acreditar en
  completion cuando `duration_ms` está
  ausente/cero.
- Todos los tests existentes actualizados para usar la
  firma nueva.
- mypy + ruff limpios.
- CHANGELOG `[0.71.0]`; pyproject 0.70.0 → 0.71.0.

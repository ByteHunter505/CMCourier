# 090 — `cmis.upload_chunk_bytes` configurable (fix GIL contention en paralelos)

## Por qué

Bug de throughput descubierto en pruebas productivas. Observación:

| Escenario | Throughput |
|---|---|
| `curl` 1 archivo grande, HTTP/1.1 | ~100 MB/s (satura el link) |
| 30 workers paralelos CMCourier, archivos >50 MB | ~20 MB/s **agregado** |

CPU OK, todos workers busy, server OK (curl prueba 100 MB/s).
HTTP/1.1 vs HTTP/2 (spec 089) no movió la aguja. Algo dentro del
proceso Python serializaba los uploads paralelos.

## Causa raíz

El uploader llamaba a ``enc.read(8192)`` literal en cada chunk:

```python
def _read_chunk(enc: MultipartEncoderMonitor = monitored) -> bytes:
    """8 KB chunk del encoder. ``enc`` default-arg
    bindea la instancia de esta iteration (B023).
    """
    return bytes(enc.read(8192))     # ← 8 KB hardcoded
```

Para un archivo de 50 MB: **6400 reads por archivo**. Cada
``enc.read()`` corre código Python (format multipart wire, copy
buffers, fire progress callback). El **GIL serializa** ese
trabajo entre los 30 threads workers. Con frecuencias tan altas
de read, el GIL se vuelve el cuello agregado.

Con 1 solo worker: cero GIL contention → curl-like throughput.
Con 30 workers: ~192,000 GIL acquisitions por batch → ~20 MB/s.

Inconsistencia adicional: el ``BandwidthLimiter`` (path alterno,
activo solo con throttle) ya usa **1 MiB chunks por default**:

```python
# cmis_uploader.py:174
chunk_size = size if size >= 0 else 1 << 20   # 1 MiB
```

El path normal del MultipartEncoder quedó en 8 KB por copy-paste
de algún snippet antiguo. El default debería ser consistente
con el path del BandwidthLimiter.

## Qué

### Cambios

1. **`CmisConfigModel.upload_chunk_bytes: int`** (schema): nuevo
   campo, default `1 << 20` (1 MiB). Rango `[4096, 64 << 20]`
   (4 KiB – 64 MiB). El operador puede subirlo más para archivos
   gigantes o bajarlo si tiene memoria limitada.

2. **`CmisConfig.upload_chunk_bytes: int`** (dataclass del
   adapter): mismo campo, propagado por wiring.

3. **`CmisUploader._read_chunk`**: reemplaza el literal `8192` por
   ``self._cfg.upload_chunk_bytes`` capturado en default-arg
   (preserva el patrón B023-safe).

4. **`wiring.py`**: copia el flag del schema al dataclass.

### Uso

```yaml
cmis:
  workers: 30
  upload_chunk_bytes: 1048576       # default 1 MiB
  # Para archivos muy grandes podés probar 4 MiB
  # upload_chunk_bytes: 4194304
```

### Tests

* `tests/unit/adapters/upload/test_upload_chunk_bytes.py`:
  - default es 1 MiB
  - schema acepta valores explícitos
  - schema rechaza < 4 KiB y > 64 MiB

## Criterios de aceptación

1. `CmisConfig().upload_chunk_bytes == 1 << 20` (1 MiB default).
2. El uploader pasa el valor del config al `enc.read()` (no más
   literal 8192).
3. Operador en escenario "30 workers, archivos > 50 MB" reporta
   throughput agregado significativamente mejor (predicción:
   3x-5x, posiblemente hasta saturación del link).
4. `pytest -m unit` pasa.

## Riesgos

* **Backward-compat**: configs pre-090 que no declaran
  `upload_chunk_bytes` ahora usan 1 MiB en vez de 8 KiB.
  **Estrictamente mejor** — sin tradeoffs operacionales conocidos.
* **Memoria por worker**: con N workers y chunk de M MiB, el
  consumo máximo de buffers de upload es N × M MiB. Con 30
  workers × 1 MiB = 30 MiB. Despreciable. Con 30 × 4 MiB =
  120 MiB — también razonable. Por eso el cap superior es 64 MiB
  (32 workers × 64 MiB = 2 GiB, marca el límite operacional).
* **Predicción de speedup no garantizada**: si el cuello real no
  fuera el GIL sino otra cosa (lock interno en httpx, AV scan en
  el disco), el fix no movería la aguja. Pero la hipótesis del
  GIL es la más consistente con todos los datos observados.

## Notas

- Pareja conceptual con 089 (HTTP/2 toggle). Ambas atacan el
  mismo síntoma (throughput agregado bajo con muchos workers
  paralelos) desde lados distintos. 089: separa conexiones TCP.
  090: reduce GIL contention. Si una sola no alcanza, la otra
  podría complementar.
- Para ver el impacto, comparar el throughput con `1 << 13` (el
  default pre-090, 8192) explícito vs `1 << 20`. Si el speedup
  es 3x+, el bug era exactamente este.
- Si el speedup es marginal, el cuello debe estar en otra parte
  — la siguiente sospecha sería disco I/O (`source_root` o
  `temp_dir` en HDD/Windows Defender real-time scan).

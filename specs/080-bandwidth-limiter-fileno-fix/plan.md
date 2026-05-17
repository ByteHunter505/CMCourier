# 080 — Plan

Cambio quirúrgico, 1 método al BandwidthLimiter + 3 tests.

## Implementación

Editar `src/cmcourier/adapters/upload/cmis_uploader.py`, agregar
después del método `close`:

```python
def fileno(self) -> int:
    return self._stream.fileno()
```

## Tests

`tests/unit/adapters/upload/test_bandwidth_limiter_fileno.py`:

1. `test_fileno_delegates_to_underlying_stream` — abrir un archivo
   tmp, envolverlo en `BandwidthLimiter`, comparar el fd.
2. `test_multipart_encoder_can_measure_bandwidth_limited_stream` —
   construir el encoder con `BandwidthLimiter(fh, bucket)` como
   file part, asegurar que `encoder.len > 0` y no tira.
3. `test_regression_080_no_typerror_on_throttled_upload` — el caso
   exacto del bug: stream throttled, MultipartEncoder no falla.

## Commits

1. `feat: add 080 spec, plan, tasks`
2. `fix(upload): BandwidthLimiter exposes fileno for total_len (080)`
3. `test: cover BandwidthLimiter fileno + MultipartEncoder integration`
4. `docs(080): CHANGELOG 0.82.0 + version bump`

# 069 — Plan

Una sola fase. Todos los cambios en `metrics.py` + tests.

## Fase 1 — implementación + tests

### `src/cmcourier/observability/metrics.py`

- `_BandwidthSampler.record_upload`: firma nueva
  `(size_bytes: int, *, started_at: float, completed_at: float)`.
  Distribuir los bytes uniformemente sobre los
  buckets-segundo que solapan el intervalo.
- `_BandwidthHandler.emit`: derivar `started_at` de
  `record.created - record.duration_ms / 1000`. Fallback
  defensivo a acreditar en completion cuando
  `duration_ms` es cero o falta.

### Tests

- `tests/unit/observability/test_metrics.py` (o un archivo
  nuevo para el sampler si no existe)
  - **Sanity de distribución**: un upload de 30 MB de
    t=10.0 a t=13.0 (3 s exactos) aterriza 10 MB en cada
    uno de los buckets {10, 11, 12}.
  - **Intervalo fraccionario**: 30 MB de t=10.5 a t=13.5
    distribuye 5 MB a {10}, 10 MB a {11}, 10 MB a {12},
    5 MB a {13}.
  - **Upload del mismo segundo**: 1 MB de t=10.0 a t=10.5
    (sub-segundo) aterriza entero en el bucket {10}.
  - **Cumulative preservado**: 3 uploads sumando 60 MB
    siempre rinde `cumulative_bytes == 60_000_000`.
  - **Pico refleja sostenido**: 30 MB sobre 3 s ⇒
    `peak_mbps` ≤ 10 MB/s, no 30.
- `tests/unit/observability/test_metrics_handler.py` (si
  está presente — sino inline en los tests de metrics)
  - **El handler lee duration_ms**: un log record
    `cmis_upload` con `duration_ms=3000`,
    `record.created=13.0`, `size_bytes=30M` impulsa el
    sampler con `started_at=10.0` → 10 MB/bucket sobre
    {10, 11, 12}.
  - **El handler hace fallback a completion cuando falta
    duration**: un record sin `duration_ms` acredita
    todos los bytes en completion (forma pre-069, solo
    defensiva).

### Verify

`pytest tests/unit tests/integration -q` verde. ruff +
mypy limpios.

### Commit

```
fix(metrics): distribute bandwidth bytes over real transmission window (069 Phase 1)
```

## Fase 2 — release

- CHANGELOG `[0.71.0]`
- pyproject 0.70.0 → 0.71.0
- `pip install -e . --no-deps` + chequeo de versión
- Tick en fila de features de README
- FF a main

Commit:
`docs(069): CHANGELOG 0.71.0 + version bump (069 Phase 2)`.

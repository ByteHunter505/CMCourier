# 077 — Tasks

## Fase 1 — Spec

- [x] 1.1 spec.md
- [x] 1.2 plan.md
- [x] 1.3 tasks.md

## Fase 2 — Sampler

- [ ] 2.1 Agregar `_BandwidthSampler.record_progress(bytes_delta, ts=None)`
        en `src/cmcourier/observability/metrics.py`.

## Fase 3 — Handler

- [ ] 3.1 Modificar `_BandwidthHandler.emit` para procesar
        `cmis_upload_progress` events.
- [ ] 3.2 Modificar branch `cmis_upload` para restar
        `progress_bytes` antes de pasar a `record_upload`.

## Fase 4 — Uploader

- [ ] 4.1 Importar `MultipartEncoderMonitor` en `cmis_uploader.py`.
- [ ] 4.2 En `_post_with_retries`, envolver el `encoder` en un
        `MultipartEncoderMonitor` con callback que emite events
        de progress con threshold 1 MB.
- [ ] 4.3 Pasar `progress_bytes` (contador acumulado) a
        `_emit_network` en todos los paths.
- [ ] 4.4 Agregar `progress_bytes` al `extra={...}` del log record
        en `_emit_network`.

## Fase 5 — Tests

- [ ] 5.1 `tests/unit/observability/test_bandwidth_progress.py`
        con los 6 tests del plan.
- [ ] 5.2 `pytest -m unit` sin regresiones.

## Fase 6 — CHANGELOG + bump

- [ ] 6.1 `CHANGELOG.md` entry `[0.79.0]`.
- [ ] 6.2 `pyproject.toml` `0.78.0` → `0.79.0`.
- [ ] 6.3 `pip install -e . --no-deps`.
- [ ] 6.4 `cmcourier --version` → `0.79.0`.

## Fase 7 — Commits + push

- [ ] 7.1 6 commits phased per plan.md
- [ ] 7.2 `git push origin main`

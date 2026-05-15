# 055 — Tasks

## Fase 1 — Pasar batch_id a través del camino de upload + tests

- [x] 1.1 `domain/ports.py`: `IUploader.upload` agrega
      `*, batch_id: str` (keyword-only, requerido).
- [x] 1.2 `cmis_uploader.py`: `CmisUploader.upload` agrega
      `batch_id`, lo reenvía a `_emit_upload_attempt`,
      `_post_with_retries`, `_emit_upload_failed`.
- [x] 1.3 `cmis_uploader.py`: `_post_with_retries` toma
      `batch_id`, lo reenvía a las tres llamadas de
      `_emit_network`.
- [x] 1.4 `cmis_uploader.py`: `_emit_network` agrega
      `extra["batch_id"]`; `_emit_upload_attempt` /
      `_emit_upload_failed` agregan `extra["batch_id"]`.
- [x] 1.5 `orchestrators/staged.py`: el call site de S5 pasa
      `batch_id=batch_id`.
- [x] 1.6 Tests: los 17 call sites de `uploader.upload(...)` en
      `test_cmis_uploader.py` reciben `batch_id=...` (el conteo
      original de 10 estaba mal — un `head` truncó el grep).
- [x] 1.7 Tests: regresión — `CmisUploader.upload()` real bajo
      un `MetricsRecorder.start_batch()` vivo → el sampler de
      bandwidth + aggregator de slow-op realmente reciben los
      bytes; y el record `cmis_upload` lleva `batch_id`.
- [x] 1.8 Suite completa unit + integration verde (1208
      pasados); mypy + ruff limpios.
- [x] 1.9 Commit
      `fix(s5): thread batch_id through the upload path so network events reach the bandwidth + slow-op handlers (055 Phase 1)`.

## Fase 2 — CHANGELOG 0.58.0 + bump de versión + README + FF

- [x] 2.1 `CHANGELOG.md [0.58.0]` — Fixed.
- [x] 2.2 `pyproject.toml` 0.57.0 → 0.58.0.
- [x] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [x] 2.4 `cmcourier --version` reporta 0.58.0.
- [x] 2.5 Tick en fila de features de `README.md`.
- [x] 2.6 Suite completa + ruff + mypy limpios (verificado en
      Fase 1, 1208 pasados; la Fase 2 no toca código — solo
      docs/CHANGELOG/version).
- [x] 2.7 Commit
      `docs(055): CHANGELOG 0.58.0 + version bump (055 Phase 2)`.
- [ ] 2.8 FF a main.

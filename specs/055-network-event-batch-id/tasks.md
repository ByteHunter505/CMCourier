# 055 — Tasks

## Phase 1 — Thread batch_id through the upload path + tests

- [x] 1.1 `domain/ports.py`: `IUploader.upload` adds `*, batch_id: str`
      (keyword-only, required).
- [x] 1.2 `cmis_uploader.py`: `CmisUploader.upload` adds `batch_id`,
      forwards to `_emit_upload_attempt`, `_post_with_retries`,
      `_emit_upload_failed`.
- [x] 1.3 `cmis_uploader.py`: `_post_with_retries` takes `batch_id`,
      forwards to all three `_emit_network` calls.
- [x] 1.4 `cmis_uploader.py`: `_emit_network` adds
      `extra["batch_id"]`; `_emit_upload_attempt` /
      `_emit_upload_failed` add `extra["batch_id"]`.
- [x] 1.5 `orchestrators/staged.py`: S5 call site passes
      `batch_id=batch_id`.
- [x] 1.6 Tests: all 17 `uploader.upload(...)` call sites in
      `test_cmis_uploader.py` get `batch_id=...` (the original count
      of 10 was wrong — a `head` truncated the grep).
- [x] 1.7 Tests: regression — real `CmisUploader.upload()` under a
      live `MetricsRecorder.start_batch()` → bandwidth sampler +
      slow-op aggregator actually receive the bytes; and the
      `cmis_upload` record carries `batch_id`.
- [x] 1.8 Full unit + integration suite green (1208 passed); mypy +
      ruff clean.
- [x] 1.9 Commit
      `fix(s5): thread batch_id through the upload path so network events reach the bandwidth + slow-op handlers (055 Phase 1)`.

## Phase 2 — CHANGELOG 0.58.0 + version bump + README + FF

- [ ] 2.1 `CHANGELOG.md [0.58.0]` — Fixed.
- [ ] 2.2 `pyproject.toml` 0.57.0 → 0.58.0.
- [ ] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 2.4 `cmcourier --version` reports 0.58.0.
- [ ] 2.5 `README.md` feature row tick.
- [ ] 2.6 Full suite + ruff + mypy clean.
- [ ] 2.7 Commit
      `docs(055): CHANGELOG 0.58.0 + version bump (055 Phase 2)`.
- [ ] 2.8 FF to main.

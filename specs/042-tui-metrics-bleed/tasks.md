# 042 — Tasks

## Phase 1 — bandwidth handler batch_id filter

- [ ] 1.1 `_BandwidthHandler.__init__(sampler, *, batch_id)` — store
      `batch_id` on the handler.
- [ ] 1.2 `_BandwidthHandler.emit` — early-return when
      `record.batch_id != self._batch_id`.
- [ ] 1.3 `MetricsRecorder.start_batch` — pass `batch_id` into
      `_BandwidthHandler(...)`.
- [ ] 1.4 Unit test: emit non-matching batch_id, cumulative_bytes
      unchanged.
- [ ] 1.5 Unit test: emit matching batch_id, cumulative_bytes
      advances.
- [ ] 1.6 mypy + ruff clean.
- [ ] 1.7 Commit
      `fix(observability): per-batch bandwidth handler filter (042 Phase 1)`.

## Phase 2 — live S5 counters propagated to CHUNKS row

- [ ] 2.1 `MetricsRecorder` — add `_s5_done`, `_s5_failed` counters
      + their `_lock`s + `record_upload_done()`,
      `record_upload_failed()`, `upload_done_count()`,
      `upload_failed_count()`.
- [ ] 2.2 `_stage_5_single` — on `outcome == "done"` /
      `"failed"`, call the matching `rec.record_upload_*` method.
- [ ] 2.3 `_stage_5_dual` — same wiring as 2.2.
- [ ] 2.4 `data_provider._chunks_state_snapshot` — when
      `status == "UPLOAD"`, replace `s5_done` / `s5_failed` with the
      live values from the upload-active recorder.
- [ ] 2.5 Unit test: `upload_done_count` thread safety.
- [ ] 2.6 Unit test: `render_chunks` shows live `s5_done` for an
      UPLOAD-status row driven by a synthetic snapshot.
- [ ] 2.7 mypy + ruff clean.
- [ ] 2.8 Commit
      `fix(tui,observability): live s5_done/failed in CHUNKS during UPLOAD (042 Phase 2)`.

## Phase 3 — separate UPLOAD active recorder slot

- [ ] 3.1 `MultiBatchOrchestrator` — add
      `_upload_active_recorder`, `_set_upload_active_recorder`, and
      public `upload_recorder()` callback.
- [ ] 3.2 `_upload_loop` — set the upload-active recorder on
      transition to UPLOAD; clear on transition to DONE/FAILED.
- [ ] 3.3 `TUIDataProvider.__init__` — new
      `upload_recorder_provider` kwarg + `_upload_metrics` property.
- [ ] 3.4 `TUIDataProvider.snapshot` — route the
      `current_chunk_*` derivation through `_upload_metrics`.
- [ ] 3.5 `cli/app.py` — wire `upload_recorder_provider=
      orchestrator.upload_recorder` into the TUIDataProvider build.
- [ ] 3.6 Unit test: initial `upload_recorder()` returns `None`.
- [ ] 3.7 Unit test: with two overlapping chunks, `upload_recorder()`
      tracks the in-UPLOAD chunk's recorder while the other is in
      PREP.
- [ ] 3.8 mypy + ruff clean.
- [ ] 3.9 Commit
      `fix(orchestrators,tui): separate upload-active recorder slot (042 Phase 3)`.

## Phase 4 — docs + CHANGELOG 0.45.0 + version bump + FF

- [ ] 4.1 `CHANGELOG.md [0.45.0]` entry — Fixed (3 bugs by id),
      Changed (bandwidth handler signature).
- [ ] 4.2 `pyproject.toml` 0.44.0 → 0.45.0.
- [ ] 4.3 `.venv/bin/pip install -e . --no-deps` — refresh
      package metadata.
- [ ] 4.4 `cmcourier --version` shows `0.45.0`.
- [ ] 4.5 `README.md` feature row tick.
- [ ] 4.6 Re-run `/tmp/verify_tui_041.py` against staging; capture
      mid-flight + final frame, confirm no bleed and live counters.
- [ ] 4.7 Full suite + mypy + ruff clean.
- [ ] 4.8 Commit
      `docs(042): CHANGELOG 0.45.0 + version bump (042 Phase 4)`.
- [ ] 4.9 FF to main.

# 055 — Plan

Two phases (~1.25 h total).

## Phase 1 — Thread batch_id through the upload path + tests (~55 min)

### Files

- `src/cmcourier/domain/ports.py`
  - `IUploader.upload` — add `*, batch_id: str` (keyword-only,
    required) to the abstract signature + docstring line.

- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - `CmisUploader.upload` — add `*, batch_id: str`; pass it to
    `_emit_upload_attempt`, `_post_with_retries`, `_emit_upload_failed`.
  - `_post_with_retries(self, url, data, headers, txn_num, kind="cmis_post", *, batch_id: str)`
    — pass `batch_id` to all three `_emit_network` calls.
  - `_emit_network(kind, t0, status, size_bytes, url, batch_id)` —
    `extra["batch_id"] = batch_id`. (Still a `@staticmethod`.)
  - `_emit_upload_attempt` / `_emit_upload_failed` — add
    `batch_id: str` keyword, `extra["batch_id"] = batch_id`.

- `src/cmcourier/orchestrators/staged.py`
  - The `self._uploader.upload(...)` call (~line 916, inside the S5
    `StageTimer` block) — add `batch_id=batch_id`. `batch_id` is
    already in scope there.

### Tests

- `tests/integration/adapters/test_cmis_uploader.py`
  - All 10 `uploader.upload(...)` call sites — add
    `batch_id="..."` (a literal per test is fine).
  - **New regression test** `test_upload_event_reaches_bandwidth_and_slowop_handlers`:
    build a `MetricsRecorder`, `start_batch(batch_id="B1")`, run a
    mocked `CmisUploader.upload(..., batch_id="B1")`, assert
    `recorder.bandwidth.peak_mbps() > 0` /
    `cumulative_bytes() > 0` and `recorder.aggregator_snapshot()`
    non-empty. The slow-op assertion needs the recorder built with
    `slow_op_threshold_ms=0.0` and the `cmcourier.metrics.network`
    logger at INFO. This is the test that exercises the *real*
    `_emit_network`.
  - **New** `test_emit_network_record_carries_batch_id`: a
    lighter-weight assertion via `caplog` (or a capturing handler)
    that the `cmis_upload` record has `record.batch_id == "B1"`.

- Scan for other call sites: `grep -rn "\.upload(" tests/ src/` — only
  `staged.py` (covered) and `test_cmis_uploader.py` (covered). Staged
  pipeline tests mock the uploader with `MagicMock`, which does not
  validate the signature — but run the full suite to confirm nothing
  passes a positional that now collides with the keyword-only marker.

### Verify

Full unit + integration suite + ruff + mypy. The required keyword
means `mypy` flags any missed call site.

### Commit

```
fix(s5): thread batch_id through the upload path so network events reach the bandwidth + slow-op handlers (055 Phase 1)
```

## Phase 2 — CHANGELOG 0.58.0 + version bump + README + FF (~20 min)

### Files

- `CHANGELOG.md` `[0.58.0]` — Fixed (every `cmis_upload` network event
  was dropped by the per-batch bandwidth + slow-op handlers because
  `_emit_network` never set `batch_id`; the UPLOAD tab showed 0
  bandwidth / blank sparkline / no slow ops on every run since 042).
- `pyproject.toml` 0.57.0 → 0.58.0.
- `README.md` feature row tick.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.58.0
```

### Commit

```
docs(055): CHANGELOG 0.58.0 + version bump (055 Phase 2)
```

### FF to main.

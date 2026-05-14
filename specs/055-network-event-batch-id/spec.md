# 055 — Network events carry the batch_id: unbreak the bandwidth + slow-op handlers

## Why

On an N=2 staging run the operator reported the UPLOAD tab dead:
bandwidth `0.00 MB/s`, peak `0.00`, blank sparkline, SLOW OPS
"(none yet)". Spec 054 fixed *which recorder* the snapshot reads — a
real bug — but the operator re-ran and **it was still empty**. 054
treated a symptom; this is the root cause.

### The root cause — proven

`CmisUploader._emit_network` (`cmis_uploader.py`) builds the log
record's `extra` with `kind`, `duration_ms`, `url_prefix`, `worker`,
`status`, `size_bytes` — **but never `batch_id`**. The `CmisUploader`
is a shared, concurrently-used object and its `upload()` never even
receives a `batch_id`.

Both metrics handlers filter on that field:

- `_BandwidthHandler.emit` →
  `if getattr(record, "batch_id", None) != self._batch_id: return`
- `_SlowOpHandler.emit` → the same `record_batch_id != self._batch_id`
  short-circuit.

`getattr(record, "batch_id", None)` is `None`; `self._batch_id` is a
real string; `None != "B1"` → **every `cmis_upload` event is dropped**,
in *every* recorder. Spec 042 added the `batch_id` filter to
`_BandwidthHandler` (and 028 to `_SlowOpHandler`) assuming the events
carried it — they never did. Since then, 100% of upload bandwidth and
upload slow-ops have been silently discarded.

Proven with a repro that replays `_emit_network`'s exact `extra`:

```
(A) extra WITHOUT batch_id -> peak_mbps=0.0  cumulative=0        slow_ops=0
(B) extra WITH    batch_id -> peak_mbps=8.0  cumulative=8000000  slow_ops=2
```

Same event, same bytes — the only difference is the `batch_id` field.

This is also why spec 053 found the `network-*.jsonl` files have no
`batch_id` and had to associate them by time window: the same
`_emit_network` omission.

## What

Thread the chunk's `batch_id` down the upload path so every network
event emitted during `upload()` carries it.

### 1. `IUploader.upload` — new required keyword `batch_id`

`upload(self, file, folder_path, object_type_id, document_name,
mime_type, properties, *, batch_id: str) -> str`. Keyword-only and
**required** — no default. A default `""` would silently re-introduce
the bug the first time a caller forgot it; `batch_id` is a legitimate
domain input, not a compatibility shim.

### 2. `CmisUploader` — propagate it to every network emitter

- `CmisUploader.upload` accepts `batch_id` and passes it to
  `_post_with_retries`, `_emit_upload_attempt`, `_emit_upload_failed`.
- `_post_with_retries(..., *, batch_id: str)` passes it to
  `_emit_network`.
- `_emit_network(kind, t0, status, size_bytes, url, batch_id)` adds
  `extra["batch_id"] = batch_id`.
- `_emit_upload_attempt` / `_emit_upload_failed` add
  `extra["batch_id"] = batch_id` too — same `batch_id` already in
  scope, and it makes the `s5_upload_attempt` / `s5_upload_failed`
  diagnostic events in `network-*.jsonl` batch-attributable as well.

### 3. The call site — `staged.py`

`StagedPipeline`'s S5 stage already has `batch_id` in scope (it builds
the `StageTimer` with it). The `self._uploader.upload(...)` call passes
`batch_id=batch_id`.

## Out of scope

- Reverting spec 053's time-window association in `analyze.py`. Once
  `network-*.jsonl` records carry `batch_id` again, the analyzer
  *could* go back to an exact `batch_id` filter — but that's a
  separate, additive change. 053's time-window path keeps working
  unchanged; a follow-up spec can simplify it.
- `verify_folder_exists` / `test_connection` / `get_type_definition` —
  these are pre-flight, single-shot, outside any batch lifetime; they
  do not emit `cmis_upload` events and are not slow-op candidates.
- Spec 054's `_metrics` vs `_upload_metrics` split — already shipped
  and correct; it is what makes the now-delivered events land on the
  right recorder for an N=2 run. 055 + 054 together fix the tab.

## Acceptance criteria

- A `CmisUploader.upload()` call (HTTP mocked) made while a
  `MetricsRecorder` has an open batch results in a non-zero
  `recorder.bandwidth.peak_mbps()` / `cumulative_bytes()` and a
  populated `aggregator_snapshot()` — a regression test asserts it.
  This is the test that would have caught the bug: it exercises the
  real `_emit_network`, not a hand-built `extra`.
- The `cmis_upload` log record emitted by `_emit_network` has a
  `batch_id` attribute equal to the value passed into `upload()`.
- `IUploader.upload` and every implementation + call site take the new
  keyword; `mypy` is clean (the required keyword forces every call
  site to be updated — no silent omissions).
- Full unit + integration suite green; mypy + ruff clean.
- `CHANGELOG.md [0.58.0]`; `pyproject.toml` 0.57.0 → 0.58.0.

## Notes on test strategy

The gap that let this ship: `test_cmis_uploader.py` mocks HTTP but
never attaches a live `MetricsRecorder`, so it never observed that the
emitted record lacked `batch_id`; and `test_data_provider.py`'s
slow-op test hand-built an `extra` dict *with* `batch_id`, so it
tested a shape the real uploader never produces. 055's regression test
closes both: a real `CmisUploader.upload()` under a real
`MetricsRecorder.start_batch()`, asserting the sampler and aggregator
actually received the bytes.

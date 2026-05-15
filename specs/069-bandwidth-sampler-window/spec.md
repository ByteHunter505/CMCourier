# 069 — Bandwidth sampler: distribute bytes over the real transmission window

## Why

Operator-reported during the same 068 staging run: bandwidth peak
`<20 MB/s` even after 068 scales workers aggressively. Part of
that is genuine throughput (the next-bottleneck is per-upload
speed against Alfresco), but the **measurement itself is buggy
for heavy files**.

Pre-069 `_BandwidthSampler.record_upload(size_bytes, completed_at)`:

```python
def record_upload(self, size_bytes: int, completed_at: float) -> None:
    ts = int(completed_at)
    self._buckets[ts] = self._buckets.get(ts, 0) + int(size_bytes)
```

It credits the **entire file size to the second of completion**.
For a 30 MB upload that took 3 seconds (T → T+3), all 30 MB land
in bucket `T+3`. Buckets `T+1`, `T+2` show **zero** bytes for that
upload — even though it was actively transmitting during them.

Consequences:

* **Spiky reading**: `current_mbps()` (which reads the previous
  full bucket) flips between "spike" and "valley" depending on
  whether a completion happened in that bucket. Operator sees
  e.g. `current 11 MB/s` one second, `current 0 MB/s` the next.
* **Wrong sparkline shape**: the 60-bucket rolling chart shows
  spikes at completion moments instead of the continuous
  transmission shape.
* **Misleading peak**: a single 30 MB completion in one second
  reports `peak 30 MB/s` even when actual sustained throughput
  is ~10 MB/s.
* **Diagnosis blocked**: the operator can't distinguish "the
  pipe is genuinely slow" from "the measurement is wrong" without
  re-deriving `cumulative_bytes / elapsed_s` manually.

## What

`record_upload` takes a transmission window — `started_at` and
`completed_at` — and **distributes bytes uniformly across the
seconds the transmission actually spanned**. For a 30 MB upload
from T=10.5 to T=13.5 (3 seconds), 10 MB lands in each of buckets
{10, 11, 12, 13} (with fractional seconds handled by partial
allocations).

### New signature

```python
def record_upload(
    self,
    size_bytes: int,
    *,
    started_at: float,
    completed_at: float,
) -> None:
```

Old positional `(size_bytes, completed_at)` signature is dropped.
Callers must pass both timestamps. There's exactly one caller
inside CMCourier: `_BandwidthHandler.emit` (the log handler that
feeds the sampler from `cmis_upload` network events). The handler
already has both — `record.created` is `completed_at`, and the
`cmis_upload` event payload carries `duration_ms` (we derive
`started_at = completed_at - duration_ms/1000`).

### Distribution algorithm

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
            # Overlap of [ts, ts+1) with [started_at, completed_at]
            overlap_start = max(started_at, float(ts))
            overlap_end = min(completed_at, float(ts) + 1.0)
            overlap = overlap_end - overlap_start
            if overlap <= 0:
                continue
            bytes_in_bucket = int(bytes_per_s * overlap)
            self._buckets[ts] = self._buckets.get(ts, 0) + bytes_in_bucket
        # Evict stale buckets
        stale = [k for k in self._buckets if k < cutoff]
        for k in stale:
            del self._buckets[k]
```

The transmission rate is assumed constant within an upload (uniform
distribution). For long uploads on stable networks this is faithful;
for uploads with bursty internal transmission it's slightly smoothed
— acceptable for an aggregate view.

### `_BandwidthHandler` change

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

The `cmis_upload` event always carries `duration_ms` (set by
`_emit_network` in the CmisUploader). When unset or zero, the
handler falls back to crediting all bytes to the completion second
(pre-069 behaviour, defensive only — should not trigger in
practice).

## Out of scope

- Per-stream bandwidth measurement (per-host, per-connection).
- Bandwidth measurement during the transmission itself
  (vs after completion). Would require streaming progress
  callbacks from httpx, much larger surface.

## Acceptance criteria

- `_BandwidthSampler.record_upload(size, *, started_at, completed_at)`
  distributes bytes uniformly over the second-buckets that overlap
  `[started_at, completed_at]`.
- A 30 MB upload from `T+0.5` to `T+3.5` (3.0 s span) lands ~5 MB
  in bucket `T`, 10 MB in `T+1`, 10 MB in `T+2`, 5 MB in `T+3`
  (within floor-rounding tolerance).
- `cumulative_bytes` is still the sum of all uploads (no double-counting).
- `peak_mbps` is the highest single-bucket rate (now reflects
  real sustained throughput, not completion spike).
- `series(seconds)` returns the windowed chart with the new
  smooth shape.
- `_BandwidthHandler.emit` reads `duration_ms` from the log
  record and derives `started_at`. Defaults to crediting at
  completion when `duration_ms` is missing/zero.
- All existing tests updated to use the new signature.
- mypy + ruff clean.
- CHANGELOG `[0.71.0]`; pyproject 0.70.0 → 0.71.0.

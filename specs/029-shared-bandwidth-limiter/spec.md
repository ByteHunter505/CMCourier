# 029 — Shared `BandwidthLimiter` (bug fix)

> Status: **Proposed** — 2026-05-11
> Author: bitBreaker
> Predecessor: 025 (concurrent S5 worker pool surfaced this bug)

---

## 1. Summary

The current `BandwidthLimiter` is **per-stream**:
each `CmisUploader.upload(...)` call wraps the file stream in
a fresh limiter with its own token bucket. With
`cmis.workers=N` concurrent uploads, the effective network
ceiling is `N × cmis.max_bandwidth_mbps`, **not** the
configured value.

This change extracts the token bucket from the limiter into a
**process-shared, thread-safe** `TokenBucket` owned by the
`CmisUploader` instance. All uploads from the same uploader
acquire from the same bucket, so the configured cap is now
genuinely enforced regardless of worker count.

---

## 2. Motivation

- **Real production risk.** A configured `max_bandwidth_mbps=100`
  with `cmis.workers=4` saturates the link at ~400 Mbps. If
  the bank agreed a 100 Mbps budget for the migration window,
  we exceed it by 4×.
- **`cmcourier analyze` correctness.** The classifier's
  `network-bound` heuristic compares observed NIC throughput
  to `cmis.max_bandwidth_mbps`. Today that comparison is
  meaningless because the configured cap is illusory.
- **Blocks POST-MVP §1.** The heavy/light lanes feature
  explicitly requires a shared bandwidth bucket. Fixing this
  now unblocks that work.

---

## 3. Scope

### In scope

- New `TokenBucket` class in
  `cmcourier/adapters/upload/cmis_uploader.py`:
  - `consume(n_bytes: int) -> None` — blocks until at least
    `n_bytes` tokens are available, then deducts them.
  - `threading.Lock` protected; safe under concurrent calls.
  - `mbps=0` means "disabled" — `consume` is a no-op.
- Refactor `BandwidthLimiter.__init__(stream, mbps)` →
  `BandwidthLimiter.__init__(stream, bucket: TokenBucket)`.
  `read(size)` defers throttling to `bucket.consume(size)`.
- `CmisUploader.__init__` constructs a single `TokenBucket`
  from `cfg.max_bandwidth_mbps` and reuses it for every
  upload.
- ≥3 new tests: TokenBucket isolation unit tests + 1 property
  test proving N=4 concurrent workers don't exceed the cap.
- Existing `TestBandwidthLimiter` tests adapted to the new
  constructor.

### Out of scope

- Per-batch quotas (POST-MVP §8).
- Adaptive sharing between heavy/light lanes (POST-MVP §1).
- Bandwidth-related TUI changes (the existing bandwidth
  sampler from 025 keeps working — it observes, doesn't
  enforce).
- Schema changes — `cmis.max_bandwidth_mbps` keeps the same
  meaning, just **actually** enforced now.

---

## 4. Requirements

- **REQ-001**: New `TokenBucket(mbps: float)`:
  - `mbps == 0` → `consume()` returns immediately.
  - `mbps > 0` → `consume(n)` blocks until `n` tokens are
    available, then deducts them.
  - Thread-safe under concurrent calls from multiple threads.
- **REQ-002**: `BandwidthLimiter` no longer owns rate /
  tokens state. Construct it with `(stream, bucket)`. `read()`
  calls `bucket.consume(chunk_size)` before reading from the
  stream.
- **REQ-003**: `CmisUploader.__init__` builds one
  `TokenBucket` from `cfg.max_bandwidth_mbps`. The instance
  is reused for every `upload()` call.
- **REQ-004**: ≥3 new tests:
  1. `TokenBucket(mbps=0)` is a no-op (immediate return).
  2. `TokenBucket(mbps=X)` with a single thread throttles to
     ~X MB/s (existing semantic, just relocated).
  3. **Property test**: N=4 threads each consuming 1 MB
     against a shared `TokenBucket(mbps=Y)` — total wall-clock
     time is roughly `4 / Y` seconds (within tolerance),
     proving the cap is global.
- **REQ-005**: Existing `TestBandwidthLimiter` tests
  refactored to construct the limiter via a bucket. Behavior
  for single-stream cases is unchanged.

---

## 5. Acceptance scenarios

1. **N=1 unchanged**: With one worker uploading at the cap,
   throughput matches the configured value (regression check).
2. **N=4 enforces global cap**: Four concurrent uploads at
   the cap — aggregate throughput equals the configured value,
   not 4× it (property test).
3. **mbps=0 disabled path**: Setting `max_bandwidth_mbps=0`
   skips throttling entirely (no lock acquisition, no token
   math).
4. **Single uploader, many uploads**: `CmisUploader` reused
   across many calls keeps the same `TokenBucket` — running
   totals carry across upload invocations.

---

## 6. Verification

- `pytest` ≥727 passing (724 + the 3 new tests).
- `mypy src/cmcourier/` clean.
- `ruff check` / `ruff format --check` clean.

# 067 — Streaming-mode TUI bug fixes

## Why

Operator-reported during the first end-to-end streaming run (configs
063→066 shipped). Four distinct bugs, all converging on the same
underlying issue: `StreamingOrchestrator` reuses the TUI binding
surface designed for the batched orchestrator without actually
populating its live fields.

### Bug 1 — Upload progress bar stuck at CURRENT/CURRENT

`upload_tab.render_upload` computes:

```python
target = max(count + snap.queue_depth, 1)
bar = _bar(count, target, width=28)
```

`snap.queue_depth` comes from `pool_stats.snapshot().queue_depth`.
The batched orchestrator's `_stage_5_single` / `_stage_5_dual` call
`pool_stats.set_queue_depth(...)` per cycle. The streaming
orchestrator never does — so queue_depth stays at 0, target equals
count, bar shows `count/count` permanently.

### Bug 2 — Chunk timer never starts, avg speed always 0

`_current_chunk_progress` reads `status` from the synthetic
ChunkState. Streaming sets `status="PREP"` for the whole run, so:

```python
else:
    # PREP (or unknown) — S5 hasn't started; no upload elapsed yet.
    elapsed_s = 0.0
```

With `elapsed_s = 0`, `avg_mbps = 0`, and `_chunk_timer_line`
returns `None` because elapsed AND bytes are both zero (the
function bails out early to avoid rendering a noisy zero line).

### Bug 3 — CHUNKS tab frozen at zero during the run

The synthetic chunk_state has `s5_done`, `s5_failed`, `doc_count`,
`prep_done` all set only in the FINAL update at end of run. During
the run, they stay at their initial zero values, so the CHUNKS-tab
renderer shows everything frozen at 0.

### Bug 4 — LANES queue counter monotonic-up, exceeds bucket size

`_dispatcher_loop` maintains private counters:

```python
heavy_depth = 0
light_depth = 0
while True:
    ...
    if size_bytes >= threshold:
        heavy_queue.put(stage_item)
        heavy_depth += 1
        self._lane_controller.set_queue_depth("heavy", heavy_depth)
```

The counter only increments — never decrements when a consumer
pops from `heavy_queue`. So the reported "queue" is a cumulative
*enqueued count*, not a live occupancy. After 5000 docs it shows
"queue 2500" even though the actual queue size never exceeds
`bucket_size=200`.

The operator's expectation (correct): the LANES queue field should
match `heavy_queue.qsize()` and `light_queue.qsize()` — the live
in-flight count. This is also what the LaneController's rebalance
heuristic needs to work correctly (the drain-driven migration
fires only when a lane's queue reaches zero — under the buggy
counter it never does).

## What

All four fixes live entirely in `streaming.py`. No changes to the
TUI renderer or the batched orchestrator.

### Fix 1 — Plumb `pool_stats.set_queue_depth` from streaming

The orchestrator updates `pool_stats.set_queue_depth(...)` with
the live total pending count:
`main_bucket.qsize() + heavy_queue.qsize() + light_queue.qsize()`
(single-lane mode: just `main_bucket.qsize()`).

Updates happen after each producer `bucket.put` and each consumer
`bucket.get` / `lane_queue.get`. The pool_stats snapshot is
read-mostly so the lock contention is minimal.

Result: `target = count + pending`, bar shows real progress
through the in-flight slice.

### Fix 2 + 3 — Live synthetic chunk_state during the run

When threads spawn, the orchestrator transitions the synthetic
`ChunkState` to `status="UPLOAD"` with `upload_started_monotonic=
start`. Both PREP and UPLOAD run simultaneously in streaming;
"UPLOAD" is the dominant phase for the operator's mental model
(the only one with a meaningful timer/throughput readout).

After every S5 outcome (in `_upload_loop` and `_lane_upload_loop`),
the orchestrator calls a new internal helper:

```python
def _publish_chunk_state(self, *, batch_id: str, tally: _StreamingTally,
                          tally_lock: threading.Lock) -> None:
    with tally_lock:
        snap = (tally.s5_done, tally.s5_failed, tally.s5_skipped,
                tally.s1_filtered, tally.cross_batch_skipped)
    s5d, s5f, s5sk, fil, csk = snap
    docs = s5d + s5f + s5sk
    with self._state_lock:
        prev = self._chunk_state
        self._chunk_state = ChunkState(
            chunk_idx=0,
            batch_id=batch_id,
            status="UPLOAD",
            s5_done=s5d,
            s5_failed=s5f,
            doc_count=docs + fil + csk,
            prep_done=docs,
            prep_skipped=csk,
            prep_filtered=fil,
            upload_skipped=s5sk,
            upload_started_monotonic=(
                prev.upload_started_monotonic if prev else None
            ),
            prep_started_monotonic=(
                prev.prep_started_monotonic if prev else None
            ),
        )
```

Result:
* CHUNKS tab shows live s5_done/s5_failed/doc_count.
* `_current_chunk_progress` sees `status="UPLOAD"` and computes
  `elapsed_s = now - upload_started_monotonic`, so the timer ticks.
* `avg_mbps = (bytes_uploaded / 1MB) / elapsed_s` — non-zero once
  the recorder accumulates network bytes.

### Fix 4 — Real qsize-based lane depth reporting

Replace the dispatcher's monotonic counters with `lane_queue.qsize()`:

```python
# dispatcher, after put:
self._lane_controller.set_queue_depth("heavy", heavy_queue.qsize())
```

And the consumer reports too:

```python
# _lane_upload_loop, after get:
self._lane_controller.set_queue_depth(lane, lane_queue.qsize())
```

Result:
* LANES "queue" field shows the live in-flight count per lane.
* Never exceeds `bucket_size` (the maxsize of each lane queue).
* The LaneController's drain-driven rebalance heuristic actually
  fires when a lane hits zero — pre-067 it never did.

## Out of scope

- True total-progress (`count / total_triggers`) in streaming mode
  — requires knowing total ahead of time. The fix above gives
  `count / (count + currently-pending)`, which is a useful
  approximation but not "total". Spec 068 (TBD) can plumb
  `--total` into the chunk_state if needed.
- Per-stage in-flight visibility (S1/S2/S3/S4 separate counters).
  Out of scope here — a future visibility spec.

## Acceptance criteria

- UPLOAD-tab progress bar shows `count / (count + pending)` during a
  streaming run (not `count / count`), where `pending` is the live
  in-flight count visible to the orchestrator.
- The per-chunk timer in the UPLOAD tab ticks from the moment
  uploads start, not after run completion.
- `current_chunk_avg_mbps` is non-zero once bandwidth is recorded.
- CHUNKS tab shows live `s5_done`, `s5_failed`, `doc_count`,
  `prep_done` during the run.
- LANES `queue` in both BUCKET and UPLOAD tabs shows the live
  qsize of each lane queue. Never exceeds `bucket_size`. Decrements
  as consumers drain.
- LaneController's `_heavy_first_empty_at` / `_light_first_empty_at`
  actually get stamped during a run with heavy and light traffic
  (proves the drain heuristic is reachable).
- All existing tests pass. New tests:
  * `_pool_stats.set_queue_depth` is called during streaming.
  * `chunk_state.status == "UPLOAD"` mid-run (via a polling test).
  * `lane_controller.set_queue_depth("heavy", N)` receives the
    real qsize value, not a cumulative count.
- mypy + ruff clean.
- CHANGELOG `[0.69.0]`; pyproject 0.68.0 → 0.69.0.

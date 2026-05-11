# Plan — 025-tui-workers-autotune

**Status**: Draft
**Spec**: `specs/025-tui-workers-autotune/spec.md`

---

## 1. Architecture in one paragraph

Three layers stacked: (1) schema extension + thread-safety
review of the existing collaborators, then (2) a
`ThreadPoolExecutor`-based `_stage_s5` plus an optional
`AutoTuneController` thread that tweaks pool size + timeout
via AIMD, then (3) a `textual` two-tab `App` that polls a
`TUIDataProvider` reading from `MetricsRecorder` +
`WorkerPoolStats`. The TUI runs in a separate thread; the
pipeline runs in the main thread. They communicate via
shared snapshots (read-only views), no callbacks, no event
bus.

---

## 2. Module layout

```
src/cmcourier/config/schema.py                  # +AutoTuneConfig +CmisConfigModel.workers/auto_tune
src/cmcourier/orchestrators/staged.py           # _stage_s5 → ThreadPoolExecutor + WorkerPoolStats
src/cmcourier/services/auto_tune.py             # NEW — AIMD controller
src/cmcourier/services/worker_pool_stats.py     # NEW — thread-safe pool snapshot
src/cmcourier/observability/metrics.py          # +mutex on _StageBucket + _SlowOpAggregator + _BandwidthSampler
src/cmcourier/observability/formatter.py        # +"worker" in ALLOWED_EXTRA_FIELDS
src/cmcourier/adapters/upload/cmis_uploader.py  # +mutex on _folder_cache + _warm; +worker name in network events
src/cmcourier/tui/__init__.py                   # NEW package
src/cmcourier/tui/app.py                        # NEW textual App
src/cmcourier/tui/prep_tab.py                   # NEW
src/cmcourier/tui/upload_tab.py                 # NEW
src/cmcourier/tui/data_provider.py              # NEW
src/cmcourier/tui/chart.py                      # NEW — sparkline rendering
src/cmcourier/cli/app.py                        # +--tui/--no-tui, thread the TUI runner
src/cmcourier/cli/_tui_runner.py                # NEW — start/stop TUI in a worker thread
tests/...                                       # +6+6+5+4+1+3 tests across phases
```

---

## 3. Key types

### 3.1 `WorkerPoolStats`

Thread-safe snapshot of S5 pool state. Owned by the orchestrator,
read by both the auto-tune controller and the TUI.

```python
@dataclass
class WorkerPoolStatsSnapshot:
    pool_size: int
    busy: int
    idle: int
    queue_depth: int
    completed: int
    failed: int


class WorkerPoolStats:
    """Mutable, thread-safe. Snapshot via .snapshot()."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pool_size = 0
        ...

    def set_pool_size(self, n: int) -> None: ...
    def mark_busy(self, worker_name: str) -> None: ...
    def mark_idle(self, worker_name: str) -> None: ...
    def mark_completed(self) -> None: ...
    def mark_failed(self) -> None: ...
    def set_queue_depth(self, n: int) -> None: ...
    def snapshot(self) -> WorkerPoolStatsSnapshot: ...
```

### 3.2 `AutoTuneController`

```python
class AutoTuneController:
    def __init__(
        self,
        config: AutoTuneConfig,
        pool_stats: WorkerPoolStats,
        metrics_recorder: MetricsRecorder,
        on_pool_resize: Callable[[int], None],
        on_timeout_change: Callable[[float], None],
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self, timeout: float = 1.0) -> None: ...

    # internal — exposed for testing
    def _next_decision(self, observed_p95_ms: float, elapsed_s: float) -> _Decision: ...
```

`_Decision` carries the new pool size + new timeout + action label
("+1", "halve", "noop") for clean unit-testing of the algorithm.

### 3.3 `TUIDataProvider`

Read-only adapter the TUI polls every 250 ms.

```python
class TUIDataProvider:
    def __init__(
        self,
        recorder: MetricsRecorder,
        pool_stats: WorkerPoolStats,
        cmis_config: CmisConfigModel,
        auto_tune: AutoTuneState,
    ) -> None: ...

    def snapshot(self) -> TUISnapshot: ...
```

`TUISnapshot` is a frozen dataclass with every field the two tabs
need to render — no live references back to mutable state.

### 3.4 `BandwidthSampler`

Lives inside `MetricsRecorder`. 60-bucket rolling 1-second window.

```python
class _BandwidthSampler:
    def record_upload(self, size_bytes: int, completed_at: float) -> None: ...
    def current_mbps(self) -> float: ...
    def series(self, seconds: int = 60) -> list[tuple[float, float]]: ...
```

---

## 4. Algorithm sketches

### 4.1 `_stage_s5` refactor

```python
def _stage_s5(self, items, batch_id):
    self._pool_stats.set_pool_size(self._workers)
    s5_done_lock = threading.Lock()
    s5_done = 0
    failed = 0
    with ThreadPoolExecutor(
        max_workers=self._workers,
        thread_name_prefix="cmcourier-s5",
    ) as pool:
        futures = {pool.submit(self._upload_one, item, batch_id): item for item in items}
        self._pool_stats.set_queue_depth(len(futures))
        for fut in as_completed(futures):
            outcome = fut.result()
            with s5_done_lock:
                if outcome == "done": s5_done += 1
                elif outcome == "failed": failed += 1
            self._pool_stats.set_queue_depth(self._pool_stats.snapshot().queue_depth - 1)
    return s5_done, failed


def _upload_one(self, item, batch_id) -> str:
    self._pool_stats.mark_busy(threading.current_thread().name)
    try:
        # existing _stage_s5 body for one item, returns "done"/"failed"/"skipped"
        ...
    finally:
        self._pool_stats.mark_idle(threading.current_thread().name)
```

The existing `StageTimer` wrapper stays — it now records under
worker thread context. The metrics recorder's `record_stage` must
be thread-safe (REQ-009).

### 4.2 AIMD decision

```python
def _next_decision(self, observed_p95_ms, elapsed_s):
    if elapsed_s < self._cfg.warmup_seconds:
        return _Decision(action="warmup", workers=current, timeout=current_timeout)
    if observed_p95_ms < 0.8 * self._cfg.target_p95_ms:
        new_workers = min(current + 1, self._cfg.max_threads)
        new_timeout = max(current_timeout / 2, self._cfg.min_timeout_s)
        return _Decision(action="+1", ...)
    if observed_p95_ms > 1.2 * self._cfg.target_p95_ms:
        new_workers = max(current // 2, self._cfg.min_threads)
        new_timeout = min(current_timeout * 2, self._cfg.max_timeout_s)
        return _Decision(action="halve", ...)
    return _Decision(action="noop", workers=current, timeout=current_timeout)
```

Note: shrinking a `ThreadPoolExecutor` is not directly supported.
We implement pool resize via a custom wrapper that holds a "target
size" the worker scheduler honors when picking up the next task —
i.e., workers above the target exit when they finish their current
task. Detailed pattern in plan §5.

### 4.3 Pool resize pattern

A `ThreadPoolExecutor` doesn't expose pool resize. Two options:
1. **Replace the pool** at every AIMD decision. Drains the
   in-flight futures via `pool.shutdown(wait=True)`, creates a
   new pool with the new size. Costly: every adjustment stops
   the world for the in-flight uploads (could be 30+ seconds).
2. **Custom thread pool** with a target-count semaphore. Workers
   loop pulling from a queue; when the target shrinks, the
   workers above the target exit. No drain stalls.

Choice: **option 2**. Implement `ResizableWorkerPool` in
`services/worker_pool_stats.py`. It's ~80 LOC of careful
threading but avoids the drain penalty.

### 4.4 Bandwidth sampler

```python
class _BandwidthSampler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # bucket_ts → bytes
        self._buckets: dict[int, int] = {}

    def record_upload(self, size_bytes, completed_at):
        with self._lock:
            ts = int(completed_at)
            self._buckets[ts] = self._buckets.get(ts, 0) + size_bytes
            # Prune to last 60s.
            cutoff = ts - 60
            for k in list(self._buckets.keys()):
                if k < cutoff:
                    del self._buckets[k]

    def current_mbps(self) -> float:
        now = int(time.time())
        with self._lock:
            return self._buckets.get(now, 0) / 1_000_000.0

    def series(self, seconds=60) -> list[tuple[float, float]]:
        now = int(time.time())
        with self._lock:
            return [(now - (60 - i), self._buckets.get(now - (60 - i), 0) / 1_000_000.0)
                    for i in range(60)]
```

### 4.5 TUI threading model

```
main thread
    │
    ├─ start TUI thread (textual App.run())
    │      ↓ poll every 250ms
    │      [TUIDataProvider.snapshot()] (thread-safe reads)
    │
    ├─ run pipeline.run()
    │   └─ _stage_s5 → ThreadPoolExecutor (4–N workers)
    │       └─ each worker: uploader.upload() → updates pool_stats + metrics
    │
    ├─ pipeline returns
    └─ signal TUI to show "Run complete" + wait for Q
```

The TUI is a non-daemon thread. Main thread joins after pipeline
finishes. Operator presses `Q` to release.

For non-TTY (pytest, CI): detect `sys.stdin.isatty()` early, fall
back to the existing headless path, no TUI thread.

### 4.6 Worker name in network events

`CmisUploader._post_with_retries` already has `kind="cmis_upload"`.
Add `extra={"worker": threading.current_thread().name}` to every
network event emission. Same for AS400 source (REQ-019 of 020 will
gain a `worker` field too — defensive even if S0 is single-threaded
today).

Add `"worker"` to `ALLOWED_EXTRA_FIELDS` in
`observability/formatter.py`.

---

## 5. Test plan summary

(See spec §4 REQ-038 through REQ-043 for counts.)

* `tests/unit/config/test_schema.py` — +6 tests
  (AutoTuneConfig fields, validator, regression for missing
  block).
* `tests/integration/pipeline/test_s5_worker_pool.py` — NEW,
  ~6 tests (N=1 vs N=4 outcomes match, exception isolation,
  graceful shutdown, p95 under concurrency, worker label
  attribution).
* `tests/unit/services/test_auto_tune.py` — NEW, ~5 tests
  (AI, MD, noop, warmup, timeout adjust).
* `tests/integration/adapters/test_cmis_uploader.py` — +4
  tests for thread-safety (concurrent ensure_folder,
  concurrent _warm).
* `tests/unit/tui/test_data_provider.py` — NEW, 1 smoke test
  (snapshot fields populated correctly from synthetic recorder
  + pool stats).
* `tests/integration/cli/test_tui_flag.py` — NEW, 3 tests
  (--no-tui works, --tui in non-TTY exits 2, default-on in
  TTY mocked).

Plus sed-patch existing CLI tests with `--no-tui` (pattern
identical to 022's `--skip-doctor`).

---

## 6. Files touched (estimated)

```
~30 source files
~12 test files
3 spec files (this change)
```

---

## 7. Risks

- **R1 (large)**: Thread-safety bugs in concurrent CmisUploader
  and MetricsRecorder calls are subtle. Mitigation: every
  thread-safety claim in the spec MUST have an explicit test.
  Use `threading.Lock` defensively even where Python's GIL
  protects pure attr writes (because the project may switch to
  3.13t free-threaded later).
- **R2 (large)**: Resizable thread pool is non-trivial. The
  custom implementation in §4.3 has been used in production
  Python code (e.g., aiohttp's executor), but our code is new.
  Mitigation: dedicated unit tests for the pool resize
  semantics. Fall-back: replace-the-pool strategy if the
  custom pool tests don't stabilize within 90 min.
- **R3 (medium)**: `textual` API stability. The project pins
  a specific version. Mitigation: lock the version in
  `pyproject.toml` (`textual >=0.x.y, <0.z.0`).
- **R4 (medium)**: TUI testing is hard. `textual` has an
  `AppTest` helper but it may not be stable. Mitigation: rely
  on the `TUIDataProvider` smoke test + visual smoke of the
  default invocation. Don't try to assert pixel-perfect
  rendering.
- **R5 (small)**: AIMD on the same loop as the pipeline could
  deadlock if the controller blocks the pool. Mitigation:
  controller is in a SEPARATE thread; only mutates the pool's
  target size, doesn't hold locks while sleeping.
- **R6 (small)**: Bandwidth sampler precision. 1-second
  buckets miss sub-second bursts. Mitigation: documented
  limitation; accept for MVP.
- **R7 (large)**: Existing test suite (608 tests as of 024)
  must keep passing. ~25 CLI tests will need `--no-tui`
  patches. Same sed pattern as 022 worked for `--skip-doctor`.
  Verified once on a test run early in Phase 4.
- **R8 (medium)**: `cmis.workers > 1` with the current
  `_post_with_retries`' retry counter is per-call; concurrent
  retries from different workers MAY exhaust their retries
  independently, sending more total requests to CMIS than
  before. Acceptable for MVP — operators tune `retry_max_attempts`
  knowing about the worker count.

---

## 8. Estimated effort

- Spec / plan / tasks: 60 min (done)
- Phase 1 (schema + worker pool + thread-safety + tests): 180 min
- Phase 2 (auto-tune + integration + tests): 150 min
- Phase 3 (TUI app + tabs + chart + data_provider + smoke test): 300 min
- Phase 4 (CLI --tui/--no-tui + adapt existing tests): 90 min
- Phase 5 (verification + docs + commit + merge): 60 min
- **Total**: ~14 h

The cycle is long. If any phase blows past its budget by 50 %, I
will checkpoint by committing the in-progress phase to the
branch and asking the operator before continuing.

---

## 9. Pause / continue checkpoints

Aware of the size, I'll explicitly checkpoint at the end of each
phase:

1. After Phase 1 (worker pool only) — sequential equivalent
   tests pass.
2. After Phase 2 (auto-tune wired) — runs with auto-tune.
3. After Phase 3 (TUI) — visible.
4. After Phase 4 (CLI integration) — production-ready.
5. After Phase 5 (docs + merge).

If a checkpoint fails to converge in <1.5× the estimated time,
I'll pause and surface options (drop a feature, split the
change, etc.).

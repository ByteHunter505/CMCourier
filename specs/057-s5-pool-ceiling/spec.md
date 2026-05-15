# 057 — Size the S5 thread pool to the AIMD ceiling

## Why

On a staging run the operator watched the UPLOAD tab's pool capacity
climb — 4 → 8 → 12 — while "in use" stayed pinned at **4**. The AIMD
auto-tune believes it scaled up; the operator sees idle workers that
do not exist; the uploads still run 4 at a time. The auto-tune knob is
disconnected from the engine.

### The bug — two limiters, stacked in the wrong order

S5 upload concurrency is gated by **two** things:

1. **The `ThreadPoolExecutor`** — the *hard* limit. `_stage_5_single`
   (`staged.py`) creates it with `max_workers=self._workers`, and
   `self._workers` is `cmis.workers` — fixed, captured at construction
   (default 4). Only that many threads ever physically exist.
   `_stage_5_dual` has the same bug, twice (one pool per lane).
2. **The `ResizableSemaphore`** (`self._concurrency_limit`) — the
   *soft* limit, acquired *inside* `_upload_one`. AIMD resizes **this**
   via `_on_pool_resize → set_capacity(new_total)`, up to
   `auto_tune.max_threads` (default **50**).

The semaphore lives *inside* the thread pool. Only `cmis.workers`
threads ever reach `acquire()`. However high AIMD lifts the semaphore,
there are no threads to use the extra slots — **the semaphore can
never be the bottleneck; `max_workers` always is.**

The TUI reads `pool_capacity` from `_concurrency_limit.capacity` (the
semaphore — climbs) and `pool_in_use` from `WorkerPoolStats.busy`
(`mark_busy` calls — capped at `cmis.workers`). Hence the exact
symptom: capacity grows, in-use stuck at 4, idle grows fictitiously.

The `ResizableSemaphore` docstring states the intent verbatim — resize
"*without tearing down the underlying ThreadPoolExecutor*" — and
`_stage_5_dual`'s docstring says each pool is "*sized to the TOTAL
worker budget*". The intent was a generous pool ceiling with the
semaphore regulating underneath; the code sized the pool to the
*initial* value instead of the *ceiling*.

## What

### `_pool_ceiling()` — the real upper bound

A new helper returns the maximum thread count S5 could ever need:

- AIMD enabled (`auto_tune` present and `enabled`) →
  `max(self._workers, auto_tune.max_threads)`.
- AIMD disabled → `self._workers` (unchanged — the pre-057 value is
  already correct when nothing resizes the semaphore).

### Size both S5 pools to the ceiling

- `_stage_5_single` — `ThreadPoolExecutor(max_workers=self._pool_ceiling())`.
- `_stage_5_dual` — both the heavy and the light
  `ThreadPoolExecutor`s get `max_workers=self._pool_ceiling()`. The
  `LaneController`'s per-lane semaphores already cap the *effective*
  per-lane concurrency and AIMD already resizes the lane budget — they
  just need real threads behind them. (Two pools at the ceiling means
  up to `2 × ceiling` threads can exist, but the `LaneController`
  caps effective use at the shared total budget; the surplus threads
  sit idle at near-zero cost — a parked thread.)

The `ResizableSemaphore` / `LaneController` thus become the *effective*
limiter, which is what specs 025 / 036 / 043 always intended. Idle
threads in a `ThreadPoolExecutor` are cheap — they block on the work
queue and consume no CPU.

`WorkerPoolStats.set_pool_size` in `_stage_5_single` is updated to the
ceiling for internal consistency (it is not surfaced in single-lane
mode, but leaving it at the stale initial value would be misleading).

## Out of scope

- Changing the AIMD algorithm, its cadence, its min/max bounds, or the
  `auto_tune.max_threads` default. 057 only connects the existing knob
  to a pool that can honour it.
- A configurable hard cap distinct from `auto_tune.max_threads` — the
  AIMD ceiling already *is* the intended maximum; no new config field.
- The TUI rendering — `data_provider` already reads the right sources
  (`_concurrency_limit.capacity`, `pool.busy`); once real threads
  exist, `pool_in_use` rises on its own. No TUI change needed.

## Acceptance criteria

- `_pool_ceiling()` returns `auto_tune.max_threads` when AIMD is
  enabled and `cmis.workers` when it is disabled — a unit test asserts
  both (including the `max(...)` guard when `cmis.workers >
  max_threads`).
- The `ThreadPoolExecutor` in `_stage_5_single` is constructed with
  `max_workers == _pool_ceiling()` — a test captures the constructor
  argument on a real run with AIMD enabled (`max_threads = 16`,
  `cmis.workers = 4`) and asserts it is `16`, and on a run with AIMD
  disabled asserts it is `4`.
- Both `ThreadPoolExecutor`s in `_stage_5_dual` are constructed with
  `max_workers == _pool_ceiling()` — a test asserts it.
- With AIMD disabled, behaviour is unchanged — the existing
  `test_s5_worker_pool` / dual-lane suites stay green untouched.
- Full unit + integration suite green; mypy + ruff clean.
- `CHANGELOG.md [0.60.0]`; `pyproject.toml` 0.59.0 → 0.60.0.

## Notes on test strategy

The gap that let this ship: the AIMD tests (043) assert the
*semaphore* resizes — never that real threads exist to use the extra
capacity. 057 closes that by capturing the actual `max_workers` passed
to `ThreadPoolExecutor` (patch the class in the `staged` module
namespace with a recording wrapper that delegates to the real one) on
a real pipeline run. That is deterministic — no timing, no
peak-concurrency sampling — and it pins the exact structural fact that
was wrong. The `_pool_ceiling()` unit test pins the computation.

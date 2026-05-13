# 043 — AIMD auto-tune: per-chunk p95 visibility in multi-batch mode

## Why

The §F.4 staging validation of 0.45.0 surfaced a silent regression
introduced by spec 028 (multi-batch overlap, ``batches_in_flight=2``):
the AIMD auto-tune controller's p95 observation always reports
``0.0`` mid-run, so the controller never down-throttles when the
upload pool saturates. Evidence from the F.4 run
(``batch_id=0a7bdf78-871b-42f4-8229-503efbf80578``, ``--total 200``):

* 91 ``auto_tune_decision`` events emitted over 19 minutes.
* 85 of them are ``action="+1"`` (additive increase). Zero are
  ``"-1"``. Workers climbed from 4 to the ``max_threads=16`` cap and
  stayed there.
* Every event has ``p95_observed_ms = 0.0`` — including events
  while real S5 latency was demonstrably 700-1300 ms (visible in
  the live verification harness frames captured during 042).

Root cause: ``StagedPipeline._build_auto_tune_controller``
(``staged.py:255``) wires the controller's ``p95_provider`` to:

```python
p95_provider=lambda: self._metrics.current_stage_p95("S5")
```

``self._metrics`` is the pipeline's own ``MetricsRecorder``,
constructed once at pipeline build. In **single-batch mode (N=1)**
the chunks write their S5 events into ``self._metrics`` — so the
controller sees real p95. In **multi-batch mode (N=2)** the
orchestrator builds a **per-chunk** recorder via
``_build_chunk_recorder`` and routes each chunk's S5 events there.
The pipeline's ``self._metrics`` recorder receives nothing — so
``current_stage_p95("S5")`` returns ``0.0`` forever.

This is the same class of bug as spec 042 #3 (UPLOAD-tab S5
percentiles read from the wrong recorder during PREP overlap). 042
fixed it for the TUI by introducing an ``upload_active_recorder``
slot. 043 extends the same architectural fix to the AIMD
controller.

## What

### 1. ``AutoTuneController.set_p95_provider(provider)``

Allow the controller's ``p95_provider`` callable to be swapped
after construction. Mirrors the public surface of ``start()`` and
``stop()``. Thread-safe (atomic reference replacement).

The pre-043 default (set at construction time from the pipeline's
own recorder) stays the fallback so the single-batch path is
unchanged.

### 2. ``MultiBatchOrchestrator._run_overlapped`` wires the upload provider

Before ``controller.start()`` inside ``_upload_loop``, the
orchestrator calls:

```python
controller.set_p95_provider(self._upload_p95_observer)
```

where ``_upload_p95_observer`` reads from
``self.upload_recorder()`` — the slot 042 already introduced. When
no chunk is in UPLOAD yet (warmup tick) the observer returns
``0.0`` and the controller treats it as "slack available, +1" —
identical behavior to today's first warmup window.

Once a chunk enters UPLOAD, the observer returns that chunk's S5
p95, the controller sees real latency, and the AIMD math behaves
correctly: additive-increase below target, multiplicative-decrease
above target.

## Out of scope

- Restructuring the recorder lifecycle. Per-chunk recorders are
  the right model from 028; the bug is the AIMD's read path, not
  the recorder design.
- Surfacing p95 to other consumers. The TUI already binds correctly
  through 042's ``upload_recorder()`` plumbing. The AIMD is the
  one remaining consumer that read from the wrong slot.
- ``timeout_auto_adjust`` separately. The same provider drives both
  worker-count and timeout decisions — fixing the provider fixes both
  in one shot.
- A "tune both prep + upload" controller. PREP-stage latency is
  CPU-bound and not interesting for AIMD's network-pressure
  decisions; out of scope.

## Acceptance criteria

- A unit test asserts that ``AutoTuneController.set_p95_provider``
  swaps the read path and the next tick uses the new provider.
- A unit test using a real ``MetricsRecorder`` confirms the
  controller observes non-zero p95 once stage events arrive.
- A live re-run of the §F.4 scenario
  (``--total 200 --batches-in-flight 2``) emits at least one
  ``auto_tune_decision`` event with ``p95_observed_ms > 0`` AND
  the worker count does not grow monotonically all the way to
  ``max_threads`` (i.e. AIMD shows mixed up/down activity).
- ``CHANGELOG.md [0.46.0]`` entry.
- mypy + ruff clean.

## Notes on test strategy

The unit tests use a fake ``p95_provider`` callable that returns
canned values to drive the controller through a known sequence
without needing a real ``MetricsRecorder``. The integration check
re-uses the F.4 invocation (~19 min run) and greps the same
``auto_tune_decision`` events used to identify the bug — this is
the smallest reproduction surface and the cleanest verification.

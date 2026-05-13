# 043 — Plan

Three phases (~1.5 h total).

## Phase 1 — ``AutoTuneController.set_p95_provider`` (~30 min)

### Files

- `src/cmcourier/services/auto_tune.py`
  - New public method ``set_p95_provider(provider)`` that atomically
    swaps ``self._p95_provider``. The existing ``_tick`` reads via
    the attribute, so a swap takes effect on the next 15 s interval
    without restarting the controller thread.

### Tests

- `tests/unit/services/test_auto_tune.py` (or wherever the
  controller tests live):
  - ``test_set_p95_provider_takes_effect_next_tick`` — start with a
    provider returning 100, swap to one returning 5000, run a tick,
    assert the recorded ``observed_p95`` matches the new provider.
  - ``test_set_p95_provider_swap_is_atomic`` — basic race-free
    assignment check (no half-state).

### Commit

```
feat(services): AutoTuneController.set_p95_provider swap hook (043 Phase 1)
```

## Phase 2 — Multi-batch orchestrator wires the upload-recorder p95 source (~30 min)

### Files

- `src/cmcourier/orchestrators/multi_batch.py`
  - Add ``_upload_p95_observer()`` method on the orchestrator that
    reads from ``self.upload_recorder()`` (the slot 042 introduced)
    and returns its ``current_stage_p95("S5")``. Falls back to
    ``0.0`` when no chunk is in UPLOAD yet.
  - In ``_run_overlapped._upload_loop``, before
    ``controller.start()``, call
    ``controller.set_p95_provider(self._upload_p95_observer)``.

### Tests

- `tests/unit/orchestrators/test_multi_batch.py`:
  - ``test_overlapped_run_wires_upload_p95_observer`` — run a small
    multi-batch with a real MetricsRecorder + a fake controller
    that captures the assigned provider; assert the provider is the
    upload-side one (not the original pipeline-recorder one).

### Commit

```
fix(orchestrators): multi-batch AIMD reads p95 from upload-active recorder (043 Phase 2)
```

## Phase 3 — Docs + CHANGELOG 0.46.0 + version bump + re-verify F.4 + FF (~30 min)

### Files

- `CHANGELOG.md` — ``[0.46.0]`` Fixed (AIMD multi-batch p95 read
  path), Changed (AutoTuneController gains ``set_p95_provider``),
  no Added/Removed.
- `pyproject.toml` 0.45.0 → 0.46.0.
- `README.md` feature row tick.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.46.0
```

### Live re-verification

Re-run §F.4:

```bash
.venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml \
  --total 200 --batches-in-flight 2 --no-tui
```

Then:

```bash
rg auto_tune_decision sample/logs/app-*.log | python3 -c "
import json, sys
events = [json.loads(l) for l in sys.stdin]
nonzero = [e for e in events if float(e.get('p95_observed_ms', 0)) > 0]
decreases = [e for e in events if e.get('action') == '-1']
print(f'total events: {len(events)}')
print(f'with p95>0: {len(nonzero)}')
print(f'with action -1: {len(decreases)}')
"
```

Acceptance: ``with p95>0`` must be ≥ 1, demonstrating AIMD now
sees real S5 latency in multi-batch mode.

### Commit

```
docs(043): CHANGELOG 0.46.0 + version bump + AIMD live re-verify (043 Phase 3)
```

### FF to main.

# 042 — Plan

Three phases for the bugfix proper (~2h) + a docs/release phase
(~30min). Each phase ships an isolated commit so the bisect surface
stays narrow if any one of these surfaces a regression later.

## Phase 1 — Bandwidth handler batch_id filter (~30min)

### Files

- `src/cmcourier/observability/metrics.py`
  - `_BandwidthHandler.__init__` now takes a required ``batch_id``
    kwarg.
  - ``emit`` short-circuits when ``record.batch_id != self._batch_id``.
    This matches the ``_SlowOpHandler`` shape from 025.
  - ``MetricsRecorder.start_batch`` constructs the handler with the
    current ``batch_id``.

### Tests

- `tests/unit/observability/test_metrics.py` (or its module-level
  equivalent) gains:
  - ``test_bandwidth_handler_filters_by_batch_id`` — emit a record
    with a different ``batch_id`` and assert ``cumulative_bytes`` did
    not move.
  - ``test_bandwidth_handler_accepts_matching_batch_id`` — emit a
    record with the same ``batch_id`` and assert cumulative_bytes
    moved.

### Commit

```
fix(observability): per-batch bandwidth handler filter (042 Phase 1)
```

## Phase 2 — Live S5 counters propagated to CHUNKS row (~45min)

### Files

- `src/cmcourier/observability/metrics.py`
  - New thread-safe counters: ``_s5_done``, ``_s5_failed`` with
    ``record_upload_done()`` / ``record_upload_failed()`` setters
    and ``upload_done_count()`` / ``upload_failed_count()`` getters.
    Mirrors the existing ``_s5_skipped`` / ``record_upload_skipped``
    from 041 Phase 3.
- `src/cmcourier/orchestrators/staged.py`
  - In ``_stage_5_single`` and ``_stage_5_dual``: on the
    ``outcome == "done"`` / ``"failed"`` branches, also call
    ``rec.record_upload_done()`` / ``rec.record_upload_failed()``.
    The orchestrator's local counters stay (the return tuple
    contract is unchanged).
- `src/cmcourier/tui/data_provider.py`
  - ``_chunks_state_snapshot`` reads the active upload recorder
    (see Phase 3) and, when ``status == "UPLOAD"``, overrides
    ``s5_done`` / ``s5_failed`` from the recorder's live counters.
    For ``DONE`` / ``FAILED`` rows it keeps the frozen ChunkState
    value (no change).

### Tests

- `tests/unit/observability/test_metrics.py`:
  - ``test_upload_done_count_thread_safe`` — 32 workers each call
    ``record_upload_done()`` 100×; assert final count == 3200.
- `tests/unit/tui/test_chunks_tab.py`:
  - ``test_upload_row_shows_live_s5_done`` — synthetic snapshot
    with one UPLOAD chunk + non-zero ``s5_done`` field; assert the
    rendered row shows the right ``done/skip/fail`` cell.

### Commit

```
fix(tui,observability): live s5_done/failed in CHUNKS during UPLOAD (042 Phase 2)
```

## Phase 3 — Separate UPLOAD active recorder slot (~30min)

### Files

- `src/cmcourier/orchestrators/multi_batch.py`
  - New slot ``self._upload_active_recorder: MetricsRecorder | None``.
  - New helper ``_set_upload_active_recorder(rec | None)`` lock-protected.
  - New public ``upload_recorder()`` callback.
  - ``_upload_loop`` sets the upload-active recorder when a chunk
    transitions into UPLOAD; clears it (back to None) when the
    chunk transitions to DONE/FAILED. The existing
    ``_set_active_recorder(item.recorder)`` call stays for the
    PREP-tab binding semantics (no change to that side).
- `src/cmcourier/tui/data_provider.py`
  - Constructor accepts an optional ``upload_recorder_provider``
    callable (mirrors ``recorder_provider``).
  - New private ``_upload_metrics`` property that returns the
    upload-active recorder if set, else falls back to
    ``self._metrics`` (the existing single-recorder path).
  - Use ``_upload_metrics`` for:
    - ``current_chunk_bytes_uploaded`` source
      (``recorder.bandwidth.cumulative_bytes()``)
    - the live ``s5_done`` / ``s5_failed`` Phase 2 override
    - The S5 stages snapshot consumed by ``render_upload``.
- `src/cmcourier/cli/app.py`
  - Pass ``upload_recorder_provider=orchestrator.upload_recorder``
    into the ``TUIDataProvider`` construction.

### Tests

- `tests/unit/orchestrators/test_multi_batch.py`:
  - ``test_upload_recorder_returns_none_outside_upload`` — initial
    state.
  - ``test_upload_recorder_tracks_chunk_in_upload`` — overlap path,
    assert ``upload_recorder()`` returns chunk #0's recorder while
    chunk #1 is in PREP.

### Commit

```
fix(orchestrators,tui): separate upload-active recorder slot (042 Phase 3)
```

## Phase 4 — Docs + CHANGELOG 0.45.0 + version bump + FF (~30min)

### Files

- `CHANGELOG.md` — ``[0.45.0]`` section. Categories: Fixed (the three
  bugs by id), Changed (handler signature now takes batch_id —
  internal API, no user-visible breakage), no Added/Removed.
- `pyproject.toml` — 0.44.0 → 0.45.0.
- `README.md` feature row tick.

### Release dance (per CONTRIBUTING)

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.45.0
```

### Verification

Re-run the headless TUI harness (``/tmp/verify_tui_041.py``)
and confirm:

- Final frame ``S5 UPLOAD ... X.X MB / Y.Y MB`` has X ≤ Y (no
  bleed).
- Mid-overlap frame: chunk #0 CHUNKS row shows non-zero
  ``UPLOAD d/s/f`` during S5 (not stuck at 0/0/0).
- Mid-overlap frame: UPLOAD tab's S5 percentile block reflects
  chunk #0's data while chunk #1 is in PREP (p50 > 0).

### Commit

```
docs(042): CHANGELOG 0.45.0 + version bump (042 Phase 4)
```

### FF to main.

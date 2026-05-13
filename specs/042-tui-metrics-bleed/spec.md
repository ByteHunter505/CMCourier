# 042 — TUI metrics: per-chunk isolation + live UPLOAD counters

## Why

A live verification of 041 against the testserver Alfresco
(`--total 100 --batches-in-flight 2`) surfaced three bugs that the
041 unit tests could not catch because they all require a real
multi-batch overlap to reproduce:

1. **CHUNKS row UPLOAD column stays `0/0/0` during the entire S5
   stage.** Operators watching the dashboard see no progress on the
   per-chunk counters until the chunk transitions to DONE. The
   actual upload IS happening (the orchestrator's local `s5_done`
   counter advances), but ``MultiBatchOrchestrator._update_chunk_state``
   only writes the counters into ``ChunkState`` on the DONE
   transition (`multi_batch.py:451`). The intermediate UPLOAD
   ``_update_chunk_state(status="UPLOAD")`` call (`:426`) leaves
   ``s5_done`` and ``s5_failed`` at their defaults of 0.

2. **`bandwidth.cumulative_bytes` leaks across overlapping chunks.**
   With ``batches_in_flight=2``, the final frame of the verification
   run showed ``S5 UPLOAD ... 77.3 MB / 40.4 MB`` — uploaded MB
   greater than chunk total, which is impossible if isolation works.
   Root cause: ``_BandwidthHandler.emit`` filters only by
   ``kind=="cmis_upload"`` and does **not** filter by ``batch_id``.
   When chunk #0 is uploading while chunk #1's recorder has already
   started (PREP), BOTH bandwidth handlers are attached to the
   ``cmcourier.metrics.network`` logger; every ``cmis_upload`` event
   increments both counters. Chunk #1 ends up with chunk #0's bytes
   counted into its cumulative total. Note: ``_SlowOpHandler`` got
   this right — it carries ``batch_id`` and short-circuits on
   ``record.batch_id != self._batch_id``. The bandwidth handler is
   the lone exception.

3. **S5 percentiles in the UPLOAD tab can bind to the wrong chunk's
   recorder during overlap.** Frame 65 of the verification run
   showed ``S5 UPLOAD ... 5.6 MB / 34.7 MB ... p50 0.0 ms`` —
   bytes had accumulated but percentile latencies were zero. Root
   cause: ``MultiBatchOrchestrator._active_recorder`` is a single
   slot. Both ``_prep_loop`` and ``_upload_loop`` call
   ``_set_active_recorder`` when their stage begins. When chunk #1
   enters PREP while chunk #0 is in UPLOAD, the active recorder
   flips to chunk #1's (which has zero S5 activity yet). The UPLOAD
   tab reads percentile data from chunk #1's empty S5 bucket.

## What

### 1. Per-chunk bandwidth handler isolation (bug #2)

``_BandwidthHandler`` gains a required ``batch_id`` parameter on
``__init__`` and short-circuits in ``emit`` when
``record.batch_id != self._batch_id``. ``MetricsRecorder.start_batch``
constructs the handler with its own ``batch_id``, mirroring the
``_SlowOpHandler`` pattern that has worked since 025.

After this fix, with N overlapping chunks every cmis_upload event
still fires on N handlers, but only the matching handler increments
its sampler — bytes stay isolated per chunk.

### 2. Live S5 counters propagated to CHUNKS row (bug #1)

Two changes:

- ``MetricsRecorder`` gains ``record_upload_done()`` and
  ``record_upload_failed()`` (mirror of ``record_upload_skipped``
  added in 041 Phase 3) with thread-safe counters and getter
  methods ``upload_done_count()`` / ``upload_failed_count()``.
- ``_stage_5_single`` and ``_stage_5_dual`` call these on the
  ``"done"`` / ``"failed"`` outcome branches.
- ``data_provider._chunks_state_snapshot`` reads the active
  upload recorder when ``status == "UPLOAD"`` and surfaces
  ``s5_done`` / ``s5_failed`` live (the recorder is per-chunk in
  multi-batch, so per-recorder counters ARE the per-chunk numbers).
  When ``status == "DONE"``, the values come from ``ChunkState``
  as today (frozen at transition).

### 3. Separate UPLOAD-side active recorder (bug #3)

``MultiBatchOrchestrator`` keeps the existing ``_active_recorder``
slot for PREP-tab binding but adds a second slot
``_upload_active_recorder`` set in ``_upload_loop`` only. Exposed
via ``upload_recorder()`` callback alongside the existing
``active_recorder()`` callback. The data provider uses
``upload_recorder()`` for everything S5-shaped:

- ``current_chunk_*`` bytes / elapsed / avg / ETA fields
- The UPLOAD tab's S5 percentile block

The PREP tab keeps using ``active_recorder()`` (the most-recent
PREP-or-UPLOAD chunk). This decouples the two tab bindings so the
PREP-side recorder flip no longer disturbs the UPLOAD-side display.

When no chunk has entered UPLOAD yet, ``upload_recorder()``
returns ``None`` and the data provider falls back to the pipeline's
own recorder (the single-batch path stays byte-identical to today).

## Out of scope

- Re-architecting the recorder lifecycle. The per-chunk recorder
  model from 028 stays as-is.
- Adding a dedicated PREP-side per-chunk recorder slot. PREP tab
  already aggregates fine; this spec only touches the UPLOAD-side
  binding.
- Bandwidth chart series (``bandwidth.series()``). The 60s window
  decays per-handler too, but the cumulative_bytes bug is the one
  with visible operator impact. Chart series accuracy can be
  revisited if it shows up in field reports.
- ``aggregator_snapshot`` (slow-ops) — already isolated correctly
  via ``_SlowOpHandler`` batch_id filter (pre-042 behavior is
  fine).

## Acceptance criteria

- A new unit test asserts ``_BandwidthHandler.emit`` ignores a
  ``cmis_upload`` record whose ``batch_id`` does not match.
- A new unit test asserts ``MetricsRecorder.upload_done_count()``
  advances when ``record_upload_done()`` is called and is
  thread-safe under contention.
- A new TUI snapshot test asserts ``render_chunks`` shows a non-zero
  ``s5_done`` for an UPLOAD-status row whose recorder reports
  uploads.
- A new integration-style test (uses ``MultiBatchOrchestrator`` with
  a fake pipeline) asserts that with two overlapping chunks the
  per-chunk ``cumulative_bytes`` does not bleed between recorders.
- mypy + ruff clean.
- ``CHANGELOG.md [0.45.0]`` entry.

## Notes on test strategy

We add one new integration test that runs ``MultiBatchOrchestrator``
end-to-end with a stub pipeline that fires synthetic ``cmis_upload``
events for each chunk. That is the smallest reproduction surface for
the cross-chunk bleed and the active-recorder flip — neither could
be unit-tested in pure isolation because both depend on the
orchestrator's handler/recorder lifecycle wiring.

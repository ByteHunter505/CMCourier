# 028 — Tasks

## Phase 1 — Schema + chunker
- [ ] T1.1 — Write schema tests for `ProcessingConfig`.
- [ ] T1.2 — Add `ProcessingConfig` to schema.
- [ ] T1.3 — Write chunker tests.
- [ ] T1.4 — Implement `cmcourier/orchestrators/chunked.py`.

## Phase 2 — MetricsRecorder per-batch routing
- [ ] T2.1 — Write isolation tests.
- [ ] T2.2 — Add `batch_id` filter to `_SlowOpHandler`.
- [ ] T2.3 — Wire `batch_id` through `start_batch`.

## Phase 3 — MultiBatchOrchestrator + CLI
- [ ] T3.1 — Write orchestrator unit tests.
- [ ] T3.2 — Implement `MultiBatchOrchestrator`.
- [ ] T3.3 — Write CLI integration tests.
- [ ] T3.4 — Wire `--batches-in-flight` into all pipeline run
      commands.
- [ ] T3.5 — Per-chunk emitter + totals in `_emit_outcome`.

## Phase 4 — Docs + verify
- [ ] T4.1 — `docs/how-to/multi-batch.md`.
- [ ] T4.2 — CHANGELOG `[0.30.0]` + `[Unreleased]`.
- [ ] T4.3 — README tick.
- [ ] T4.4 — POST-MVP §7 SHIPPED in-place.
- [ ] T4.5 — Full gate (ruff + mypy + pytest ≥715).
- [ ] T4.6 — FF merge.

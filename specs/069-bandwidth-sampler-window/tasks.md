# 069 — Tasks

Branch: `feat/069-bandwidth-sampler-window`.

## Phase 1

- [ ] T1. `_BandwidthSampler.record_upload`: new signature +
      uniform distribution over interval buckets
- [ ] T2. `_BandwidthHandler.emit`: derive started_at, drive the
      new signature. Defensive fallback when duration_ms missing.
- [ ] T3. Tests: distribution sanity, fractional, sub-second,
      cumulative preserved, peak reflects sustained.
- [ ] T4. Tests: handler reads duration_ms / falls back.
- [ ] T5. Full pytest + ruff + mypy clean.
- [ ] T6. Commit `fix(metrics): distribute bandwidth bytes over real transmission window (069 Phase 1)`

## Phase 2

- [ ] T7. CHANGELOG `[0.71.0]`
- [ ] T8. pyproject 0.70.0 → 0.71.0
- [ ] T9. `pip install -e . --no-deps` + version verify
- [ ] T10. README feature row tick
- [ ] T11. Commit `docs(069): CHANGELOG 0.71.0 + version bump (069 Phase 2)`
- [ ] T12. FF to main

# 044 — Tasks

## Phase 1 — _apply_resume algorithm rewrite

- [ ] 1.1 Re-order ``_apply_resume`` per spec: validate inputs →
      explicit ``--from-stage`` honored → auto-detect → clean.
- [ ] 1.2 Add gap detection: for each stage N<5, if
      ``stage_counts[S{N}][DONE] > 0`` AND no earlier stage has
      FAILED/PENDING, resolved = N+1.
- [ ] 1.3 Unit test: FAILED in S3 + DONE in S4 → resolves to 3.
- [ ] 1.4 Unit test: S4_DONE=543, S5_DONE=281 → resolves to 5.
- [ ] 1.5 Unit test: only S5_DONE → "Nothing to resume" + exit 0.
- [ ] 1.6 Unit test: clean batch + explicit_from_stage=5 →
      returns 5 (no early exit).
- [ ] 1.7 Unit test: unknown batch_id → exit 1 + "Batch not found".
- [ ] 1.8 mypy + ruff clean.
- [ ] 1.9 Commit
      ``fix(cli): resume detects S{N}_DONE→S{N+1} stage gaps + honors explicit --from-stage (044 Phase 1)``.

## Phase 2 — --batch-id always threaded

- [ ] 2.1 Drop ``if resume_flag else None`` conditional in
      ``resume_batch_id`` assignment.
- [ ] 2.2 Update inline comment documenting the new semantic.
- [ ] 2.3 Integration test: ``--batch-id X`` (no ``--resume``)
      runs and uses X as the literal batch_id.
- [ ] 2.4 mypy + ruff clean.
- [ ] 2.5 Commit
      ``fix(cli): --batch-id always threads to the orchestrator (044 Phase 2)``.

## Phase 3 — docs + CHANGELOG 0.47.0 + version bump + live re-verify + FF

- [ ] 3.1 ``CHANGELOG.md [0.47.0]`` Fixed (3 bugs by id) + Changed
      (algorithm + semantic).
- [ ] 3.2 ``pyproject.toml`` 0.46.0 → 0.47.0.
- [ ] 3.3 ``.venv/bin/pip install -e . --no-deps`` — refresh
      metadata.
- [ ] 3.4 ``cmcourier --version`` reports 0.47.0.
- [ ] 3.5 ``README.md`` feature row tick.
- [ ] 3.6 Live re-verify against staging: kill-mid-S5 + resume.
- [ ] 3.7 Full unit suite + ruff + mypy clean.
- [ ] 3.8 Commit
      ``docs(044): CHANGELOG 0.47.0 + version bump + resume live re-verify (044 Phase 3)``.
- [ ] 3.9 FF to main.

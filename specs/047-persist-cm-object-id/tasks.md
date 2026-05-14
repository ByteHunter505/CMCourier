# 047 — Tasks

## Phase 1 — Thread cm_object_id through mark_stage_done

- [ ] 1.1 ``ITrackingStore.mark_stage_done`` — add keyword-only
      ``cm_object_id: str | None = None``.
- [ ] 1.2 ``SQLiteTrackingStore.mark_stage_done`` — include the
      ``cm_object_id`` column in the UPDATE only when the arg is
      not None; None path unchanged.
- [ ] 1.3 ``IdempotencyCoordinator.mark_uploaded`` — forward
      ``cm_object_id`` into the SQLite ``mark_stage_done`` call.
- [ ] 1.4 ``staged.py`` S5_DONE non-coordinator call passes
      ``cm_object_id=cm_object_id``.
- [ ] 1.5 Integration test: ``mark_stage_done`` with OID persists
      the column.
- [ ] 1.6 Integration test: ``mark_stage_done`` without OID leaves
      the column.
- [ ] 1.7 Unit test: coordinator forwards the kwarg.
- [ ] 1.8 Update any signature-asserting test in
      ``test_ports.py`` / ``test_idempotency.py``.
- [ ] 1.9 mypy + ruff clean. Full suite green.
- [ ] 1.10 Commit
      ``fix(tracking): persist cm_object_id on S5_DONE transition (047 Phase 1)``.

## Phase 2 — docs + CHANGELOG 0.50.0 + version bump + live re-verify + FF

- [ ] 2.1 ``CHANGELOG.md [0.50.0]`` — Fixed (cm_object_id never
      persisted).
- [ ] 2.2 ``pyproject.toml`` 0.49.0 → 0.50.0.
- [ ] 2.3 ``.venv/bin/pip install -e . --no-deps``.
- [ ] 2.4 ``cmcourier --version`` reports 0.50.0.
- [ ] 2.5 ``README.md`` feature row tick.
- [ ] 2.6 ``docs/how-to/validation-checklist.md`` §L.3 — drop the
      known-issue note, restore the tracking-DB query path.
- [ ] 2.7 Live re-verify: 5-doc run → every S5_DONE row has a
      non-NULL ``cm_object_id``.
- [ ] 2.8 Full unit + integration suite green; ruff + mypy clean.
- [ ] 2.9 Commit
      ``docs(047): CHANGELOG 0.50.0 + version bump + cm_object_id re-verify (047 Phase 2)``.
- [ ] 2.10 FF to main.

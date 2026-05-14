# 045 — Tasks

## Phase 1 — 409 recovery in CmisUploader

- [ ] 1.1 ``_lookup_existing_object_id(folder_url, name)`` private
      method — GET ``cmisselector=children``, return
      ``cmis:objectId`` of the matching child or ``None``.
- [ ] 1.2 ``upload(...)`` extended: on 409 from POST, run the
      lookup; return the recovered id on hit, re-raise on miss.
- [ ] 1.3 New structured events
      ``s5_upload_409_recovery_attempt`` /
      ``s5_upload_409_recovered`` / ``s5_upload_409_recovery_failed``
      (added to ``JsonFormatter.ALLOWED_EXTRA_FIELDS`` if their
      payload includes new keys).
- [ ] 1.4 Unit test: 409 + lookup hit → upload returns recovered id.
- [ ] 1.5 Unit test: 409 + lookup miss → re-raises CMISClientError.
- [ ] 1.6 Unit test: 200 first attempt → lookup never invoked.
- [ ] 1.7 mypy + ruff clean.
- [ ] 1.8 Commit
      ``fix(uploader): idempotent 409 recovery — lookup existing object on conflict (045 Phase 1)``.

## Phase 2 — docs + CHANGELOG 0.48.0 + version bump + live re-verify + FF

- [ ] 2.1 ``CHANGELOG.md [0.48.0]`` — Fixed (kill-race
      idempotency), Added (lookup helper + events).
- [ ] 2.2 ``pyproject.toml`` 0.47.0 → 0.48.0.
- [ ] 2.3 ``.venv/bin/pip install -e . --no-deps``.
- [ ] 2.4 ``cmcourier --version`` reports 0.48.0.
- [ ] 2.5 ``README.md`` feature row tick.
- [ ] 2.6 Live re-verify: kill-mid-S5 + resume; assert s5_failed=0.
- [ ] 2.7 Full unit suite + ruff + mypy clean.
- [ ] 2.8 Commit
      ``docs(045): CHANGELOG 0.48.0 + version bump + 409 idempotency live re-verify (045 Phase 2)``.
- [ ] 2.9 FF to main.

# Tasks — 024-background-runner

**Status**: Draft
**Spec**: `specs/024-background-runner/spec.md`
**Plan**: `specs/024-background-runner/plan.md`

---

## Phase 1 — `_lock.py`

- [ ] **1.1 (R)** Create
  `tests/unit/cli/commands/test_lock.py` with 6 tests
  (roundtrip, contention, deterministic path, XDG/tmp
  fallback, pid+ts content).
- [ ] **1.2 (G)** Create `src/cmcourier/cli/commands/_lock.py`:
  - `LockHeld` exception.
  - `acquire_config_lock(config_path)` context manager.
  - `_lock_path_for(config_path) -> Path` helper for testing
    determinism.
- [ ] **1.3** Run phase-1 tests. Iterate.

---

## Phase 2 — `background.py` + `_run_pipeline_command` quiet kwarg

- [ ] **2.1 (G)** Edit `cli/app.py::_run_pipeline_command`:
  - Add `quiet: bool = False` kwarg.
  - Skip `_emit_summary` on success when `quiet=True`.
  - On failure: when `quiet=True`, emit a single-line stderr
    summary; exit 1.
- [ ] **2.2 (G)** Edit `cli/app.py::_apply_resume`:
  - Add `quiet: bool = False` kwarg.
  - Suppress the "Nothing to resume" stdout echo when
    `quiet=True`; still exit 0.
- [ ] **2.3 (G)** Thread the `quiet` value through to
  `_apply_resume` from `_run_pipeline_command`.
- [ ] **2.4 (G)** Create `src/cmcourier/cli/commands/background.py`:
  - `background_command` registered on `main`.
  - Acquires lock; on contention echoes + exits 75.
  - Inside the lock: dispatches into
    `_run_pipeline_command(..., quiet=True)` with the right
    `expected_kind` mapping.
- [ ] **2.5 (G)** Edit `cli/app.py` to register
  `background_command`.

---

## Phase 3 — Integration tests

- [ ] **3.1 (R)** Create
  `tests/integration/cli/test_background.py` with:
  - `test_help` — flag listing.
  - `test_pipeline_choice_enforced` —
    `--pipeline single-doc` exits 2 (Click validation).
  - `test_happy_path_csv_trigger_quiet` — exit 0, stdout
    empty.
  - `test_lock_contention_exits_75` — programmatic lock +
    CliRunner.
  - `test_skip_doctor_passthrough` — auto-doctor bypassed
    with the flag.
- [ ] **3.2** Run phase-3 tests. Iterate.

---

## Phase 4 — Verification + docs + commit + merge FF

- [ ] **4.1** `ruff check src/ tests/` clean.
- [ ] **4.2** `ruff format --check src/ tests/` clean (or
  apply).
- [ ] **4.3** `mypy src/cmcourier/` clean.
- [ ] **4.4** `pytest --cov=src/cmcourier --cov-report=term`
  — ≥580 pass, cov on new files ≥85%.
- [ ] **4.5** `pre-commit run --all-files` clean.
- [ ] **4.6** Smoke:
  - `cmcourier --help` lists `background`.
  - `cmcourier background --help` lists every flag.
- [ ] **4.7** Update `CHANGELOG.md`:
  - Remove `background --pipeline` bullet from Planned.
  - Add `[0.26.0] — 2026-05-10` entry.
- [ ] **4.8** Update `README.md` Status checklist: tick
  "Twenty-fourth change: background runner".
- [ ] **4.9** PII grep on new content.
- [ ] **4.10** Stage. Commit:
  `feat(cli): add cron-friendly background runner with per-config lock`.
- [ ] **4.11** `git checkout main && git merge --ff-only feat/024-background-runner && git branch -d feat/024-background-runner`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..004 (command surface) | 2.4, 2.5, 3.1 |
| REQ-005..010 (lock) | 1.1, 1.2, 2.4 |
| REQ-011..014 (quiet) | 2.1, 2.2, 2.3 |
| REQ-015..017 (dispatch + resume passthrough) | 2.1, 2.2, 2.3, 2.4 |
| REQ-018..020 (observability) | 2.4 |
| REQ-021..022 (test counts) | 1.1, 3.1 |
| REQ-023..025 (verification) | 4.1..4.4 |

---

## Estimated effort

- Phase 1: 50 min
- Phase 2: 40 min
- Phase 3: 60 min
- Phase 4: 30 min
- **Total**: ~3 h

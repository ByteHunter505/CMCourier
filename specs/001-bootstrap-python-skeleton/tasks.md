# Tasks — 001-bootstrap-python-skeleton

**Status**: Draft (under review)
**Created**: 2026-05-08
**Spec reference**: `specs/001-bootstrap-python-skeleton/spec.md`
**Plan reference**: `specs/001-bootstrap-python-skeleton/plan.md`

> Atomic implementation checklist. Each task is small enough to complete in one session. Phases are sequenced so each phase ends in a meaningful intermediate state.

---

## How to read this file

- Tasks are numbered hierarchically: `<phase>.<task>`.
- Tick `[ ]` → `[x]` as each task completes.
- Strict TDD Mode is **enabled**. For tasks that produce code, the implementor follows Red → Green → Refactor:
  1. Write the failing test first (or reuse the spec scenario).
  2. Confirm the test fails for the expected reason.
  3. Write the minimum code to make it pass.
  4. Confirm the test passes.
  5. Refactor while green.
- For non-code tasks (configs, docs), TDD does not apply directly — the verification scenarios in `spec.md §4` are the proof.

---

## Phase 1 — Repo hygiene

Quick wins. No Python code yet.

- [ ] **1.1** Create `.gitignore` at repo root with the entries from `spec.md REQ-018`.
- [ ] **1.2** Create `.editorconfig` at repo root with: `root = true`, `[*]` block setting `indent_style = space`, `indent_size = 4`, `end_of_line = lf`, `charset = utf-8`, `trim_trailing_whitespace = true`, `insert_final_newline = true`. Add `[*.md]` override with `trim_trailing_whitespace = false` (Markdown trailing-space-as-linebreak preservation).

**Phase 1 done when**: `.gitignore` and `.editorconfig` exist and are tracked by git.

---

## Phase 2 — Source layout

Create every package directory with `__init__.py`. No logic.

- [ ] **2.1** Create `src/cmcourier/__init__.py` with:
  ```python
  """CMCourier — banking document migration tool (RVI → IBM Content Manager)."""
  __version__ = "0.0.0"
  ```
- [ ] **2.2** Create `src/cmcourier/main.py` with a one-line module docstring and a placeholder `main()` that imports from `cli.app`. Module-level only — no logic.
- [ ] **2.3** Create `src/cmcourier/domain/__init__.py` with a docstring describing the layer's purpose ("Pure Python; no external dependencies. Models, ports, exceptions.").
- [ ] **2.4** Create `src/cmcourier/domain/models.py` with a docstring placeholder ("Domain models — TriggerRecord, RVABREPDocument, CMMapping, etc. Populated in 002-domain-models-and-ports.").
- [ ] **2.5** Create `src/cmcourier/domain/ports.py` with a docstring placeholder ("Abstract interfaces — IDataSource, ITrackingStore, IAssembler, IUploader. Populated in 002-domain-models-and-ports.").
- [ ] **2.6** Create `src/cmcourier/domain/exceptions.py` with a docstring placeholder ("Typed exception hierarchy. Populated in 002-domain-models-and-ports.").
- [ ] **2.7** Create `src/cmcourier/adapters/__init__.py` and the four sub-package init files: `sources/__init__.py`, `tracking/__init__.py`, `assembly/__init__.py`, `upload/__init__.py`. Each has a docstring naming its purpose.
- [ ] **2.8** Create `src/cmcourier/services/__init__.py` with a layer docstring.
- [ ] **2.9** Create `src/cmcourier/orchestrators/__init__.py` with a layer docstring.
- [ ] **2.10** Create `src/cmcourier/cli/__init__.py` with a layer docstring.
- [ ] **2.11** Create `src/cmcourier/cli/app.py` with the Click group placeholder:
  ```python
  """CMCourier CLI entry point — Click group root."""
  import click

  @click.group()
  @click.version_option()
  def main() -> None:
      """CMCourier — RVI → IBM Content Manager migration tool."""

  if __name__ == "__main__":
      main()
  ```
- [ ] **2.12** Create `src/cmcourier/cli/commands/__init__.py` and `src/cmcourier/cli/ui/__init__.py` with layer docstrings.
- [ ] **2.13** Create `src/cmcourier/config/__init__.py` with a layer docstring.

**Phase 2 done when**: every directory shown in `plan.md §6` exists with its `__init__.py`. Run `find src/cmcourier -name __init__.py | wc -l` and confirm the count matches the layout.

---

## Phase 3 — Build & tooling config

Create `pyproject.toml`. After this phase, `pip install -e .[dev]` must work.

- [ ] **3.1** Create `pyproject.toml` with the `[build-system]` block (`requires = ["setuptools>=68", "wheel"]`, `build-backend = "setuptools.build_meta"`).
- [ ] **3.2** Add the `[project]` block: `name = "cmcourier"`, `version = "0.0.0"`, `description`, `requires-python = ">=3.11"`, `readme = "README.md"`, `license = {text = "Proprietary"}`, `authors = [{name = "bitBreaker"}]`, `keywords`, `classifiers`. Use the description: "CMCourier — banking document migration tool from IBM RVI on AS400 to IBM Content Manager via CMIS."
- [ ] **3.3** Add the `[project].dependencies` array per `plan.md §3.1` (runtime deps with `>=`/`<` bounds).
- [ ] **3.4** Add the `[project.optional-dependencies].dev` array per `plan.md §3.2`.
- [ ] **3.5** Add `[project.scripts]` block: `cmcourier = "cmcourier.cli.app:main"`.
- [ ] **3.6** Add `[tool.setuptools]` block: `package-dir = {"" = "src"}` and `[tool.setuptools.packages.find]` with `where = ["src"]`.
- [ ] **3.7** Add the `[tool.ruff]` and `[tool.ruff.lint]`, `[tool.ruff.lint.per-file-ignores]`, `[tool.ruff.format]` blocks per `plan.md §4.1`.
- [ ] **3.8** Add the `[tool.mypy]` block plus the two `[[tool.mypy.overrides]]` blocks per `plan.md §4.2`.
- [ ] **3.9** Add the `[tool.pytest.ini_options]` block per `plan.md §4.3`.
- [ ] **3.10** Add the `[tool.coverage.run]` and `[tool.coverage.report]` blocks per `plan.md §4.4`.

**Phase 3 done when**:
- `python -m venv .venv && source .venv/bin/activate && pip install -e .[dev]` succeeds in a clean environment.
- `python -c "import cmcourier; print(cmcourier.__version__)"` prints `0.0.0`.

---

## Phase 4 — Tests skeleton + smoke test

Strict TDD applies starting here. The smoke test is the first failing test that drives the rest of phase 3 to be valid.

- [ ] **4.1** Create `tests/__init__.py` (empty).
- [ ] **4.2** Create `tests/conftest.py` with a module docstring only ("Shared pytest fixtures. Populated as adapters land."). No fixtures yet.
- [ ] **4.3** **Red**: write `tests/test_smoke.py` per `plan.md §7`. Run `pytest`. Confirm both tests fail with `ModuleNotFoundError: cmcourier` IF run before phase 3 was complete. (If phase 3 was completed correctly, the tests will pass on first run — that is also acceptable.)
- [ ] **4.4** **Green**: ensure `pytest` passes. If failing, fix the actual cause (likely a `pyproject.toml` typo or a missing `__init__.py`).
- [ ] **4.5** Create `tests/unit/__init__.py`, `tests/unit/domain/__init__.py`, `tests/unit/services/__init__.py`, `tests/unit/orchestrators/__init__.py` — empty unit test stubs ready for phase 002+.
- [ ] **4.6** Create `tests/integration/__init__.py`, `tests/integration/adapters/__init__.py`, `tests/integration/pipeline/__init__.py` — empty integration test stubs.
- [ ] **4.7** Run `pytest -v` and confirm: 2 tests collected, 2 pass, 0 fail. Capture the output for the verification report.

**Phase 4 done when**: `pytest` exits 0 with the smoke test green.

---

## Phase 5 — Pre-commit pipeline

Enforce the constitutional rules from the first commit onward.

- [ ] **5.1** Create `scripts/hooks/no-co-authored-by.sh` per `plan.md §5.2`. Make it executable: `chmod +x scripts/hooks/no-co-authored-by.sh`.
- [ ] **5.2** Create `.pre-commit-config.yaml` per `plan.md §5.1`.
- [ ] **5.3** Run `pre-commit install` and `pre-commit install --hook-type commit-msg`. Confirm it installs both `pre-commit` and `commit-msg` hooks.
- [ ] **5.4** **Smoke test the lint hooks**: run `pre-commit run --all-files`. Expect ruff/mypy to pass on the empty skeleton (or to output autofixes that we then commit). If errors surface, fix and rerun.
- [ ] **5.5** **Smoke test the no-co-authored-by hook**: in a throwaway branch, attempt a commit with `Co-Authored-By: Test <test@example.com>` in the message. Confirm the commit is **rejected** with the expected error message. Capture the output.
- [ ] **5.6** **Smoke test the conventional commit hook**: in the same throwaway branch, attempt a commit with subject `update stuff`. Confirm rejection.
- [ ] **5.7** Discard the throwaway branch (`git branch -D <branch>`).

**Phase 5 done when**: pre-commit hooks installed and validated against the rejection scenarios from `spec.md §4.5` and §4.6.

---

## Phase 6 — Documentation update + verification

Tie the loose ends, scaffold the documentation architecture (per `plan.md §13`), update docs, run the full verification suite.

- [ ] **6.1** Update `README.md` "Getting started" section per `plan.md §8`.
- [ ] **6.2** Update `README.md` Status checklist: tick the line about "Python skeleton bootstrap".
- [ ] **6.3** Update `CHANGELOG.md` per `plan.md §9` — add the `[0.3.0]` block dated to the commit date, and adjust the `[Unreleased]` "Planned for next release" bullets.
- [ ] **6.4** Create `docs/INDEX.md` following the template in `plan.md §13.5` — list every existing artifact (README, CHANGELOG, CONTRIBUTING, constitution, domain spec, POST-MVP, samples) with one-line descriptions; leave `how-to` and `explanation` sections empty with pointers to their READMEs.
- [ ] **6.5** Create `docs/how-to/README.md` per `plan.md §13.4`: purpose statement (problem-oriented "How to use"), naming convention (`how-to/<task-slug>.md`, kebab-case), empty bullet list of available guides, link back to `docs/INDEX.md`.
- [ ] **6.6** Create `docs/explanation/README.md` per `plan.md §13.4`: purpose statement (understanding-oriented "How it works"), naming convention (`explanation/<concept-slug>.md`), empty bullet list of available explanations, link to the project's domain spec as canonical domain explanation, link back to `docs/INDEX.md`.
- [ ] **6.7** Update `README.md` "Documentation map" section: add a top-row link to `docs/INDEX.md` as the canonical entry point. Keep the existing per-artifact rows for quick access.
- [ ] **6.8** Run the full verification suite from `spec.md §8`:
  ```bash
  pip install -e .[dev]
  pytest -v
  ruff check src/ tests/
  ruff format --check src/ tests/
  mypy src/cmcourier/
  pre-commit run --all-files
  ```
  Capture each output. All MUST pass before commit.
- [ ] **6.9** Grep for PII in the new files (per `spec.md §4.8`):
  ```bash
  rg -n '\b\d{6}\b' src/ tests/                      # 6-digit numbers (CIF pattern)
  rg -n -i '(juan|maria|carlos)\s?(perez|gomez|rodriguez)' src/ tests/   # common Argentine names
  ```
  Confirm no real-looking matches.
- [ ] **6.10** Stage all the new and modified files. Confirm `git status` matches the expected file list:
  ```
  modified: README.md
  modified: CHANGELOG.md
  added: .editorconfig
  added: .gitignore
  added: .pre-commit-config.yaml
  added: pyproject.toml
  added: scripts/hooks/no-co-authored-by.sh
  added: src/cmcourier/**/*.py
  added: tests/**/*.py
  added: docs/INDEX.md
  added: docs/how-to/README.md
  added: docs/explanation/README.md
  ```
- [ ] **6.11** Create the implementation commit on the feature branch:
  ```
  feat: bootstrap Python skeleton with hexagonal layout and tooling

  Phase 0 of the implementation order from the spec. Ships
  pyproject.toml (PEP 621) declaring all settled dependencies,
  src/cmcourier/ in src layout with the six hexagonal layers as
  empty packages, tests/ skeleton with a smoke test confirming
  importability and __version__, ruff + mypy + pytest + coverage
  configured to enforce the constitution from the first line of
  real code.

  Pre-commit hooks block: lint failures, format violations, mypy
  errors, non-Conventional-Commits messages, and the Co-Authored-By
  trailer (Constitution Principle IX).

  No business logic in this change. The next change (002-domain-
  models-and-ports) starts populating domain/.

  Closes specs/001-bootstrap-python-skeleton/.
  ```

**Phase 6 done when**: branch is committed, all verification commands green, ready for PR or direct merge.

---

## Phase 7 — Optional: PR + merge

If using GitHub PR workflow:

- [ ] **7.1** Push the branch.
- [ ] **7.2** Open a PR titled `feat: bootstrap Python skeleton` (≤70 chars).
- [ ] **7.3** PR body links to `specs/001-bootstrap-python-skeleton/spec.md`, lists test evidence (smoke test passes, lint/format/mypy clean, hook rejection demonstrated).
- [ ] **7.4** Review (if applicable). Address comments by adding new commits, never amending.
- [ ] **7.5** Merge.

If working solo on `main` (current setup):

- [ ] **7.1-alt** Confirm the verification suite passed.
- [ ] **7.2-alt** Tag if appropriate (we do NOT tag pre-MVP).

---

## Verification mapping (spec → tasks)

For traceability:

| Spec REQ | Tasks that fulfill it |
|----------|----------------------|
| REQ-001 | 3.1 |
| REQ-002 | 3.1–3.10, verified in 3-done and 4.4 |
| REQ-003 | 2.1, verified in 4.4 |
| REQ-004 | 2.11, 3.5 |
| REQ-005 | 3.3 |
| REQ-006 | 3.4 |
| REQ-007 | 3.2 |
| REQ-008 | 2.x (entire phase 2) |
| REQ-009 | 3.6 |
| REQ-010 | 2.x |
| REQ-011 | 3.7 |
| REQ-012 | 3.8 |
| REQ-013 | 3.9 |
| REQ-014 | 3.10 |
| REQ-015 | 5.2 |
| REQ-016 | 5.2 |
| REQ-017 | 5.1, 5.2 |
| REQ-018 | 1.1 |
| REQ-019 | 1.2 |
| REQ-020 | enforced by 6.5 grep + Constitution discipline |
| REQ-021 | 4.3, 4.4 |
| REQ-022 | 4.7 |
| REQ-023 | 6.1 |
| REQ-024 | 6.3 |
| REQ-025 | 6.2 |
| REQ-026 | 6.4 |
| REQ-027 | 6.5 |
| REQ-028 | 6.6 |
| REQ-029 | 6.7 |

| Acceptance scenario | Tasks that produce evidence |
|---------------------|----------------------------|
| 4.1 (fresh install) | 3.1–3.10, 6.4 |
| 4.2 (smoke test passes) | 4.4, 4.7, 6.4 |
| 4.3 (linter clean) | 6.4 |
| 4.4 (mypy clean) | 6.4 |
| 4.5 (Co-Authored-By blocked) | 5.5 |
| 4.6 (non-conventional blocked) | 5.6 |
| 4.7 (hexagonal layering visible) | 2.x |
| 4.8 (no PII) | 6.9 |
| 4.9 (documentation index discoverable) | 6.4, 6.5, 6.6, 6.7 |

---

## Estimated effort

- Phase 1: 5 minutes
- Phase 2: 20 minutes (mechanical, lots of small files)
- Phase 3: 30 minutes (the meat: pyproject.toml + first install)
- Phase 4: 15 minutes (smoke test + structure)
- Phase 5: 25 minutes (pre-commit + hook validation)
- Phase 6: 30 minutes (docs structure + README/CHANGELOG updates + verification + commit)
- **Total**: ~2 hours and 5 minutes of focused work for one contributor pair-programming with an agent.

This is consistent with the spec estimating "Phase 0 — Bootstrap (1 day)" — we are well under that, because much of the prep (constitution, domain spec, docs) is already done.

---

## Notes for the implementor

- Do not deviate from the layout in `plan.md §6` without amending the plan first.
- If a task does not match its corresponding REQ exactly, the spec wins — fix the task or amend the spec.
- If `pyodbc` install fails on your host, install `unixODBC-dev` (Debian/Ubuntu: `sudo apt install unixodbc-dev`; macOS: `brew install unixodbc`) and retry.
- The 50-line function cap (Constitution Principle III) does not bind in this change because there are no functions of consequence. It binds the moment the first real function lands.
- Strict TDD applies for any line of `*.py` under `src/cmcourier/` that does anything beyond a docstring. The placeholders in this change have only docstrings, so the only test that exists is the smoke test — and it covers all production code in this change (the smoke test asserts that `__version__` is set, and that is the only behavior).

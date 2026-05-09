# Spec — 001-bootstrap-python-skeleton

**Status**: Draft (under review)
**Created**: 2026-05-08
**Author**: bitBreaker
**Constitution version at draft time**: v1.0.0

> The **what** of this change. Describes requirements, acceptance scenarios, and out-of-scope items. The **how** lives in `plan.md`. The implementation checklist lives in `tasks.md`.

---

## 1. Intent

Stand up the Python project skeleton so that all subsequent changes have a working sandbox to land code into. Without this scaffolding, no pipeline, adapter, service, or test can be written: `pytest` does not exist, `mypy` does not exist, `ruff` does not exist, and the package `cmcourier` is not importable.

This change does **not** implement any business logic. It is the andamiaje (scaffolding) — `pyproject.toml`, layout, configs, hooks, smoke test. Once it merges, the next change can begin writing real code immediately, with full tooling enforcement from the first line.

This change corresponds to **Phase 0** in `docs/domain/CMCOURIER_REBIRTH.md §15` ("Implementation Order"), now executed under the SDD discipline established in the project constitution.

---

## 2. Why now

- The constitution and the REBIRTH have been ratified. The engineering ground rules are settled.
- Without `pyproject.toml`, the Constitution's Principle VI (Real Test Pyramid) is unenforceable — nothing runs.
- Without `mypy --strict`, Principle I (Hexagonal Architecture, zero deps in `domain/`) is unenforceable at type level.
- Without pre-commit hooks, Principle III (50-line function cap) and the no-`Co-Authored-By` rule are enforced manually, which means inconsistently.
- Every day this delays is a day where someone could write the first line of `pipeline.py` 2.0 and undo the architecture work we already paid for.

---

## 3. Requirements (RFC 2119)

### 3.1 Build & packaging

- **REQ-001**: The project MUST declare its build configuration in a single `pyproject.toml` at the repo root, conforming to PEP 621.
- **REQ-002**: The project MUST be installable in editable mode via `pip install -e .[dev]` from a fresh checkout with no manual steps beyond the install command.
- **REQ-003**: The package name MUST be `cmcourier`. The package MUST be importable as `import cmcourier` immediately after installation.
- **REQ-004**: The project MUST declare an empty entry point `cmcourier = "cmcourier.cli.app:main"` so the binary name is reserved for the CLI even though the CLI does not yet exist meaningfully.

### 3.2 Dependencies

- **REQ-005**: All runtime dependencies declared in Constitution §Constraints MUST be listed under `[project].dependencies`: `pydantic>=2.0`, `click>=8.1`, `pyodbc>=5.0`, `requests>=2.31`, `requests-toolbelt>=1.0`, `pandas>=2.0`, `img2pdf>=0.5`, `Pillow>=10.0`, `PyPDF2>=3.0`.
- **REQ-006**: All development dependencies MUST be listed under `[project.optional-dependencies].dev`: `pytest>=7.4`, `pytest-cov>=4.1`, `ruff>=0.4`, `mypy>=1.8`, `pre-commit>=3.5`, type stubs (`types-requests`, `pandas-stubs`).
- **REQ-007**: Python version MUST be `>=3.11` per Constitution §Constraints.

### 3.3 Source layout

- **REQ-008**: The repository MUST follow the layout described in `docs/domain/CMCOURIER_REBIRTH.md §14.2` for `src/cmcourier/` and `tests/`, with one deviation: only the directories that are required for the skeleton smoke test must be created in this change. Sub-modules that will be filled in later (e.g., `models.py`, `ports.py`) ARE created with docstring-only placeholders, so the hexagonal layering is visible immediately.
- **REQ-009**: The package layout MUST use a `src/` directory (PEP 420 src layout) — `src/cmcourier/__init__.py` is the package root, not a top-level `cmcourier/` directory.
- **REQ-010**: Every directory under `src/cmcourier/` MUST contain an `__init__.py` (no implicit namespace packages).

### 3.4 Tooling configs

- **REQ-011**: `ruff` MUST be configured under `[tool.ruff]` with rules selected to match the project's style: `E`, `W`, `F`, `I`, `B`, `C4`, `UP`, `N`, `SIM`, `RET`, `PTH`. Line length 100.
- **REQ-012**: `mypy` MUST be configured under `[tool.mypy]` with `strict = true` applied to `src/cmcourier/domain/`, `src/cmcourier/services/`, `src/cmcourier/orchestrators/`. Other layers (`adapters/`, `cli/`, `config/`) MAY use a more permissive config to accommodate untyped third-party deps, but MUST still be type-checked.
- **REQ-013**: `pytest` MUST be configured under `[tool.pytest.ini_options]` with `testpaths = ["tests"]`, marker definitions for `unit`, `integration`, `slow`, and `addopts = ["-ra", "--strict-markers"]`.
- **REQ-014**: `coverage` MUST be configured under `[tool.coverage.run]` and `[tool.coverage.report]` with `source = ["src/cmcourier"]`, `branch = true`, and `fail_under = 80`. The 80% threshold becomes binding the moment the first real code lands; the empty skeleton is exempt by virtue of having no testable code.

### 3.5 Pre-commit hooks

- **REQ-015**: A `.pre-commit-config.yaml` MUST be present at the repo root.
- **REQ-016**: The pre-commit pipeline MUST include: `ruff check` (lint), `ruff format --check` (format), `mypy` on staged files of in-scope layers, and a Conventional Commits message check.
- **REQ-017**: The pre-commit pipeline MUST block any commit message that contains `Co-Authored-By` (case-insensitive) per Constitution §Workflow.

### 3.6 Repo hygiene

- **REQ-018**: A `.gitignore` MUST cover Python build/runtime artifacts: `__pycache__/`, `*.pyc`, `*.pyo`, `*.egg-info/`, `dist/`, `build/`, `.venv/`, `venv/`, `env/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.coverage`, `htmlcov/`, `logs/`, `tmp/`, `staging/`, `.idea/`, `.vscode/`.
- **REQ-019**: An `.editorconfig` MUST be present at the repo root with: 4-space indentation, LF line endings, UTF-8 encoding, trim trailing whitespace, insert final newline.
- **REQ-020**: The skeleton MUST NOT add any sample/test data containing real CIFs, customer names, or account numbers (Constitution Principle VIII).

### 3.7 Smoke test

- **REQ-021**: `tests/test_smoke.py` MUST exist and contain at minimum two tests:
  - One that asserts `import cmcourier` succeeds.
  - One that asserts `cmcourier.__version__` is a non-empty string matching SemVer pattern.
- **REQ-022**: The smoke test MUST pass on the empty skeleton — it is the single proof that the scaffolding works.

### 3.8 Documentation update

- **REQ-023**: The `Getting started` section in `README.md` MUST be filled in (no longer a placeholder), describing the install / test / lint commands.
- **REQ-024**: A `CHANGELOG.md` entry under `[Unreleased]` MUST document this change before the commit lands.
- **REQ-025**: The Status checklist in `README.md` MUST tick the bootstrap line.

---

## 4. Acceptance Scenarios

Scenarios use Given/When/Then format. Each is independently verifiable.

### 4.1 Fresh install works

- **Given** a clean checkout of the `feat/001-bootstrap-python-skeleton` branch
- **And** Python 3.11 or newer is installed
- **And** a fresh virtualenv is active
- **When** the contributor runs `pip install -e .[dev]`
- **Then** the install completes without errors
- **And** `python -c "import cmcourier; print(cmcourier.__version__)"` prints a SemVer string

### 4.2 Smoke test passes

- **Given** the package is installed per scenario 4.1
- **When** the contributor runs `pytest`
- **Then** the smoke test passes
- **And** the test report shows zero failures, zero errors

### 4.3 Linter passes on the skeleton

- **Given** the package is installed per scenario 4.1
- **When** the contributor runs `ruff check src/ tests/` and `ruff format --check src/ tests/`
- **Then** no errors are reported
- **And** the exit code is zero

### 4.4 Type checker enforces strict on domain

- **Given** the package is installed per scenario 4.1
- **When** the contributor runs `mypy --strict src/cmcourier/domain/`
- **Then** no errors are reported
- **And** the exit code is zero

### 4.5 Pre-commit hook blocks bad commits

- **Given** the contributor has run `pre-commit install` in their working tree
- **When** they attempt a commit with a message containing `Co-Authored-By: <anyone>`
- **Then** the commit is aborted with a message naming the offending line
- **And** the commit is NOT added to the branch

### 4.6 Pre-commit hook blocks unconventional commits

- **Given** the contributor has run `pre-commit install`
- **When** they attempt a commit with the subject `update stuff`
- **Then** the commit is aborted because the message is not Conventional Commits compliant

### 4.7 Hexagonal layering visible in layout

- **Given** the change is merged
- **When** an outsider opens `src/cmcourier/`
- **Then** they see directories `domain/`, `adapters/`, `services/`, `orchestrators/`, `cli/`, `config/`
- **And** every directory has an `__init__.py`
- **And** `domain/` contains placeholder files `models.py`, `ports.py`, `exceptions.py` with docstrings explaining their future role

### 4.8 No PII in fixtures

- **Given** the change is merged
- **When** the contributor greps for known PII patterns (real-looking 6-digit CIFs, common Argentine names) under `src/`, `tests/`, `docs/samples/`
- **Then** no matches are found
- **And** any sample files use synthetic identifiers like `JUANPEREZ01` (already documented as synthetic in REBIRTH)

---

## 5. Out of Scope

These items are explicitly NOT part of this change. They each get their own future change.

- Implementation of any domain model (`TriggerRecord`, `RVABREPDocument`, `CMMapping`, etc.). Spec/plan/code for those is the second change.
- Implementation of any port (interface). Same as above.
- Any concrete adapter (CSV, AS400, SQLite, CMIS, PDF assembly). Each adapter gets its own change.
- Any pipeline or orchestrator code.
- Any CLI command beyond a placeholder Click group that prints a help message.
- Configuration schema (`pydantic` models for `config.yaml`).
- Real `config.yaml` file under `config/`.
- `docker-compose.yml` for Alfresco integration testing.
- Linux-side AS400 driver setup documentation.
- CI pipeline definition (GitHub Actions, etc.). Will land in a separate `chore` change once the test surface justifies it.
- Real coverage threshold enforcement (skeleton has no testable code; threshold becomes binding when first real code lands).

---

## 6. Constraints from Constitution

This spec MUST NOT violate any constitutional principle. Specifically:

- **Principle I**: `domain/` will be created with no third-party imports. Even the docstring-only placeholders import nothing.
- **Principle III**: every config file we create stays under tripwires (no 1000-line `pyproject.toml`). All files in this change are short.
- **Principle V**: no environment variable reads in any module other than the (forthcoming) `config/env.py`. The skeleton's modules are empty enough that this is trivial.
- **Principle VII**: this spec exists before any code ships. The plan and tasks files exist before any implementation begins.
- **Principle VIII**: no PII anywhere. Confirmed in scenario 4.8.
- **Principle IX**: every choice in this spec is justified — no decoration, no trend-chasing.

---

## 7. Risks & Open Questions

### 7.1 Known risks

- **Pre-commit hooks may slow down the first contributor** until they get used to fixing lint/format errors locally before pushing. Mitigation: documented in CONTRIBUTING.md with concrete fix commands (`ruff format src/`, `ruff check --fix src/`).
- **`mypy --strict` on empty skeleton may surface zero issues today, then explode the moment real code lands.** That is by design — strict mode catches issues at the line they are introduced, not at the end of a sprint. Plan documents how to handle gradual adoption if needed.
- **`pyodbc` does not install cleanly on every host** without the unixODBC dev headers. CI / contributor docs MUST mention this.

### 7.2 Open questions (must resolve in plan.md)

- Build backend choice: `setuptools`, `hatchling`, `pdm-backend`, or `poetry-core`? Plan picks one and documents why.
- `pre-commit` framework version: pinned exactly, or `>=`? Plan decides.
- Does the smoke test live at `tests/test_smoke.py` (top-level) or `tests/unit/test_smoke.py`? Plan decides.
- `ruff` per-file-ignores: do we want `__init__.py` exempted from `F401` (unused imports)? Plan decides.

---

## 8. Verification Strategy

Verification of this spec happens in `/sdd-verify` (or its manual equivalent) by mapping each REQ and Scenario to a concrete check:

- REQ-001 → grep `pyproject.toml` exists at repo root, `[project]` block present
- REQ-002 → run scenario 4.1 in a clean venv
- REQ-003 → `python -c "import cmcourier"` exits 0
- REQ-004 → grep entry-point in `pyproject.toml`
- REQ-005, REQ-006 → grep dependency strings in `pyproject.toml`
- REQ-007 → `requires-python = ">=3.11"` present
- REQ-008–REQ-010 → repo tree matches expected layout
- REQ-011–REQ-014 → grep config blocks in `pyproject.toml`, run each tool against the empty tree
- REQ-015–REQ-017 → run `pre-commit run --all-files`; run a synthetic commit attempting `Co-Authored-By` and verify rejection
- REQ-018, REQ-019 → grep `.gitignore` and `.editorconfig` entries
- REQ-020, scenario 4.8 → automated grep for PII patterns
- REQ-021, REQ-022, scenario 4.2 → run `pytest`
- REQ-023 → diff of `README.md` shows new content under "Getting started"
- REQ-024 → diff of `CHANGELOG.md` shows new entry
- REQ-025 → diff of `README.md` shows ticked checkbox

---

## 9. Cross-References

- Constitution: `.specify/memory/constitution.md`
- Domain ground truth: `docs/domain/CMCOURIER_REBIRTH.md` (especially §14.2 "Project Layout" and §15 "Implementation Order")
- Post-MVP roadmap: `docs/roadmap/POST-MVP.md`
- Project workflow: `CONTRIBUTING.md`
- Current changelog: `CHANGELOG.md`

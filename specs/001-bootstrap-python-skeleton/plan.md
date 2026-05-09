# Plan — 001-bootstrap-python-skeleton

**Status**: Draft (under review)
**Created**: 2026-05-08
**Spec reference**: `specs/001-bootstrap-python-skeleton/spec.md`
**Constitution version at draft time**: v1.0.0

> The **how** of this change. Describes architectural decisions, library choices, and the final layout. Implementation breakdown lives in `tasks.md`.

---

## 1. Approach Summary

A single `pyproject.toml` (PEP 621) declares the entire build, dependencies, and tooling configuration. No `setup.py`. No `setup.cfg`. The repo gets a `src/`-layout skeleton with empty `__init__.py` files in every package, a smoke test that proves importability, and a pre-commit pipeline that enforces the constitutional rules from the first commit.

The change is intentionally narrow: every line of code or configuration in this change must be justified by a requirement in `spec.md`. Nothing is added "because we'll need it later" — that is the kind of speculative scaffolding that grew the old `pipeline.py` to 1341 lines.

---

## 2. Build & Packaging Decisions

### 2.1 Build backend: `setuptools`

**Decision**: Use `setuptools>=68` as the build backend.

**Alternatives considered**:
- `hatchling`: modern, lightweight, fewer features. Adoption growing.
- `pdm-backend`: tied to PDM; we are not using PDM as the dependency manager.
- `poetry-core`: tied to Poetry; we are not using Poetry.

**Rationale**:
- `setuptools` is the default. Every Python developer on the planet understands it.
- We do not need any feature that `hatchling` provides above `setuptools` (no plugins, no dynamic versioning beyond `version = "0.0.0"`).
- Switching backend later is cheap if a feature gap appears.
- Constitution Principle IX: "concepts over code, verify over assume". Choosing the boring default is the verified option.

### 2.2 src layout (PEP 420)

**Decision**: All importable code lives under `src/cmcourier/`. No top-level `cmcourier/` directory.

**Rationale**:
- Forces editable installs to actually install the package (rather than picking up the repo root as if it were on `PYTHONPATH`). This catches missing `__init__.py` and mis-declared modules at install time, not at runtime.
- Eliminates a class of "tests pass locally but fail on CI" problems caused by import resolution differences.
- Standard practice for modern Python projects.

### 2.3 Version

**Decision**: Hardcoded `__version__ = "0.0.0"` in `src/cmcourier/__init__.py`. SemVer bumps from there as real features land.

**Rationale**:
- We do not need dynamic versioning from git tags yet. When the first MVP ships, we revisit (likely `setuptools-scm` or a manual bump policy).
- Empty skeleton ≠ shippable software. `0.0.0` is honest; `0.1.0` would imply something works.

### 2.4 Entry point reservation

**Decision**: Declare `[project.scripts] cmcourier = "cmcourier.cli.app:main"` even though `main` does not exist beyond a placeholder Click group.

**Rationale**:
- Reserves the binary name from day one. The first contributor to add a real CLI command does not have to refactor the install.
- Forces the placeholder `main()` function to exist with the correct signature, which is documentation in itself.

---

## 3. Dependency Pinning Policy

### 3.1 Runtime dependencies

Pin to **minimum compatible versions** with `>=` (no upper bound) for now:

```toml
[project]
dependencies = [
  "pydantic>=2.0,<3.0",        # major-version cap to avoid silent breakage
  "click>=8.1,<9.0",
  "pyodbc>=5.0,<6.0",
  "requests>=2.31,<3.0",
  "requests-toolbelt>=1.0,<2.0",
  "pandas>=2.0,<3.0",
  "img2pdf>=0.5,<1.0",
  "Pillow>=10.0,<12.0",
  "PyPDF2>=3.0,<4.0",
]
```

**Rationale**:
- Lower bound = minimum we have validated against. We will validate against these versions during MVP.
- Upper bound = next major. Major versions are where breaking changes happen; we want to consciously choose to upgrade.
- No exact pins (`==`) at this layer. Exact pins live in a `requirements.lock` file (post-MVP, when we have a CI pipeline that needs reproducibility).

### 3.2 Development dependencies

```toml
[project.optional-dependencies]
dev = [
  "pytest>=7.4,<9.0",
  "pytest-cov>=4.1,<6.0",
  "ruff>=0.4,<1.0",
  "mypy>=1.8,<2.0",
  "pre-commit>=3.5,<5.0",
  "types-requests>=2.31,<3.0",
  "pandas-stubs>=2.0,<3.0",
]
```

---

## 4. Tooling Configuration

### 4.1 ruff

```toml
[tool.ruff]
line-length = 100
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = [
  "E", "W",   # pycodestyle
  "F",        # pyflakes
  "I",        # isort
  "B",        # flake8-bugbear
  "C4",       # flake8-comprehensions
  "UP",       # pyupgrade
  "N",        # pep8-naming
  "SIM",      # flake8-simplify
  "RET",      # flake8-return
  "PTH",      # flake8-use-pathlib
  "TID",      # flake8-tidy-imports
]
ignore = []

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]   # __init__.py may re-export without using
"tests/*" = ["S101"]       # asserts allowed in tests

[tool.ruff.format]
# defaults are fine; ruff format mimics black
```

**Decision on `F401` for `__init__.py`**: yes, exempt. Re-exports are intentional in `__init__.py`.

### 4.2 mypy

Two-tier strictness as specified in the spec:

```toml
[tool.mypy]
python_version = "3.11"
files = ["src/cmcourier", "tests"]
strict = false              # baseline; overridden per-module below
warn_unused_configs = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_return_any = true

# Strict for the layers where Principle I demands it
[[tool.mypy.overrides]]
module = [
  "cmcourier.domain.*",
  "cmcourier.services.*",
  "cmcourier.orchestrators.*",
]
strict = true

# Third-party deps with weak or missing stubs
[[tool.mypy.overrides]]
module = ["img2pdf", "pyodbc", "PyPDF2", "requests_toolbelt.*"]
ignore_missing_imports = true
```

**Rationale**: strict mode on the inner layers (where the constitution demands cleanliness) and pragmatic mode on the adapter layer (where third-party libraries with bad stubs would otherwise produce noise). This matches Constitution §Constraints / Type checking.

### 4.3 pytest

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["-ra", "--strict-markers", "--strict-config"]
markers = [
  "unit: fast tests that mock all ports",
  "integration: tests that exercise real adapters (SQLite, CSV, Alfresco, etc.)",
  "slow: tests that take more than 5 seconds individually",
]
```

### 4.4 coverage

```toml
[tool.coverage.run]
source = ["src/cmcourier"]
branch = true

[tool.coverage.report]
fail_under = 80          # binding from the moment the first real code lands
show_missing = true
skip_covered = false
exclude_lines = [
  "pragma: no cover",
  "if TYPE_CHECKING:",
  "raise NotImplementedError",
]
```

**Note**: 80% threshold is configured but the skeleton itself has zero production code. Coverage of an empty package is trivially 100%, so the threshold "passes" from day one without being meaningful. The threshold becomes binding the moment real code ships. This is by design.

---

## 5. Pre-commit Pipeline

### 5.1 Hooks

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.10
    hooks:
      - id: ruff           # lint with autofix
        args: ["--fix"]
      - id: ruff-format    # formatting

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies: ["pydantic>=2.0", "types-requests"]
        files: ^src/cmcourier/
        # Run only on staged Python files in scope

  - repo: https://github.com/compilerla/conventional-pre-commit
    rev: v3.4.0
    hooks:
      - id: conventional-pre-commit
        stages: [commit-msg]
        args: ["feat", "fix", "docs", "refactor", "test", "chore", "perf", "ci"]

  - repo: local
    hooks:
      - id: no-co-authored-by
        name: Block Co-Authored-By in commit messages
        entry: bash scripts/hooks/no-co-authored-by.sh
        language: system
        stages: [commit-msg]
```

### 5.2 The `no-co-authored-by` hook

Implemented as a tiny shell script under `scripts/hooks/no-co-authored-by.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
msg_file="$1"
if grep -qiE '^[[:space:]]*Co-Authored-By:' "$msg_file"; then
  echo "ERROR: commit message contains 'Co-Authored-By' — disallowed by Constitution Principle IX." >&2
  echo "If this is human pair-programming, list the co-author in the PR description instead." >&2
  exit 1
fi
```

**Rationale**: a pre-commit hook is the only place this rule is enforced automatically. Constitution prose alone does not block bad commits.

### 5.3 Hooks framework version pin

**Decision**: pin all hook versions exactly (the `rev:` field above). Pre-commit's own version is pinned in `dev` deps with `>=3.5,<5.0`.

**Rationale**: hook versions changing under us is a CI surprise we do not need. Bumping is a deliberate `chore: bump pre-commit hooks` change.

---

## 6. Final Repo Layout

After this change merges:

```
CMCourier/
├── .editorconfig
├── .gitignore
├── .pre-commit-config.yaml
├── .specify/
│   └── memory/constitution.md
├── .atl/skill-registry.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── README.md                          (Getting started filled in)
├── pyproject.toml                     (NEW)
├── docs/
│   ├── domain/CMCOURIER_REBIRTH.md
│   ├── roadmap/POST-MVP.md
│   └── samples/{csv,excel,responses}/
├── scripts/
│   └── hooks/
│       └── no-co-authored-by.sh        (NEW)
├── specs/
│   └── 001-bootstrap-python-skeleton/
│       ├── spec.md
│       ├── plan.md
│       └── tasks.md
├── src/
│   └── cmcourier/                      (NEW)
│       ├── __init__.py                 (with __version__ = "0.0.0")
│       ├── main.py                     (placeholder; calls cli.app.main())
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── models.py               (docstring-only placeholder)
│       │   ├── ports.py                (docstring-only placeholder)
│       │   └── exceptions.py           (docstring-only placeholder)
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── sources/
│       │   │   └── __init__.py
│       │   ├── tracking/
│       │   │   └── __init__.py
│       │   ├── assembly/
│       │   │   └── __init__.py
│       │   └── upload/
│       │       └── __init__.py
│       ├── services/
│       │   └── __init__.py
│       ├── orchestrators/
│       │   └── __init__.py
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── app.py                  (Click group placeholder + main())
│       │   ├── commands/
│       │   │   └── __init__.py
│       │   └── ui/
│       │       └── __init__.py
│       └── config/
│           └── __init__.py
└── tests/                              (NEW)
    ├── __init__.py
    ├── conftest.py                     (empty placeholder)
    ├── test_smoke.py                   (the only test today)
    ├── unit/
    │   ├── __init__.py
    │   ├── domain/__init__.py
    │   ├── services/__init__.py
    │   └── orchestrators/__init__.py
    └── integration/
        ├── __init__.py
        ├── adapters/__init__.py
        └── pipeline/__init__.py
```

**Notes on the layout**:
- Every empty `__init__.py` is **intentional** — no namespace packages, every subdirectory is an explicit package.
- `domain/{models,ports,exceptions}.py` are docstring-only placeholders so the layering is visually obvious from day one.
- `cli/app.py` exists as a placeholder so the entry point declared in `pyproject.toml` actually resolves.
- `tests/` mirrors `src/cmcourier/` partially — only the layers that will hold unit tests (`domain`, `services`, `orchestrators`) need stubs. Integration tests are organized by what they test (`adapters`, `pipeline`).

---

## 7. Smoke Test Detail

`tests/test_smoke.py`:

```python
"""Smoke tests: minimal proof that the package is installed and importable."""
import re

import cmcourier


def test_package_imports() -> None:
    """The package must be importable after `pip install -e .[dev]`."""
    assert cmcourier is not None


def test_version_is_set() -> None:
    """The package must expose a SemVer-compatible __version__ string."""
    version = getattr(cmcourier, "__version__", None)
    assert isinstance(version, str), "cmcourier.__version__ must be a string"
    assert version, "cmcourier.__version__ must be non-empty"
    assert re.match(r"^\d+\.\d+\.\d+(?:[-+].*)?$", version), (
        f"cmcourier.__version__ must be SemVer-compatible, got {version!r}"
    )
```

**Decision on placement**: `tests/test_smoke.py` (top-level), NOT `tests/unit/test_smoke.py`. Reason: the smoke test is meta — it tests that the build works, not a domain unit. It should not be discovered as part of unit tests once `tests/unit/` fills up.

---

## 8. README "Getting started" Section

Replaces the current placeholder:

```markdown
## Getting started

### Prerequisites

- Python 3.11 or newer
- A C compiler and `unixODBC-dev` (Linux) / IBM iSeries Access ODBC Driver (Windows) — required by `pyodbc`
- Git

### Install (editable, with development tooling)

```bash
git clone <repo> CMCourier
cd CMCourier
python -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate            # Windows
pip install -e .[dev]
pre-commit install
```

### Run the smoke test

```bash
pytest                             # all tests
pytest -m unit                     # only unit tests
pytest -m integration              # only integration tests
```

### Lint, format, type-check

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/cmcourier/
```

### Pre-commit hook bypass

You don't bypass pre-commit hooks. If a hook fails, fix the cause and create a new commit. Never `--no-verify` (Constitution / Git Safety Protocol).
```

---

## 9. CHANGELOG Entry

Under `[Unreleased]` in `CHANGELOG.md`, replace the "Planned for next release" bullets with:

```markdown
## [Unreleased]

### Planned for next release
- First domain change: dataclasses + ports + exceptions for the hexagonal core.

## [0.3.0] — 2026-05-XX (this change's date once committed)

### Added
- `pyproject.toml` (PEP 621) with all runtime and dev dependencies pinned per Constitution §Constraints.
- `src/cmcourier/` skeleton in src layout (PEP 420) with hexagonal layering visible: `domain/`, `adapters/`, `services/`, `orchestrators/`, `cli/`, `config/`.
- `tests/` with unit / integration mirroring + a smoke test (`test_smoke.py`) confirming the package imports and exposes a SemVer `__version__`.
- `.pre-commit-config.yaml` with ruff, mypy, conventional-commits, and a custom `no-co-authored-by` hook.
- `.gitignore`, `.editorconfig`.
- README "Getting started" section.
- `scripts/hooks/no-co-authored-by.sh` to enforce Constitution §Workflow rule via pre-commit.
- `specs/001-bootstrap-python-skeleton/{spec.md, plan.md, tasks.md}` documenting this change end to end.
```

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `pyodbc` install fails on CI / contributor host without `unixODBC-dev` | README Getting started lists the prerequisite explicitly. Future CI pipeline (separate change) installs it via apt/brew. |
| `pre-commit` first-run is slow (downloads hook environments) | Documented in README. One-time cost. |
| `mypy --strict` blocks the first real code change with stub gaps in `pyodbc`/`img2pdf` | `tool.mypy.overrides` for those modules already set `ignore_missing_imports = true`. |
| Coverage threshold of 80% on empty skeleton looks like cheating | It is, by design. Documented as such. Becomes binding when first real code lands. |
| Pre-commit hook on commit-msg fails on `git commit -m "..."` (no editor) | conventional-pre-commit and the no-co-authored-by hook both run on `commit-msg`, which fires for `-m` commits too. Works. |
| Conventional Commits hook is too strict for `wip` commits during local development | Contributors are expected to squash before opening PR. Documented in CONTRIBUTING.md. If pain becomes real, we add an opt-in skip (separate change). |

---

## 11. Implementation Order Hint

The `tasks.md` file groups tasks by phase. The phases are sequenced so that each phase produces a partial-working state — at the end of any phase, the contributor can stop, push, and have a meaningful intermediate commit.

Phases:
1. Repo hygiene (gitignore, editorconfig)
2. Source layout (empty `__init__.py` everywhere)
3. Build & tooling config (`pyproject.toml`)
4. Tests skeleton + smoke test
5. Pre-commit pipeline
6. Verification + docs update

This order matches the dependency graph: hygiene before layout, layout before pyproject (which references the layout), pyproject before tests (so `pip install -e .[dev]` works), tests before pre-commit (so `pre-commit run --all-files` has things to run against), pre-commit before docs (so the docs reflect the working state).

---

## 12. Open Questions (now resolved)

The spec listed 4 open questions. Resolved here:

| Question | Resolution |
|----------|------------|
| Build backend? | `setuptools` (§2.1 above) |
| pre-commit version pinning? | Exact pins per hook; framework `>=3.5,<5.0` (§5.3) |
| Smoke test placement? | `tests/test_smoke.py` (top level), NOT `tests/unit/` (§7) |
| `__init__.py` exempted from `F401`? | Yes, in `[tool.ruff.lint.per-file-ignores]` (§4.1) |

---

## 13. Documentation Architecture

CMCourier uses a **Diátaxis-inspired** documentation layout (https://diataxis.fr): documentation is split by *purpose* rather than by topic. This avoids the typical mess of one giant README that tries to teach, explain, and reference all at once.

### 13.1 The four quadrants of Diátaxis

| Quadrant | Purpose | Reader's mindset |
|----------|---------|------------------|
| **Tutorials** | Learning-oriented | "I am new and want to learn by doing" |
| **How-to guides** | Problem-oriented | "I need to solve this specific task" |
| **Reference** | Information-oriented | "I need to look up a specific fact" |
| **Explanation** | Understanding-oriented | "I want to understand how/why this works" |

### 13.2 What we ship in 001 (pragmatic subset)

For this change we materialize **only the two quadrants the user explicitly requested**: `how-to` and `explanation`. Tutorials and reference are deferred until natural content appears — a tutorial is best written when the first pipeline ships and there is something to walk through; a reference is best written when the CLI command surface stabilizes.

```
docs/
├── INDEX.md                     # The map of all documentation (NEW)
├── domain/                       # already exists — explanation-class but special
│   └── CMCOURIER_REBIRTH.md     # domain ground truth (precedence #4)
├── roadmap/                      # already exists
│   └── POST-MVP.md
├── samples/                      # already exists — reference fixtures
│   └── {csv,excel,responses}/
├── how-to/                       # NEW — "How to use"
│   └── README.md                 # purpose + naming convention + index of guides
└── explanation/                  # NEW — "How it works"
    └── README.md                 # purpose + naming convention + index of explanations
```

`docs/domain/CMCOURIER_REBIRTH.md` stays where it is despite being explanation-class. It is the **domain ground truth** with precedence #4 in the constitution; moving it would invalidate cross-references in already-shipped artifacts (constitution, README, plan files). It is linked from `docs/explanation/README.md` as canonical domain explanation.

### 13.3 Naming conventions

- **How-to**: `docs/how-to/<task-slug>.md` (e.g., `run-rvabrep-pipeline.md`, `configure-cmis-credentials.md`, `recover-from-failed-batch.md`).
- **Explanation**: `docs/explanation/<concept-slug>.md` (e.g., `stage-architecture.md`, `metadata-resolution-cascade.md`, `cmis-session-warmup.md`).
- Slugs are kebab-case, descriptive, stable. Renaming an existing doc is a breaking change for external links — bump CHANGELOG.

### 13.4 What goes in each subdirectory README

Each `how-to/README.md` and `explanation/README.md`:

1. States the purpose of that kind of doc in 2-3 sentences (the Diátaxis quadrant definition adapted to CMCourier).
2. Lists the naming convention from §13.3.
3. Lists currently-available content as a markdown bullet list (empty at MVP start; filled as docs are added — every change that ships a doc updates the appropriate README).
4. Links back to `docs/INDEX.md` for navigation.

### 13.5 What goes in `docs/INDEX.md`

A single-page map of **every** documentation artifact in the repo, grouped by category, with one-line descriptions and links. Approximate shape:

```markdown
# CMCourier — Documentation Index

The single map of every document in the project. Pick the quadrant that matches your intent.

## For everyone
- README.md — project overview, current status
- CHANGELOG.md — versioned history (Keep a Changelog)
- CONTRIBUTING.md — workflow, commit standards, PR rules

## Engineering law
- .specify/memory/constitution.md — 9 immutable principles

## Domain ground truth
- docs/domain/CMCOURIER_REBIRTH.md — full domain specification (RVI, CMIS, stages, metadata)

## Project planning
- docs/roadmap/POST-MVP.md — features deferred beyond MVP
- specs/<NNN>/ — per-change SDD artifacts (spec, plan, tasks)

## Reference data
- docs/samples/csv/ — sample CSVs (Modelo Documental, trigger lists, metadata sources)
- docs/samples/excel/RVILIB_RVABREP.xlsx — RVABREP table dump
- docs/samples/responses/EjemploRespuestaCMIS.txt — real CMIS response example

## How to use (recipes)
- (none yet — see docs/how-to/README.md)

## How it works (explanations)
- (none yet — see docs/explanation/README.md)
```

The INDEX is updated by every change that adds or moves a documentation artifact (the change's `tasks.md` includes a task to update it; CONTRIBUTING.md will document this responsibility).

### 13.6 Future evolution

- When the first tutorial is written (likely when `rvabrep-pipeline` ships end-to-end and we have a real walkthrough to give a new operator), create `docs/tutorials/` with its own README.md following the same pattern.
- When the CLI command surface stabilizes (post-MVP), create `docs/reference/` with a CLI command reference and a config schema reference.
- Each addition is documented in CHANGELOG.md and the INDEX.md.

---

## 14. Cross-References

- Spec: `specs/001-bootstrap-python-skeleton/spec.md`
- Tasks: `specs/001-bootstrap-python-skeleton/tasks.md`
- Constitution: `.specify/memory/constitution.md`
- REBIRTH §14.2 (Project Layout), §15 (Implementation Order)
- CONTRIBUTING.md (workflow conventions this change enforces via hooks)
- Diátaxis framework: https://diataxis.fr

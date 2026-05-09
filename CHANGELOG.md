# Changelog

All notable changes to CMCourier are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once code begins shipping.

> **Pre-implementation phase**: while no code has shipped yet, releases are tagged at meaningful documentation milestones (constitution ratification, architectural decisions, roadmap consolidation). Once the first MVP change merges, the project moves to standard SemVer.

---

## [Unreleased]

### Planned for next release

- Second implementation change (`002-domain-models-and-ports`): dataclasses for the domain (`TriggerRecord`, `RVABREPDocument`, `CMMapping`, `ResolvedMetadata`, `StagedFile`, `MigrationRecord`), abstract ports (`IDataSource`, `ITrackingStore`, `IAssembler`, `IUploader`, per-stage strategy interfaces), and the typed exception hierarchy under `src/cmcourier/domain/`.

---

## [0.3.0] — 2026-05-09

### Added

- **`pyproject.toml`** (PEP 621) declaring all runtime and dev dependencies per Constitution §Constraints, with major-version bounds on every package: `pydantic`, `click`, `pyodbc`, `requests`, `requests-toolbelt`, `pandas`, `img2pdf`, `Pillow`, `PyPDF2` (runtime); `pytest`, `pytest-cov`, `ruff`, `mypy`, `pre-commit`, `types-requests`, `pandas-stubs` (dev).
- **`src/cmcourier/`** in src layout (PEP 420) with hexagonal layering visible from day one: `domain/`, `adapters/{sources,tracking,assembly,upload}/`, `services/`, `orchestrators/`, `cli/{commands,ui}/`, `config/`. Every directory has an explicit `__init__.py` with a layer-purpose docstring.
- **`src/cmcourier/__init__.py`** exposes `__version__ = "0.0.0"`.
- **`src/cmcourier/cli/app.py`** Click group placeholder reserving the `cmcourier` binary entry point.
- **`tests/`** with `unit/{domain,services,orchestrators}/` and `integration/{adapters,pipeline}/` mirrors plus `conftest.py` (empty fixtures placeholder) and `tests/test_smoke.py` (asserts package imports and exposes a SemVer `__version__`).
- **`.pre-commit-config.yaml`** with ruff (lint + format), mypy on staged `src/cmcourier/` files, conventional-pre-commit on `commit-msg`, and a custom local hook (`scripts/hooks/no-co-authored-by.sh`) that blocks any commit message containing `Co-Authored-By` (Constitution Principle IX).
- **`scripts/hooks/no-co-authored-by.sh`** — executable Bash hook backing the rule above.
- **`.gitignore`** covering Python build/runtime artifacts, tooling caches, virtualenvs, IDE junk, and operational artifacts (`logs/`, `tmp/`, `staging/`, SQLite tracking files).
- **`.editorconfig`** with 4-space indent, LF endings, UTF-8, trim trailing whitespace, final newline; `*.md` exempt from trailing-space trim; `*.{yml,yaml,json,toml}` use 2-space indent.
- **`docs/INDEX.md`** — canonical map of every documentation artifact in the repository, organized by purpose per the Diátaxis framework. Updated by every change that adds or moves a doc.
- **`docs/how-to/README.md`** — index of how-to guides (problem-oriented "How to use"), with naming convention (`how-to/<task-slug>.md`) and an empty list at MVP start.
- **`docs/explanation/README.md`** — index of explanation documents (understanding-oriented "How it works"), with naming convention (`explanation/<concept-slug>.md`) and a pointer to the canonical domain explanation in REBIRTH.
- **README "Getting started"** section populated with prerequisites (including unixODBC-dev / IBM iSeries Access driver requirement for `pyodbc`), install / test / lint / type-check commands, env-var conventions, and a pointer to `docs/INDEX.md`.
- **README "Documentation map"** prominently links `docs/INDEX.md` as the canonical entry point.

### Changed

- README "Documentation map" expanded with rows for `docs/INDEX.md`, `docs/how-to/README.md`, `docs/explanation/README.md`.
- README "Status checklist" ticks the `/sdd-init` and Python-skeleton-bootstrap milestones.

### Rationale

- This change executes Phase 0 of the implementation order from `docs/domain/CMCOURIER_REBIRTH.md §15`, now under SDD discipline (spec / plan / tasks landed in commits `c908927` and `56a091c`; this commit ships the implementation).
- The skeleton holds **no business logic** — its only purpose is to give every subsequent change a working sandbox. The smoke test (`tests/test_smoke.py`) is the single proof that the scaffolding works: it asserts that `import cmcourier` succeeds and that `__version__` is a SemVer string.
- Pre-commit hooks enforce the constitutional rules from the first commit onward — Conventional Commits, no `Co-Authored-By` trailer, ruff lint + format, mypy on staged files. This is the moment the constitution stops being a document and starts being executable.
- Coverage threshold (80%) is configured but trivially passes on the empty skeleton. It becomes binding the moment the first real code lands.
- Documentation architecture follows the [Diátaxis framework](https://diataxis.fr): docs split by purpose (learn / solve / look up / understand) rather than by topic. We materialize only the two quadrants the user explicitly requested (`how-to`, `explanation`); `tutorials` and `reference` are deferred to natural-content moments per `specs/001-bootstrap-python-skeleton/plan.md §13`.

---

## [0.2.0] — 2026-05-08

### Added
- **`docs/domain/CMCOURIER_REBIRTH.md` §10 rewritten**: replaced the old "Execution Modes A/B/C" model with a stage-based pipeline architecture. Eight atomic stages (`S0`–`S7`) compose into named pipelines exposed as CLI commands.
- **`docs/domain/CMCOURIER_REBIRTH.md §10.5`**: Pre-Flight Validation specification. Automatic before any pipeline run; available as standalone `cmcourier doctor` command.
- **`docs/domain/CMCOURIER_REBIRTH.md §10.6`**: TUI by default with PREP / UPLOAD tabs (Rich); `cmcourier background` is the explicit headless exception.
- **`docs/domain/CMCOURIER_REBIRTH.md §10.7`**: Adaptive heavy / light upload lanes — design intent recorded, marked as post-MVP feature.
- **`docs/domain/CMCOURIER_REBIRTH.md §11`**: CLI surface restructured to match stage-based pipelines. `doctor`, pipelines as commands, `batch` and `inspect` subcommand groups.
- **`docs/domain/CMCOURIER_REBIRTH.md §17.4`**: Observability section expanded into five logging tiers (application, pipeline, network, system, slow-ops) with per-tier configuration toggles, bottleneck identification framework, PII discipline.
- **`docs/roadmap/POST-MVP.md`**: New exhaustive roadmap of nine deferred features (adaptive lanes, system metrics, log analysis tooling, AS400 tracking backend, AIMD auto-tuning, additional pipelines, multi-batch parallelism, per-batch bandwidth, cross-batch metadata cache) plus a watchlist. Each entry: intent, design, MVP placeholder, why deferred, acceptance criteria.
- **`README.md`**: project overview, status, documentation map, tech stack, project workflow, status checklist.
- **`CONTRIBUTING.md`**: SDD workflow, branching, conventional commits, PR standards, constitutional amendment procedure pointer.
- **`CHANGELOG.md`**: this file.

### Changed
- **Configuration schema (`§12` of REBIRTH)**: removed the global `datasource_mode` field. Trigger source is selected by which pipeline command is invoked, not by a config flag.

### Rationale
- The user surfaced a list of design changes that the rewrite should adopt: pipelines as composable stages, modes as commands rather than config, an explicit `doctor` command, TUI everywhere except background, batch-as-first-class with two-batch producer-consumer flow, stage-by-stage execution per batch, exhaustive observability, validatable mapping/metadata configurations.
- Document Class Mapping (`S2`) was promoted to a separate stage from Metadata Resolution (`S3`) so missing mappings and missing metadata produce distinct error classes — better diagnosis, better doctor output.
- The adaptive heavy/light lane design was explicitly deferred to post-MVP after a viability vs complexity trade-off review. Single-lane MVP delivers correct results; adaptive lanes deliver faster results.

---

## [0.1.0] — 2026-05-08

### Added
- **`.specify/memory/constitution.md`** ratified at v1.0.0 with nine core principles:
  - I. Hexagonal Architecture is Non-Negotiable
  - II. Idempotency is Sacred
  - III. No God Objects — Decompose by Responsibility
  - IV. Streaming Over Buffering
  - V. Config is the Single Source of Truth
  - VI. Real Test Pyramid (AS400 is not mocked)
  - VII. Spec Before Code
  - VIII. Data Sensitivity is Non-Negotiable
  - IX. Concepts Over Code, Verify Over Assume
- Constraints section: Python 3.11+, Pydantic v2, Click, pyodbc, requests + requests-toolbelt, pandas, img2pdf + Pillow + PyPDF2, SQLite (WAL), pytest, ruff, mypy.
- File and directory conventions per GitHub Spec Kit (`.specify/memory/`, `specs/<NNN-feature-slug>/`).
- Governance section: amendment procedure with SemVer (MAJOR/MINOR/PATCH), enforcement, document precedence chain.
- Project structure under `docs/domain/` (REBIRTH ground truth) and `docs/samples/{csv,excel,responses}/` (reference fixtures from RVIMigration).

### Moved
- `CMCOURIER_REBIRTH.md` → `docs/domain/CMCOURIER_REBIRTH.md` (preserved as git rename).
- `*.csv`, `*.xlsx`, `EjemploRespuestaCMIS.txt` → `docs/samples/{csv,excel,responses}/` (preserved as git renames).

### Rationale
- The old project (`RVIMigration`) drifted into a 1341-line God Object without immutable principles guiding the work. The constitution exists so the rewrite does not repeat that history.
- Spec Kit was chosen over OpenSpec for file-based, git-versioned SDD artifacts.

---

## How to read this changelog

- **Added**: new functionality or documentation
- **Changed**: existing behavior or documentation modified
- **Deprecated**: behavior or feature on its way out
- **Removed**: behavior or feature deleted
- **Fixed**: bug fixes
- **Security**: security-relevant changes
- **Moved**: file relocations (preserved as git renames where possible)
- **Rationale**: the *why* behind a release, when not obvious from the entries above

Pre-1.0.0 versions are documentation milestones. 1.0.0 will mark the first production-ready MVP migration.

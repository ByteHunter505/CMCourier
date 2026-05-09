# Changelog

All notable changes to CMCourier are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once code begins shipping.

> **Pre-implementation phase**: while no code has shipped yet, releases are tagged at meaningful documentation milestones (constitution ratification, architectural decisions, roadmap consolidation). Once the first MVP change merges, the project moves to standard SemVer.

---

## [Unreleased]

### Planned for next release

- Third implementation change (`003-csv-data-source-adapter`): the first concrete `IDataSource` implementation backed by pandas + CSV files. Foundation for the CSV trigger pipeline and the per-source metadata fixtures used by tests of higher layers.

---

## [0.4.0] — 2026-05-09

### Added

- **`cmcourier.domain.models`** — frozen dataclasses (`@dataclass(frozen=True, slots=True)`) for `TriggerRecord`, `RVABREPDocument`, `CMMapping`, `ResolvedMetadata`, `StagedFile`, and `MigrationRecord`. The `StageStatus` enum (subclassing `enum.StrEnum` from Python 3.11) encodes the per-stage state machine from REBIRTH §10.3 with values matching member names so persistence layers can store them directly. Module-level helpers `parse_cymmdd`, `is_pdf_filename`, `compute_cm_folder`, and `compute_cm_object_type` live alongside the models because they are intrinsic to model semantics (REBIRTH §3.3, §3.4, §4.2).
- **`cmcourier.domain.ports`** — abstract interfaces `IDataSource`, `ITrackingStore` (with stage-aware methods `is_stage_done`, `mark_stage_pending`, `mark_stage_done`, `mark_stage_failed`, plus the cross-batch `is_uploaded` idempotency anchor), `IAssembler`, `IUploader`, and `S0Strategy` (the new abstraction for the four trigger source modes from REBIRTH §5.1). All declared as `abc.ABC` with `@abstractmethod` decorators. Concrete implementations land in 003+.
- **`cmcourier.domain.exceptions`** — typed hierarchy rooted at `CMCourierError`, organized by stage (`TriggerError` S0, `IndexingError` S1 with `RVABREPNotFoundError` / `RVABREPDeletedError` / `RVABREPDuplicateError`, `MappingError` S2 with `IDRViNotMappedError`, `MetadataError` S3 with `SourceFailedError` / `DefaultValidationFailedError`, `AssemblyError` S4 with `SourceFileMissingError` / `PDFAssemblyFailedError`, `UploadError` S5 with `CMISClientError` / `CMISServerError` / `RetriesExhaustedError`, `TrackingError` S6) plus `ConfigurationError`. Every concrete subclass carries explicit named context parameters (`txn_num`, `id_rvi`, `batch_id`, etc.) for structured logging per Constitution Principle VIII.
- **`cmcourier.domain.__init__`** re-exports every public name (35 symbols) so callers write `from cmcourier.domain import IDataSource` regardless of which submodule the symbol lives in. `__all__` is alphabetized.
- **`tests/unit/domain/test_models.py`**, **`test_ports.py`**, **`test_exceptions.py`**, **`test_imports.py`** — 112 unit tests covering construction, validation rejection, frozen-ness, computed properties, helper edge cases (CYYMMDD round-trip, the REBIRTH §4.2 example, etc.), abstract-class semantics, exception hierarchy filtering, structured-context surfacing in `str(exc)`, and complete `__all__` re-export coverage.

### Verification

- `pytest -m unit -v tests/unit/domain/`: **112 / 112 pass** in 0.17 s.
- `pytest --cov=src/cmcourier/domain`: **98.56 % branch coverage** (target ≥ 95 %).
- `mypy src/cmcourier/`: clean across 18 source files with strict mode applied to `domain/`, `services/`, `orchestrators/`.
- `ruff check src/ tests/`, `ruff format --check`: clean.
- `pre-commit run --all-files`: ruff, ruff-format, and mypy hooks all pass.

### Rationale

- Provides the stable contract that every adapter (003+) and service (004+) will build against. Without this layer, no concrete code can be written without inventing types ad-hoc.
- All dataclasses are `frozen=True, slots=True` to make accidental mutation impossible and to keep per-instance memory footprint small at scale (200 000+ records in flight is plausible per REBIRTH §10.4).
- Exceptions carry structured context for downstream PII-safe logging in the observability layer (REBIRTH §17.4) without relying on message parsing.
- Constitution Principle I held throughout: zero third-party imports inside `src/cmcourier/domain/`. The only non-stdlib dependencies in test files are `pytest` itself.

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

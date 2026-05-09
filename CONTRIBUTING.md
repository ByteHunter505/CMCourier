# Contributing to CMCourier

This document explains the workflow for contributing to CMCourier. Read it before opening a PR. The rules are not negotiable — they are derived from the [project constitution](.specify/memory/constitution.md).

---

## Mental model

CMCourier is built with **Spec-Driven Development**. The shape of every contribution is:

```
Constitution → Spec → Plan / Design → Tasks → Code → Verify → Archive
```

You do not write code first and document later. You define the contract, then implement against it. **Skipping phases is not "moving fast"** — it is incurring debt that will be paid in confusion.

If this feels heavy: read the [REBIRTH document](docs/domain/CMCOURIER_REBIRTH.md). The previous tool was built bottom-up and ended as a 1341-line God Object. SDD is the antidote.

---

## Before you start

1. **Read the [constitution](.specify/memory/constitution.md)**. Nine principles. None are decorative. Specs and code that violate them are rejected without debate.
2. **Read the [REBIRTH document](docs/domain/CMCOURIER_REBIRTH.md) for any domain you are touching**. The CMIS quirks, the AS400 driver behavior, the CYYMMDD date format, the file naming convention — they were learned the hard way and are documented.
3. **Check the [post-MVP roadmap](docs/roadmap/POST-MVP.md)**. If your idea is already there, you have most of the design done.
4. **Check the [CHANGELOG](CHANGELOG.md)** for recent changes that may affect your work.

---

## SDD workflow

CMCourier uses **GitHub Spec Kit** conventions for SDD artifacts.

### Artifact locations

```
.specify/
├── memory/
│   └── constitution.md          # Ratified engineering law
└── amendments/                   # Constitutional amendments (each numbered)
    └── NNN-amendment-slug.md

specs/
└── NNN-feature-slug/             # One folder per change
    ├── spec.md                   # The what (requirements, scenarios, acceptance)
    ├── plan.md                   # The how (architecture, libraries, decomposition)
    ├── tasks.md                  # The implementation checklist
    ├── research.md               # Optional, for non-obvious investigations
    └── data-model.md             # Optional, for changes that touch persistence
```

Numbering is **append-only**: never reuse a slot.

### Phase responsibilities

| Phase | Artifact | Reads | Writes | Goal |
|-------|----------|-------|--------|------|
| Specification | `spec.md` | Constitution, REBIRTH | requirements + scenarios | Establish the contract |
| Plan / Design | `plan.md` | spec | architecture + decomposition | Establish the approach |
| Tasks | `tasks.md` | spec + plan | implementation checklist | Make implementation mechanical |
| Code | source under `src/` and `tests/` | tasks + spec + plan | actual code | Implement |
| Verify | `verify-report.md` (or transient) | spec + tasks + code | validation report | Confirm spec was met |
| Archive | `archive-report.md` | all artifacts | summary + cross-refs | Close the change |

### Test discipline

The constitution's Principle VI is unconditional:

- Unit tests mock the **ports** (interfaces in `domain/ports.py`), exercise services and orchestrators in isolation, run in <30s in CI.
- Integration tests use **real** adapters: SQLite (file or in-memory), CSV, Alfresco in Docker for CMIS.
- **AS400 / DB2 is NOT mocked**. The `CSVDataSource` adapter covers all dev/test needs.
- End-to-end tests run against staging IBM CM before any production migration.

If you find yourself writing a test that asserts the behavior of a mock, delete the test and write an integration test against a real adapter.

### Strict TDD

When the project's `sdd-init` indicates Strict TDD Mode, every implementation task follows the **Red → Green → Refactor** loop:

1. Write a failing test that captures the requirement.
2. Run the test, confirm it fails for the expected reason.
3. Write the minimum code to make it pass.
4. Run the test, confirm it passes.
5. Refactor while green.

Do not write production code without a failing test pointing at it. Strict TDD is not optional in this mode.

---

## Branching

- Branch per change, named after the change slug: `feat/<feature-slug>` or `fix/<bug-slug>` or `docs/<doc-slug>`.
- Branch from `main`, merge to `main` via PR.
- Never push to `main` directly.

---

## Commit messages

**Conventional Commits** only. The full list of types:

- `feat:` — a new feature (user-visible behavior)
- `fix:` — a bug fix
- `docs:` — documentation only
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `test:` — adding or fixing tests
- `chore:` — build, tooling, dependencies
- `perf:` — performance improvements
- `ci:` — CI / CD changes

### Hard rules

- **No `Co-Authored-By` lines**. No AI attribution. Authorship is the human.
- **No `--no-verify`**. Pre-commit hooks are not optional.
- **Atomic commits**. One logical change per commit.
- **Imperative mood in subject** ("add metadata cache", not "added metadata cache").
- **Subject ≤72 characters**. Body explains *why*, diff explains *what*.
- **Body wrapped to ~72 columns** for readability.

### Example

```
feat: add doctor command with mapping completeness check

Validate that every ID RVI in the upcoming batch has a mapping in
the Modelo Documental before any pipeline run starts. Without this
check, a missing mapping surfaces as a per-document failure during
S2, scattering errors across the batch instead of failing fast.

The check is invoked automatically in pre-flight; the standalone
`cmcourier doctor --check mapping` runs the same logic for ad-hoc
operator triage.

Closes specs/003-doctor-command/.
```

---

## Pull request standards

A PR is rejected at review if any of the following is true:

- It adds code without a corresponding spec under `specs/<NNN-feature-slug>/` (Constitution Principle VII).
- It violates the SRP test of Constitution Principle III, or exceeds the 50-line function cap.
- It introduces external dependencies in `domain/` (Principle I).
- It logs PII at INFO level or below (Principle VIII).
- It mocks AS400 or DB2 (Principle VI).
- Its commit messages are not Conventional Commits, or include `Co-Authored-By` lines.
- The PR title exceeds 70 characters or fails to summarize the change.

A passing PR includes:

- Title summarizing the change in <70 characters
- Body linking to the relevant spec, listing test evidence (which tests pass, what was exercised), noting any constitutional exceptions invoked
- All CI checks green (lint, type, unit tests, integration tests where applicable)
- Updated `CHANGELOG.md` under `[Unreleased]` describing the change
- For features: updated `docs/how-to/` if user-facing behavior changed

---

## Constitutional amendments

The constitution can change, but only through the procedure in its [`Governance` section](.specify/memory/constitution.md#governance):

1. Write a proposal in `.specify/amendments/<NNN-amendment-slug>.md` describing the principle change, the rationale (preferably a real incident, not a hypothetical), and the migration plan for code that violates the new rule.
2. Bump the constitution version per SemVer (MAJOR / MINOR / PATCH for governance docs).
3. The amendment commit updates `Version`, `Last Amended`, and the affected sections atomically.

Do not edit the constitution directly. Edit through an amendment proposal.

---

## Reviewer posture

- The reviewer's job is to enforce the constitution. The author's job is to make enforcement easy.
- "Looks good to me" is not a review. Specific, falsifiable observations are reviews.
- When the constitution is silent, the reviewer and author negotiate. When the constitution speaks, the constitution wins.
- Push back on PRs that bypass SDD. Stand firm on PRs that mock AS400. Be ruthless about PII in logs.

---

## Pre-commit hooks

Once `pyproject.toml` lands, the project will install pre-commit hooks for:

- `ruff format` — formatting
- `ruff check` — lint
- `mypy --strict` on `domain/`, `services/`, `orchestrators/`
- Conventional Commit lint on commit message
- Unit test fast-suite on staged files (best effort)

Hooks are not optional. If a hook fails, fix the cause, re-stage, and create a new commit. Never `--no-verify`. Never `--amend` to bypass a hook (Constitution / Git Safety Protocol).

---

## Where to ask questions

- **Domain question** → re-read `docs/domain/CMCOURIER_REBIRTH.md` first. If still unclear, open an issue tagged `domain` with the section reference.
- **Architecture question** → re-read `docs/domain/CMCOURIER_REBIRTH.md §10` (stages) and `§14` (architecture). Then constitution Principle I.
- **Process question** → re-read this file, then constitution `§Workflow Discipline`.
- **Stuck on an SDD phase** → search engram for similar phases of past changes; if none, open an issue tagged `process`.

---

## Final note

This project exists because the previous one drifted off the rails when discipline lapsed. Every rule above is a guardrail learned from a real incident. They feel heavy until the first time they save you from a bad merge. Hold the line.

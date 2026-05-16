# CMCourier Constitution

**Version**: 1.0.0
**Ratified**: 2026-05-08
**Last Amended**: 2026-05-08
**Status**: Active

> This document is the supreme law of the CMCourier project. Specs, designs, tasks, and code that violate any principle herein are rejected — not debated. Amendments require the procedure defined in §Governance.

---

## Preamble

CMCourier is a rewrite of `RVIMigration`, a tool that migrates documents from a legacy IBM RVI system on AS400 to IBM Content Manager via the CMIS REST API. The original tool worked but suffered from architectural drift: a 1341-line God Object, broken `run()` method, tangled responsibilities. This constitution exists so that history does not repeat itself.

This constitution is the **ground truth for the engineering discipline**. Domain interpretation lives in the active specs under `specs/` and in the working code under `src/cmcourier/`.

---

## Core Principles

### I. Hexagonal Architecture is Non-Negotiable

The codebase is organized as **Ports & Adapters**. Four layers, with strict dependency direction:

```
CLI → Orchestrators → Services → Domain ← Adapters
```

**Rules**:
- `domain/` contains models, ports (abstract interfaces), and exceptions. **Zero external dependencies.** Pure Python stdlib only. No `requests`, no `pyodbc`, no `pandas`, no `pydantic` — nothing.
- `adapters/` implement the domain ports. They are the only place I/O lives (network, disk, database).
- `services/` contain business logic and depend on ports, never on adapters.
- `orchestrators/` coordinate services. They contain no business logic and no direct I/O.
- `cli/` injects dependencies. It does not contain business logic.

**Rationale**: The original `pipeline.py` mixed CMIS HTTP calls, SQLite writes, AS400 queries, threading, and business rules in a single file. Testing was impossible without spinning up the entire ecosystem. Hexagonal architecture is the antidote: each layer is independently testable and replaceable.

**How to apply**: When you catch yourself importing `requests` in a service, or instantiating an adapter inside business logic, stop. Refactor through a port.

---

### II. Idempotency is Sacred

Every migration must be safely re-runnable. Interrupted, restarted, retried — the system must never produce a duplicate upload to Content Manager.

**Rules**:
- `rvabrep_txn_num` is **the** idempotency key. It carries a `UNIQUE` constraint at the persistence layer.
- Before processing any document, the tracking store must be consulted. If the document is in `UPLOADED` status, it is skipped — no re-resolution, no re-assembly, no re-upload.
- Failed records may be retried only by transitioning `FAILED → PENDING` explicitly (via `retry-failed` command).
- Status transitions follow the state machine defined in the tracking store domain model. No shortcuts.

**Rationale**: The system runs against a corporate AS400 over a corporate network with corporate firewalls. Things break. A migration of 200,000 documents that re-uploads on retry destroys storage budgets and audit trails.

**How to apply**: Any new persistence operation must answer two questions: "What happens if this runs twice?" and "What happens if this is interrupted halfway?" If you cannot answer both, the operation is not ready.

---

### III. No God Objects — Decompose by Responsibility

Single Responsibility Principle is the law. The real test is **responsibility**, not **length**.

**Rules**:
- **A function may not exceed 50 lines.** Hard limit, no exceptions. A function longer than 50 lines never has a single responsibility — split it.
- **The SRP test for files and classes**: if you cannot describe its purpose in one sentence without using the word "and", it has more than one responsibility. Split it.
- **Soft tripwires** (not caps): files trend under **400 lines**, classes trend under **200 lines**. When you exceed these, the question is not "did I break the rule?" — it is "is this complexity *forced* by the domain or *invented* by my design?". If invented, refactor. If forced (e.g., the CMIS adapter has many legitimate quirks that belong together), document the reason in a file-top docstring and move on.
- The 1341-line `pipeline.py` from RVIMigration is the canonical anti-pattern. The bug was not "1341 lines is too many" — it was "twelve responsibilities pretending to be one".

**Rationale**: Hard caps on files and classes punish honest complexity (legitimate adapter quirks) while letting badly designed small classes pass review. They generate ceremonial exception documents that nobody reads. Functions are different: an operation with twelve steps is twelve operations, not one — that's why the 50-line cap on functions stays absolute.

**How to apply**: Before adding code to a file, ask "does this share a reason to change with what's already here?" If yes, it belongs — regardless of current size. If no, it goes elsewhere — even if the file is short.

---

### IV. Streaming Over Buffering

The system handles documents that may exceed several hundred megabytes. Buffering is forbidden where streaming is possible.

**Rules**:
- PDF assembly uses `img2pdf.convert(list_of_paths)` — never load image bytes into memory then concatenate.
- CMIS uploads use `requests-toolbelt` `MultipartEncoder` with file handles — never `requests.post(data=open(...).read())`.
- Database iteration uses cursor-based streaming where the adapter supports it (e.g., `query_stream` for AS400).
- Trigger lists are iterated, never fully loaded into memory.

**Rationale**: A 540-page TIFF document can exceed 500 MB once decoded. Twenty workers each buffering one such document is 10 GB of RAM consumed for no reason. Production hosts do not have 10 GB to spare.

**How to apply**: Any new code that reads a file or a network resource must default to streaming. Buffering must be justified in the PR description.

---

### V. Config is the Single Source of Truth

There is exactly one configuration file: `config/config.yaml`. It is validated at startup by Pydantic. Credentials are loaded from environment variables only.

**Rules**:
- No code reads environment variables directly except in `config/env.py` (the env override module).
- No code hardcodes hosts, paths, ports, table names, column names, or property IDs.
- No code constructs CMIS property names (`clbNonGroup.BAC_*`) inline. They live in `cmis.property_catalog`.
- Schema validation runs at process start. Invalid config fails fast with a clear error.

**Rationale**: The bank operates multiple environments (dev, staging, prod) with different AS400 hosts, different CM repos, different mapping tables. Hardcoded values mean a typo deploys to production. Centralized config means one file changes per environment.

**How to apply**: Before writing `os.getenv` or `os.environ[...]` in any module other than `config/env.py`, stop. Add the field to the Pydantic schema and the YAML.

---

### VI. Real Test Pyramid

Tests exist to give us confidence to ship, not to inflate coverage numbers.

**Rules**:
- **Unit tests** mock the ports (interfaces in `domain/ports.py`) and exercise services and orchestrators in isolation. They are fast (full unit suite < 30 seconds) and run in every CI build.
- **Integration tests** use real adapters: real SQLite (file or in-memory), real CSV files, real Alfresco in Docker for CMIS. They run on demand and in nightly CI.
- **AS400 / DB2 is NOT mocked.** The `CSVDataSource` adapter covers all dev/test needs that do not require real AS400 behavior. AS400 testing happens against staging, where the ODBC driver behavior matters.
- **Alfresco** validates the CMIS Browser Binding contract: session warmup, multipart structure, folder creation, retry paths. It does not validate IBM-specific quirks (`$t!-2_BAC_*v-1`, `clbNonGroup.BAC_*`).
- **End-to-end tests** against the real IBM CM run in staging, before any production migration.

**Rationale**: Mocking AS400 with pyodbc behavior simulators is a tarpit. Either you test the simulator (worthless) or you discover that real AS400 does not behave like the simulator (devastating). The CSV adapter is a real adapter that exercises the same domain ports — if it works against CSV, the bug is in AS400-specific code, where staging catches it.

**How to apply**: When writing a new test, ask: "Is this exercising business logic, or is this exercising my mock?" If the latter, delete the test and write an integration test against a real adapter.

---

### VII. Spec Before Code

CMCourier is built with **Spec-Driven Development**. No implementation begins without an approved spec.

**Rules**:
- The flow is: **Constitution → Spec → Plan → Tasks → Code → Verify**.
- A spec describes the **what** (requirements, scenarios, acceptance criteria). A plan describes the **how** (architecture, libraries, decomposition). Tasks are the implementation checklist.
- Specs and plans live under `specs/<NNN-feature-slug>/` per **GitHub Spec Kit** convention. Constitution and SDD memory live under `.specify/memory/`. Both are file-based and git-versioned.
- A change must have a proposal before a spec, a spec before a plan, a plan before tasks, tasks before code.
- Skipping phases is not "moving fast" — it is incurring debt that will be paid in confusion.

**Rationale**: The original `RVIMigration` was built bottom-up: someone wrote `pipeline.py`, then bolted on a CLI, then bolted on tracking, then bolted on the 3-phase mode. Each layer compromised the previous. SDD inverts the flow: define the contract, then implement against it.

**How to apply**: When tempted to "just quickly write a function" without a spec, stop. Either the function fits within an existing spec (in which case the existing spec governs it) or it does not (in which case write the proposal first).

---

### VIII. Data Sensitivity is Non-Negotiable

CMCourier handles **bank customer data**: CIF numbers, customer names, account and card numbers, signed authorizations, and transaction documents. Mishandling this data is not a code review issue — it is a regulatory and ethical one.

**Rules**:
- **No PII in default logs.** CIF, customer names, account numbers, card numbers, and full file paths are masked at `INFO` level and below. They surface only at `DEBUG`, behind an explicit `--debug-pii` flag, and only to local rotated log files — never to stdout/stderr in production.
- **No credentials in git.** Ever. No real `username` / `password` in committed YAML — credentials arrive exclusively through the reserved environment variables. No secrets in test fixtures, commit messages, or PR descriptions.
- **No PII in committed test fixtures.** Sample data under `docs/samples/` and `tests/fixtures/` is synthetic or anonymized. If a real-looking CIF, name, or account number ends up in git, it is replaced — no exceptions, no "fix in next commit".
- **Errors do not leak data to humans.** Exception traces written to log files may include domain identifiers (we need them for debugging). Messages displayed to operators, surfaced in TUIs, or returned in CLI output strip identifiers and replace them with masked tokens (`CIF=***456`).
- **Audit trail is preserved.** The tracking store records *what* was migrated, *when*, and *with what outcome*. This data is retained for the regulatory window the bank specifies. Tracking records are not deleted casually.

**Rationale**: We migrate banking documentation. A leak of CIFs paired with names is a regulatory incident. A leak of account numbers is worse. The tool runs inside a corporate network, but logs end up in tickets, screenshots, Slack channels, and bug reports. Mask at the source — by the time you remember to mask, the data is already in three other systems.

**How to apply**: Before any `log.info(...)`, `print(...)`, or error message that includes a domain variable, ask "would I paste this into a public ticket?" If no, mask it. Centralized masking helpers in `cli/ui/logging.py` (forthcoming) implement this — use them, do not hand-roll regex per call site.

---

### IX. Concepts Over Code, Verify Over Assume

This is a discipline principle, applicable to everyone touching the codebase — human or agent.

**Rules**:
- Understand the domain concept before writing the function. If you cannot explain in one sentence what `BAC_CIF` represents and where it comes from, you are not ready to resolve it.
- Verify technical claims before stating them. "Dejame verificar" beats "claro que sí" every single time.
- When the user appears to be wrong, explain *why* with evidence — code, docs, behavior — not opinion.
- When you discover you were wrong, acknowledge with proof, not with apology.
- AI is a tool. The human leads. Code generated by an agent without comprehension is technical debt at the speed of light.

**Rationale**: The previous codebase contains bugs that originated from copy-pasting code without understanding it (`scan_and_resolve` inserted mid-method; non-existent column `preprocessed_at` in a SQL UPDATE). Concepts-first prevents this class of bug entirely.

**How to apply**: Before writing code, write a one-sentence explanation of what the code does and why. If the sentence sounds vague, the code is not ready.

---

## Constraints

### Technology Stack

The following choices are settled. Substitutions require constitutional amendment.

| Concern | Choice |
|---------|--------|
| Language | Python 3.11+ |
| Config validation | Pydantic v2 |
| CLI framework | Click |
| AS400 driver | pyodbc + iSeries Access ODBC Driver |
| HTTP client | requests + requests-toolbelt (MultipartEncoder) |
| CSV reading | pandas |
| PDF assembly | img2pdf (fast path) + Pillow + PyPDF2 (fallback) |
| Tracking store | SQLite (WAL mode), AS400 (alternative backend) |
| Tests | pytest + pytest-cov |
| Formatting | ruff (lint + format) |
| Type checking | mypy (strict on `domain/`, services/`, orchestrators/`) |
| Packaging | pyproject.toml (PEP 621) |

### Environment Variables (Reserved)

These names are reserved for credential injection. No other use is permitted.

- `AS400_USERNAME`, `AS400_PASSWORD`
- `CMIS_USERNAME`, `CMIS_PASSWORD`

### File and Directory Conventions

- Source code under `src/cmcourier/`. Single importable package.
- SDD specs / plans / tasks under `specs/<NNN-feature-slug>/`. Constitution and SDD memory under `.specify/memory/`. Both follow **GitHub Spec Kit** conventions.
- Domain knowledge documents under `docs/domain/`.
- Sample data and reference files under `docs/samples/`.
- Test fixtures under `tests/fixtures/`. Never under `docs/`.
- Logs under `./logs/` (gitignored).
- Temp staging under system temp, never under repo root.

---

## Workflow Discipline

### Spec-Driven Development Cycle

```
specification → plan → tasks → implementation → verification → archive
```

Each phase produces a single, named artifact under `specs/<NNN-feature-slug>/` (`spec.md`, `plan.md`, `tasks.md`, plus `research.md` and `data-model.md` when needed). Each artifact is reviewable in isolation.

### Branching and Commits

- Branch per change, named after the change slug (e.g., `feat/metadata-prefetch`).
- **Conventional Commits** only. `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- **No `Co-Authored-By` lines.** No AI attribution in commits. Authorship is the human.
- Commits are atomic. One logical change per commit.
- The commit message body explains the *why*. The diff explains the *what*.

### Pull Request Standards

- A PR title summarizes the change in <70 characters.
- A PR body links to the relevant spec, lists test evidence, and notes any constitutional exceptions invoked.
- A PR that adds code without an approved spec is rejected at review (Principle VII).
- A PR that violates the SRP test of Principle III (single responsibility per file / class / function), or exceeds the 50-line function cap, is rejected at review.

### Code Review Posture

- The reviewer's job is to enforce this constitution. The author's job is to make enforcement easy.
- "Looks good to me" is not a review. Specific, falsifiable observations are reviews.
- When the constitution is silent on a question, the reviewer and author negotiate. When the constitution speaks, the constitution wins.

---

## Governance

### Authority

This constitution governs CMCourier and only CMCourier. It does not bind the user's other projects, the original `RVIMigration` codebase, or any external dependency.

### Amendment Procedure

A constitutional amendment requires:

1. **A written proposal** in `.specify/amendments/<NNN-amendment-slug>.md` describing:
   - The principle being added, modified, or removed
   - The rationale (typically a real incident, not a hypothetical)
   - The migration plan for any code that violated the new rule
2. **A version bump** following SemVer for governance docs:
   - **MAJOR** — backward-incompatible principle removal or redefinition (e.g., abandoning hexagonal architecture)
   - **MINOR** — new principle added, or material expansion of an existing principle
   - **PATCH** — clarifications, typo fixes, non-semantic rewording
3. **The amendment commit** updates `Version`, `Last Amended`, and the affected sections atomically.

### Enforcement

- Each SDD phase agent (specs, design, tasks, apply, verify) reads this constitution at start and refuses outputs that violate it.
- The `sdd-verify` phase explicitly checks implementation against constitutional principles, not only against the spec.
- The user retains final veto over enforcement decisions.

### Precedence

When documents conflict, the order of precedence is:

1. **This Constitution** (absolute, only overridden by amendment)
2. **The active Spec** (governs a specific change)
3. **The active Plan / Design** (governs implementation approach)
4. **Existing code** (governs nothing — code is the output of the above, not the input)

---

## Closing

The original tool was written without a constitution. It worked for a while, then it didn't, and the cost of fixing it exceeded the cost of rewriting it. CMCourier exists because we paid that price once. This constitution exists so we do not pay it again.

— *Ratified for the rewrite, 2026-05-08.*

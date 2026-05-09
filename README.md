# CMCourier

> Document migration tool for moving banking documentation from the legacy IBM RVI system on AS400 into IBM Content Manager via CMIS.

**Status**: Bootstrap — constitution and architecture are ratified, MVP implementation has not started.

CMCourier is a complete rewrite of the older `RVIMigration` tool. The rewrite is **green-field code-wise** and **brown-field domain-wise**: the business rules, integration quirks, file formats, and data sources are well understood and documented. The architecture and engineering discipline are starting fresh under hexagonal design and Spec-Driven Development.

---

## What this repository contains right now

```
CMCourier/
├── .specify/
│   └── memory/
│       └── constitution.md          # Ratified engineering law (v1.0.0)
│
├── docs/
│   ├── domain/
│   │   └── CMCOURIER_REBIRTH.md     # Domain ground truth (1300+ lines)
│   ├── roadmap/
│   │   └── POST-MVP.md              # Everything deferred beyond the MVP
│   └── samples/
│       ├── csv/                     # Reference CSVs from the old project
│       ├── excel/                   # RVABREP table dump (xlsx)
│       └── responses/               # Real CMIS response fixture
│
├── README.md                        # This file
├── CHANGELOG.md                     # Project history (Keep a Changelog format)
└── CONTRIBUTING.md                  # SDD workflow, commit standards, PR rules
```

No source code yet. The skeleton (`src/cmcourier/`, `tests/`, `pyproject.toml`, etc.) lands with the first implementation change.

---

## Documentation map

Read these in order if you are picking up the project cold.

| Document | Read when | Purpose |
|----------|-----------|---------|
| [`README.md`](README.md) | First | What the project is, current status, where to look for what |
| [`.specify/memory/constitution.md`](.specify/memory/constitution.md) | Before writing anything | The 9 immutable engineering principles. Spec, design, code that violates these is rejected |
| [`docs/domain/CMCOURIER_REBIRTH.md`](docs/domain/CMCOURIER_REBIRTH.md) | Before writing anything domain-related | The full domain context: source system (RVI/AS400), target system (CMIS/Content Manager), file formats, metadata resolution, CMIS integration quirks, stage architecture |
| [`docs/roadmap/POST-MVP.md`](docs/roadmap/POST-MVP.md) | When asking "did we forget X?" | Every feature deferred beyond MVP, with intent + design + acceptance criteria |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Before opening a PR | SDD workflow, commit rules, PR standards |
| [`CHANGELOG.md`](CHANGELOG.md) | Anytime | Versioned history of every meaningful change to the project |

---

## What CMCourier will do

End to end:

1. **Discover** documents to migrate via one of several trigger sources (CSV, AS400 query, RVABREP filter, local folder scan).
2. **Index** each trigger against the RVABREP master table on AS400.
3. **Map** each document's RVI type code to a Content Manager document class (folder + object type + required metadata fields).
4. **Resolve** metadata for each document via a configurable fallback chain over multiple sources.
5. **Assemble** the final PDF (merge multi-page TIFFs to a single PDF, or pass through native PDFs).
6. **Upload** to Content Manager via the CMIS Browser Binding REST API with proper metadata.
7. **Track** every document so re-runs are idempotent.

The full design is described in [`docs/domain/CMCOURIER_REBIRTH.md`](docs/domain/CMCOURIER_REBIRTH.md).

---

## Architecture in one paragraph

**Hexagonal Architecture (Ports & Adapters)** with four layers: `domain` (pure Python, no external deps), `services` (business logic depending only on ports), `orchestrators` (thin coordinators), `adapters` (concrete implementations of ports — pyodbc for AS400, requests for CMIS, pandas for CSV, SQLite for tracking, img2pdf/Pillow for PDF assembly). Pipelines are **named compositions of atomic stages** (`S0`–`S7`), each pipeline a CLI command, never a config flag.

See Constitution Principle I and `CMCOURIER_REBIRTH.md §10` for details.

---

## Tech stack

Settled by Constitution. Substitution requires constitutional amendment.

- **Language**: Python 3.11+
- **Config**: Pydantic v2 (validated at startup)
- **CLI**: Click
- **AS400**: pyodbc + iSeries Access ODBC Driver (thread-local connections)
- **HTTP**: requests + requests-toolbelt (`MultipartEncoder` for streaming uploads)
- **CSV**: pandas
- **PDF assembly**: img2pdf (fast path) + Pillow + PyPDF2 (fallback)
- **Tracking**: SQLite (WAL mode), AS400 alternative (post-MVP)
- **Testing**: pytest + pytest-cov
- **Lint / format**: ruff
- **Type check**: mypy (strict on `domain/`, `services/`, `orchestrators/`)
- **Packaging**: pyproject.toml (PEP 621)

---

## Getting started

The MVP has not been built yet. Once the implementation phase begins, this section will document:

- How to install dependencies (`pip install -e .[dev]` once `pyproject.toml` exists)
- How to set required environment variables (`AS400_USERNAME`, `AS400_PASSWORD`, `CMIS_USERNAME`, `CMIS_PASSWORD`)
- How to run the test suite (`pytest`)
- How to run the doctor command against your environment (`cmcourier doctor`)
- How to run the first migration end-to-end

For now: read the constitution and the domain doc. Understanding comes first; code comes second (Constitution Principle IX).

---

## Project workflow

CMCourier follows **Spec-Driven Development** under the GitHub Spec Kit conventions. Briefly:

```
Constitution (immutable filter)
        ↓
Specification (the what — requirements, scenarios, acceptance criteria)
        ↓
Plan / Design (the how — architecture, libraries, decomposition)
        ↓
Tasks (the implementation checklist)
        ↓
Code (implement against the spec)
        ↓
Verify (validate against constitution + spec)
```

No code lands without a spec. No spec contradicts the constitution. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full workflow.

---

## Status checklist

- [x] Constitution ratified (v1.0.0)
- [x] Project structure laid out
- [x] Domain ground truth documented (`CMCOURIER_REBIRTH.md`)
- [x] Stage-based pipeline architecture defined (`§10`)
- [x] Pre-flight validation defined (`§10.5`)
- [x] Observability tiers defined (`§17.4`)
- [x] Post-MVP roadmap captured
- [ ] SDD context registered (`/sdd-init`)
- [ ] First change: Python skeleton bootstrap
- [ ] First change: MVP `rvabrep-pipeline` end-to-end
- [ ] Real-data dry run against staging
- [ ] First production migration

---

## License

To be defined by the project owner. Until then, treat this repository as proprietary; do not distribute without permission.

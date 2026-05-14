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

The canonical entry point is **[`docs/INDEX.md`](docs/INDEX.md)** — a single page that maps every documentation artifact in the repo. Below is a quick-access cheat sheet for the most common reads.

| Document | Read when | Purpose |
|----------|-----------|---------|
| [`docs/INDEX.md`](docs/INDEX.md) | **Anytime** | Canonical map of all documentation, organized by purpose (Diátaxis-inspired) |
| [`README.md`](README.md) | First | What the project is, current status, where to look for what |
| [`.specify/memory/constitution.md`](.specify/memory/constitution.md) | Before writing anything | The 9 immutable engineering principles. Spec, design, code that violates these is rejected |
| [`docs/domain/CMCOURIER_REBIRTH.md`](docs/domain/CMCOURIER_REBIRTH.md) | Before writing anything domain-related | The full domain context: source system (RVI/AS400), target system (CMIS/Content Manager), file formats, metadata resolution, CMIS integration quirks, stage architecture |
| [`docs/roadmap/POST-MVP.md`](docs/roadmap/POST-MVP.md) | When asking "did we forget X?" | Every feature deferred beyond MVP, with intent + design + acceptance criteria |
| [`docs/how-to/README.md`](docs/how-to/README.md) | When you need to *do* something | Index of recipes (problem-oriented). Empty at MVP start; grows as commands ship |
| [`docs/explanation/README.md`](docs/explanation/README.md) | When you need to *understand* something | Index of explanations (understanding-oriented). Pairs with the canonical domain explanation in REBIRTH |
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

### Prerequisites

- **Python 3.11 or newer** (CMCourier is verified on 3.11 and 3.12).
- **A C compiler and ODBC headers** — required by `pyodbc`:
  - **Linux** (Debian/Ubuntu): `sudo apt install build-essential unixodbc-dev`
  - **macOS**: `brew install unixodbc`
  - **Windows**: install the [IBM iSeries Access ODBC Driver](https://www.ibm.com/support/pages/ibm-i-access-client-solutions) (the driver itself ships its own SDK).
- **Git**.

### Install (editable, with development tooling)

```bash
git clone <repo> CMCourier
cd CMCourier
python3 -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate            # Windows
pip install -e .[dev]
pre-commit install
pre-commit install --hook-type commit-msg
```

### Run the smoke test

```bash
pytest                             # all tests
pytest -m unit                     # only unit tests
pytest -m integration              # only integration tests
pytest -m "not slow"               # skip slow tests
```

### Lint, format, type-check

```bash
ruff check src/ tests/             # lint
ruff format src/ tests/            # auto-format
ruff format --check src/ tests/    # CI-style check (no writes)
mypy src/cmcourier/                # type-check (strict on inner layers)
```

### Pre-commit hook bypass

You don't bypass pre-commit hooks. If a hook fails, fix the cause and create a new commit. Never `--no-verify` (Constitution / Git Safety Protocol).

### Required environment variables (when running real migrations)

Credentials live in the environment, never in committed YAML (Constitution Principle V & VIII):

```bash
export AS400_USERNAME="..."
export AS400_PASSWORD="..."
export CMIS_USERNAME="..."
export CMIS_PASSWORD="..."
```

A real `config/config.yaml` and a working CLI command lands in subsequent changes. For now, the CLI prints its help message:

```bash
cmcourier --help
```

For the architecture, the domain context, and the roadmap: read the [docs/INDEX.md](docs/INDEX.md). Understanding comes first; code comes second (Constitution Principle IX).

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
- [x] SDD context registered (`/sdd-init`)
- [x] First change: Python skeleton bootstrap
- [x] Second change: domain models, ports, exceptions
- [x] Third change: first concrete adapter (Tabular CSV+XLSX data source)
- [x] Fourth change: first service (MappingService over Modelo Documental)
- [x] Fifth change: MetadataService (fallback chain + CIF self-healing)
- [x] Sixth change: S0 trigger strategies (CSV + direct_rvabrep + stubs)
- [x] Seventh change: SQLite tracking store (idempotency + per-stage state)
- [x] Eighth change: IndexingService (S1 — RVABREP lookup)
- [x] Ninth change: PdfAssembler (S4 — img2pdf + Pillow/PyPDF2 fallback)
- [x] Tenth change: CmisUploader (S5 — CMIS Browser Binding + retry policy + bandwidth limiter)
- [x] Eleventh change: CsvTriggerPipeline orchestrator (S0..S6 end-to-end, library) — **MVP pipeline complete**
- [x] Twelfth change: CLI + Pydantic config + YAML loader — **MVP CLI usable end-to-end**
- [x] Thirteenth change: `cmcourier doctor` pre-flight (REBIRTH §10.5)
- [x] Fourteenth change: AS400 adapter + rvabrep-pipeline + as400-trigger-pipeline — **multi-pipeline + AS400 production-ready**
- [x] Fifteenth change: AS400 metadata sources (closes the 014 gap)
- [x] Sixteenth change: local-scan-pipeline (4th production pipeline; REBIRTH §5.1 set complete)
- [x] Seventeenth change: single-doc-pipeline (REBIRTH §10.2 diagnostic — CLI-driven one-shot)
- [x] Eighteenth change: per-source AS400 query override (closes the 015 scale gap)
- [x] Nineteenth change: adapter port-hygiene cleanup (every adapter now declares its port)
- [x] Twentieth change: observability tiers 1-4 (REBIRTH §17.4) — JSON app log + pipeline + network + slow-ops
- [x] Twenty-first change: operator CLI essentials (REBIRTH §11) — batch list/show/retry-failed + inspect rvabrep/mapping + as400-query
- [x] Twenty-second change: pipeline safety flags — auto-doctor + --resume + doctor --check
- [x] Twenty-third change: complete REBIRTH §11 menus — inspect trigger / mapping-stats + batch export-report
- [x] Twenty-fourth change: background runner — cron-friendly entry point with per-config fcntl lock
- [x] Twenty-fifth change: live two-tab TUI + S5 worker pool + AIMD auto-tune (REBIRTH §10.6, §17.4)
- [x] Twenty-sixth change: tier-5 system metrics (POST-MVP §2 — psutil sampling, ~0.1% CPU cost)
- [x] Twenty-seventh change: offline log analyzer `cmcourier analyze batch/compare/trends` (POST-MVP §3)
- [x] Twenty-eighth change: multi-batch orchestrator with N=2 producer-consumer overlap (POST-MVP §7, N=2)
- [x] Twenty-ninth change: shared `BandwidthLimiter` token bucket — `cmis.max_bandwidth_mbps` is now the real global cap
- [x] Thirtieth change: TUI multi-batch view — new `CHUNKS` tab + live recorder binding
- [x] Thirty-second change: shell auto-completion (`cmcourier completion bash|zsh|fish`)
- [x] Thirty-third change: Tier 1 polish — `--total <N>` flag + CI integration docs for `analyze`
- [x] Thirty-fourth change: AS400 NIARVILOG distributed idempotency (POST-MVP §4 — toggleable, retry/backoff, `cmcourier sync resolve` CLI)
- [x] Thirty-fifth change: mapping CSV split (`MapeoRVI_CM.csv` + `MetadatosCM.csv` + `CMISType` column — production format; consolidated mode stays for tests)
- [x] Thirty-sixth change: adaptive heavy/light upload lanes (POST-MVP §1 — default off, `LaneSplitter` + `LaneController` + drain-driven rebalance + dual TUI sub-panels)
- [x] Thirty-seventh change: cross-batch `document_cache` table (POST-MVP §9 — default off, SQLite-backed, TTL-aware, `cmcourier cache stats|clear` CLI)
- [x] Thirty-eighth change: CMIS connection pool sizing + eager warm-up (POST-MVP §10.2 — `HTTPAdapter pool_maxsize`, `warm_connection_pool(n)` pre-S5)
- [x] Thirty-ninth change: CMIS `object_type_id` override (via `mapping.cmis_type`) + staging dry-run scaffolding (Alfresco-in-Docker + runbooks)
- [x] Fortieth change (038): CMIS target pre-flight + upload payload trace — `CMISFolder` + `CMISPropertyId` columns; `doctor --check cm-targets` (folders + properties); `IUploader.verify_folder_exists` (read-only); `s5_upload_attempt` / `s5_upload_failed` events with PII masking + `observability.unmask_pii` toggle
- [x] Forty-first change (039): synthetic RVABREP CSV generator — `cmcourier mock rvabrep` streams a seed-deterministic CSV at any scale (chains into `mock generate` for file materialization)
- [x] Forty-second change (040): Alfresco CMIS compatibility — `repo_id=""` semantics + mime-property heuristic + JSON formatter allowlist + doctor `cmis_type` override; live smoke against Alfresco 23.x ships 0 failures end-to-end
- [x] Forty-third change (041): TUI quality-of-life pass — clean dashboard (stderr handler is detached when Textual owns the terminal), UPLOAD tab adds MB-uploaded/MB-planned + per-chunk wall-clock + avg MB/s + ETA, CHUNKS tab becomes a per-stage breakdown table with TOTAL aggregate row
- [x] Forty-fourth change (042): TUI multi-batch metric isolation — per-batch `_BandwidthHandler` filter (no more byte bleed across overlapping chunks), live `s5_done`/`s5_failed` propagated into CHUNKS row during UPLOAD (no more stuck `0/0/0`), separate `upload_recorder()` slot in `MultiBatchOrchestrator` so UPLOAD-tab S5 percentiles aren't disturbed by PREP-side recorder flips
- [x] Forty-fifth change (043): AIMD auto-tune sees real p95 in multi-batch mode — `AutoTuneController.set_p95_provider` swap hook + orchestrator wires the upload-active recorder so the elastic-protection property is restored (pre-043 the controller observed `p95=0` always and only grew workers, never decreased)
- [x] Forty-sixth change (044): robust resume after kill -9 mid-S5 — `_apply_resume` detects `S{N}_DONE → S{N+1}` stage gaps (workers paused mid-batch no longer abandon as "clean"), `--batch-id` always threads through (operator-named batches honored without `--resume`), explicit `--from-stage` wins over auto-detection
- [x] Forty-seventh change (045): idempotent S5 upload on 409 conflict — `CmisUploader.upload` recovers from kill-race orphans (doc in Alfresco, missing from migration_log) by looking up the existing `cmis:objectId` via the folder-children endpoint; closes the last `S5_FAILED` window after a real `kill -9`
- [x] MVP: `rvabrep-pipeline` end-to-end
- [ ] Real-data dry run against staging
- [ ] First production migration

---

## License

To be defined by the project owner. Until then, treat this repository as proprietary; do not distribute without permission.

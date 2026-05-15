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
- [x] Forty-eighth change (046): polymorphic `Trigger` model — each pipeline emits its natural trigger shape (`ClientTrigger` for csv / single-doc / as400, `RvabrepRowTrigger` for rvabrep-direct, `LocalScanTrigger` for local-scan); S1 dispatches per subtype, so local-scan now uploads exactly the files in the scan pool (no more "1 file → all client docs" over-expansion)
- [x] Forty-ninth change (047): persist `cm_object_id` on `S5_DONE` — `mark_stage_done` now writes the CMIS objectId into `migration_log` so the tracking DB can answer "what's the objectId of doc X?" without a children-walk against CMIS
- [x] Fiftieth change (048): pluggable RVABREP source — `indexing.source` becomes a discriminated union (`kind: csv` ↔ `kind: as400`); `rvabrep-pipeline` serves both (CSV file vs. live AS400 query returning an RVABREP-shaped table), the standalone `as400-trigger-pipeline` command and `trigger.kind: as400` are removed (AS400 is a *source* choice, not a trigger kind)
- [x] Fifty-first change (049): configurable NIARVILOG column names — `tracking.as400_sync.columns` maps the 15 logical NIARVILOG fields to per-environment physical names (symmetric to `indexing.columns`); all configurable identifiers (`columns.*`, `library`, `table`) are now validated as DB2 identifiers, closing the SQL-interpolation surface
- [x] Fifty-second change (050): streaming trigger pipeline — triggers stream in `batch_size` chunks instead of being materialized whole; peak memory is `O(batch_size × batches_in_flight)` not `O(total)`, so the ~20M-row production RVABREP migration no longer OOMs (defeated four materialization points: `_run_overlapped`'s `list()`, the monolithic N=1 path, `TabularDataSource.get_all`, and `--total`)
- [x] Fifty-third change (051): "filtered at S1" is a first-class outcome — delete-coded RVABREP rows were silently dropped at S1 with zero traceability; now `_enrich_known_row` raises `RVABREPDeletedError`, `_stage_s0_s1` counts it as `filtered` (not failed, not a silent drop) with a per-doc log, and `s1_filtered` surfaces in the headless summary + TUI PREP/CHUNKS tabs
- [x] Fifty-fourth change (052): CHUNKS tab — live rates, frozen timer, drill-down — per-chunk `MB/s·docs/s` throughput column; the run timer now freezes at completion instead of counting up forever; a new DETAIL tab (`[` / `]` chunk cursor, `d` to view) lists every doc of a chunk (name/size/status/reason), read on demand from the tracking store so memory stays bounded
- [x] Fifty-fifth change (053): stage-aware bottleneck classifier — `cmcourier analyze batch` now leads with the per-stage breakdown (the batch-exact signal it previously ignored): a stage holding ≥45% of total stage time *is* the bottleneck, and the verdict names whether it is INSIDE the program (`assembly/metadata/mapping/indexing/trigger-bound`) or OUTSIDE it (`upload-bound` — the CMIS server + network); `LogReader` associates the un-tagged `network-*`/`system-*` tiers by the batch's time window instead of an absent `batch_id`, so `network_summary`/`system_summary` are no longer always empty
- [x] Fifty-sixth change (054): UPLOAD-tab recorder wiring — finishes the 042 PREP/UPLOAD recorder split: `bandwidth_current/peak/series` + `slow_ops_all` now read the UPLOAD-side recorder (pre-054 they read the PREP recorder, which on N=2 runs sees none of the uploading chunk's `cmis_upload` events → 0 bandwidth, blank sparkline, no slow ops); the per-chunk UPLOAD timer measures from `upload_started_monotonic` (S5 start) instead of `prep_started_monotonic`, so "chunk elapsed" and `avg_mbps` reflect the actual upload window
- [x] Fifty-seventh change (055): network events carry the `batch_id` — the root cause behind the dead UPLOAD tab: `CmisUploader._emit_network` never set `batch_id`, so the per-batch `_BandwidthHandler` / `_SlowOpHandler` (which filter on it) silently dropped *every* `cmis_upload` event in *every* recorder since spec 042; `IUploader.upload` now takes a required `batch_id` keyword and threads it through `_post_with_retries` → `_emit_network` (+ the `s5_upload_attempt`/`s5_upload_failed` diagnostic events), so bandwidth/peak/sparkline/slow-ops finally receive data
- [x] Fifty-eighth change (056): configurable prep workers — `processing.prep_workers` sizes a fixed `ThreadPoolExecutor` for the prep stages S2 (mapping), S3 (metadata) and S4 (assembly), which ran one document at a time on a single thread; default `1` is byte-identical to before, `pool.map` keeps the survivor list in input order, and S0/S1 stay serial by design (they carry the cross-batch idempotency + resume logic). No AIMD/lanes/bandwidth machinery — just a thread count
- [x] Fifty-ninth change (057): size the S5 thread pool to the AIMD ceiling — the upload `ThreadPoolExecutor` was created with `max_workers=cmis.workers` (fixed), so the AIMD-resized `ResizableSemaphore` could never exceed the initial count: `pool_in_use` stayed pinned at `cmis.workers` while the TUI's capacity climbed, and the auto-tune knob was disconnected from the engine; the pool (both `_stage_5_single` and the dual heavy/light pair) is now sized to `_pool_ceiling()` = `auto_tune.max_threads`, so the semaphore/lane controller becomes the effective limiter — unchanged when AIMD is off
- [x] Sixtieth change (058): DETAIL tab fixes — (a) the per-doc `size` column always read `—` because `file_size_bytes` was never persisted: the row was first INSERT-OR-IGNORE'd in S1 (when `item.staged_file` was still `None`) and the S4 INSERT was silently ignored, so the column stayed NULL forever; a new `ITrackingStore.record_staged_file_metadata` UPDATEs the row after S4 assembles, idempotent so resume runs also backfill; (b) the DETAIL pane was wrapped in a plain `Container` that crops overflow instead of scrolling — now a `VerticalScroll` with `#detail_body { height: auto }` and `_MAX_ROWS` raised to 2000, so chunks larger than the visible height read past the fold
- [x] Sixty-first change (060): HTTP client migrated from `requests` to `httpx[http2]` — `CmisUploader` now negotiates HTTP/2 via ALPN, so the N concurrent S5 workers share a single TCP connection (Apache-fronted Alfresco in prod), dropping small-upload overhead; transparent fallback to HTTP/1.1 when the server doesn't advertise h2 (Tomcat-direct staging), so behaviour is unchanged there; 56 adapter integration tests migrated from `responses` to `respx`
- [x] Sixty-second change (061): AIMD `min_samples` guard — the controller halved the worker pool a few seconds into the first chunk because the nearest-rank p95 with ~5 samples was dominated by a single cold-connection outlier; new `cmis.auto_tune.min_samples` config (default 20) short-circuits the decision to a new `insufficient_data` action when too few samples have accumulated, leaving workers/timeout untouched until the observation is trustworthy
- [x] Sixty-third change (062): persist S1 filtered + cross-batch-skipped docs to `migration_log` — two new `StageStatus` values (`S1_FILTERED`, `S1_SKIPPED`) + a `mark_stage_terminal` port method, so the DETAIL tab / `analyze batch` / `cmcourier batch show` can identify which specific docs were filtered (delete-coded at source, spec 051) or skipped cross-batch (REBIRTH §10 idempotency); §10's "silent skip" contract intentionally reversed for traceability
- [x] Sixty-fourth change (063): streaming orchestrator (core, single-lane) — new `processing.mode: "batched" | "streaming"` selects the orchestrator; `"streaming"` runs a continuous producer-consumer pipeline driven by a bounded **bucket** (`processing.streaming.bucket_size`, default 100) between PREP (S1–S4 producers, sized by `prep_workers`) and S5 consumers (sized to `_pool_ceiling()`). Memory peak collapses to `bucket_size` (independent of total trigger count) and S5 never idles waiting for a chunk's PREP. Resume is rejected in streaming mode — re-run + 062's `S1_SKIPPED` rows provide traceability. Heavy/light lanes (036) and a real TUI BUCKET tab are deferred to 065 / 064
- [x] Sixty-fifth change (064): TUI BUCKET tab for streaming mode — new `b` keybind opens a dedicated tab showing bucket level vs cap (ASCII bar), peak level since run start, 5s sliding-window throughput on PREP + S5, producer in-flight count, configured worker totals, and cumulative `S5_DONE` / `S5_FAILED` / `S1_FILTERED` / `S1_SKIPPED`. The orchestrator exposes a `streaming_snapshot()` reader and a `_ThroughputWindow` (deque+lock) feeds the rates. Batched mode is unchanged — the BUCKET tab prints a one-line stub pointing at CHUNKS
- [x] Sixty-sixth change (065): heavy/light lanes in streaming mode — combining `processing.mode: "streaming"` with `heavy_light_lanes.enabled: true` now inserts a dispatcher thread between the main bucket and S5: it routes each item into a heavy or light per-lane queue by `staged_file.size_bytes >= heavy_threshold_bytes`, and each lane gets its own consumer pool gated by the existing `LaneController` (semaphore split + drain-driven rebalance from 036). The BUCKET tab gains a LANES sub-block showing heavy/light budget, busy, queue depth, and total budget. Eliminates head-of-line blocking caused by a single heavy doc starving lighter ones queued behind it
- [x] Sixty-seventh change (066): S4 PDF assembly in `ProcessPoolExecutor` — diagnosed `prep_workers: 16` running at < 5 docs/s aggregate because the GIL serializes `img2pdf`/`PIL`/`PyPDF2` work. New default-on `processing.s4_use_processes: true` dispatches `assemble()` to a process pool sized by `s4_max_processes` (default `os.cpu_count()`), bypassing the GIL completely. `spawn` context (not `fork`) avoids the deadlock risk of a multi-threaded parent. `SourceFileMissingError` / `PDFAssemblyFailedError` got `__reduce__` so they round-trip cleanly across the worker boundary. Expect ~Nx speedup for S4-dominated runs
- [x] MVP: `rvabrep-pipeline` end-to-end
- [ ] Real-data dry run against staging
- [ ] First production migration

---

## License

To be defined by the project owner. Until then, treat this repository as proprietary; do not distribute without permission.

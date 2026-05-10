# Changelog

All notable changes to CMCourier are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once code begins shipping.

> **Pre-implementation phase**: while no code has shipped yet, releases are tagged at meaningful documentation milestones (constitution ratification, architectural decisions, roadmap consolidation). Once the first MVP change merges, the project moves to standard SemVer.

---

## [Unreleased]

### Planned for next release

- First MVP orchestrator wiring S0..S6 together. With S5 (CMIS upload) now in place, ALL adapters and services for the `rvabrep-pipeline` command are real — no more stubs to plan around. The next change is the orchestrator + CLI command + tracking integration.

---

## [0.12.0] — 2026-05-10

### Added

- **`cmcourier.adapters.upload.cmis_uploader.CmisUploader`** — concrete `IUploader` for IBM Content Manager via the CMIS Browser Binding REST/JSON protocol (REBIRTH §8). Single-threaded MVP: one `requests.Session` shared across calls; thread-local sessions deferred to a follow-up change when the orchestrator's worker pool lands. Holds an in-memory `set[str]` folder cache so a verified or created folder path is never re-POSTed within a process lifetime.
- **Lazy JSESSIONID warmup** (REBIRTH §8.2): no HTTP at construction time; the first call to `test_connection`, `ensure_folder`, or `upload` issues `GET {base_url}/{repo_id}?cmisselector=repositoryInfo`. Re-warmup fires on any 401 from a subsequent POST.
- **Recursive idempotent folder creation** (REBIRTH §8.3): `ensure_folder(path)` walks segments left-to-right, skips any segment starting with `$` (system folders like `$type`), and POSTs `createFolder` to the parent for the rest. HTTP 409 (Conflict) is treated as success; the resulting path is still added to the cache. Re-invocation after a successful walk issues zero HTTP calls.
- **Streaming multipart upload** (REBIRTH §8.5) via `requests-toolbelt.MultipartEncoder`. The file is read from disk on demand by the encoder; the adapter never calls `.read()` on the whole stream. Property bag is laid out as `propertyId[N] / propertyValue[N]` pairs in insertion order, with three fixed slots for `cmis:objectTypeId`, `cmis:name`, `cmis:contentStreamMimeType` (the first three triples) and then the caller's `properties` mapping appended starting at index 3.
- **`cmcourier.adapters.upload.cmis_uploader.BandwidthLimiter`** (REBIRTH §8.6) — token-bucket file-stream wrapper with `read`, `seek`, `tell`, `close`, `name`, `__enter__`, `__exit__`. `mbps <= 0` disables throttling (read passthrough). Positive `mbps` throttles to `mbps * 1_000_000` bytes per second via a `time.monotonic()` refill loop. Passthrough methods are required so `MultipartEncoder` introspection works.
- **Complete retry policy** (REBIRTH §8.7): HTTP 201/2xx → success; HTTP 401 → re-warmup + retry exactly once (a second 401 raises `CMISClientError(status_code=401)`); HTTP 4xx (other) → fail-fast `CMISClientError`; HTTP 5xx → exponential backoff (`retry_base_delay_s * 2**(attempt-1)`, capped at 60 s), up to `retry_max_attempts`; `requests.exceptions.ConnectionError` whose message contains `"10053"` (Windows abort) → `ERROR` log + doubled sleep; retry budget exhausted → `RetriesExhaustedError(txn_num, attempts)` with the last `CMISServerError` as `__cause__`. 409 is handled as success ONLY in `_create_folder_segment`, never in the generic post path.
- **Three-path `cmis:objectId` parser** (REBIRTH §8.8): `succinctProperties["cmis:objectId"]` → `properties["cmis:objectId"]["value"]` → `str(data.get("id", "unknown"))`. Each fallback is reachable from a real IBM response shape variant. Unparseable JSON returns `"unknown"`.
- **`cmcourier.adapters.upload.cmis_uploader.CmisConfig`** — frozen+slots dataclass with `base_url`, `repo_id`, `username`, `password`, `timeout_seconds=300.0`, `verify_ssl=False`, `max_bandwidth_mbps=0.0`, `retry_max_attempts=3`, `retry_base_delay_s=2.0`.
- **26 integration tests** in `tests/integration/adapters/test_cmis_uploader.py` across 9 groups: config, warmup, `test_connection`, `ensure_folder` (skip `$`, recursive, cache, 409, cached-after-409), upload happy path (3 objectId fallbacks + Content-Type assertion), retry (5xx-then-201, 4xx fail-fast, 401 re-warmup, retries exhausted), Windows-10053 (delay doubling + ERROR log), BandwidthLimiter (throttle + passthrough + passthrough methods), logging discipline. Branch coverage on `cmis_uploader.py`: **94%** (target ≥ 85%).

### Changed

- `src/cmcourier/adapters/upload/__init__.py` re-exports `BandwidthLimiter`, `CmisConfig`, `CmisUploader`.
- **`pyproject.toml`** dev deps add `responses>=0.25,<1.0` for HTTP mocking. `responses` is the dev-only library that lets the integration tests exercise the real `requests` stack with the network stubbed — Constitution Principle VI's "no mocking the SUT" applies; `responses` mocks the network, not `requests`.

### Verification

- `pytest -v`: **314 / 314 pass** in ~36 s (288 from earlier changes + 26 new).
- `pytest --cov=src/cmcourier`: total branch coverage **96.21%**; `adapters/upload/cmis_uploader.py` at **94%**.
- `ruff check`, `ruff format --check`: clean (one `PTH123` lint nudged `open(...)` to `path.open(...)` during verification).
- `mypy --strict on cmcourier.*`: clean across 29 source files.
- `pre-commit run --all-files`: ruff (legacy alias), ruff format, mypy all pass.

### Rationale

- **Stage S5 closes the adapter set** for the MVP `rvabrep-pipeline`. With S0 (triggers), S1 (indexing), S2 (mapping), S3 (metadata), S4 (assembly), S5 (upload), and S6 (tracking) all real, the next change is the orchestrator — every adapter it cables will be production code, not a stub.
- **MVP includes BandwidthLimiter and complete retry policy** (per user direction). Skipping these to ship the adapter faster would mean either a noticeable production retry hole or a flaky first-week dry-run on shared corporate networks. The retry policy is the most heavily-tested area of the adapter precisely because its failure modes are silent and expensive.
- **Single-threaded MVP** (also per user direction): the adapter holds ONE `requests.Session`. REBIRTH §8.2's "per thread" note becomes load-bearing only when the orchestrator wants worker pools; refactoring to `threading.local()` is a focused, ~10-line change in a follow-up. Shipping it now would mean test fixtures and async patterns we'd be designing around a hypothetical orchestrator instead of a real one.
- **`responses` chosen over `requests-mock`**: same author surface, but `responses` integrates as a pytest fixture / context manager rather than monkey-patching `requests.adapters`. The result is a flat top-down test reading: register stubs → run code → inspect calls. The `responses.add_callback` API also lets us inspect the multipart `Content-Type` boundary without parsing the body.
- **`requests-toolbelt.MultipartEncoder` is non-negotiable**. Loading a 540-page TIFF into memory before POSTing is the production failure mode REBIRTH §8.5 explicitly warns against. The encoder reads the file stream on demand and computes content-length without buffering. Test 4.13 asserts the request header rather than the body bytes because `responses` does not faithfully reproduce multipart wire bytes anyway.
- **409 lives in `_create_folder_segment`, not in `_post_with_retries`**: making the generic retry path treat 409 as success would mask conflicts on document creation (where 409 means a real cmis:name collision, not idempotency). Locality of decision-making beats DRY here.
- **`assert last_exc is not None` before `RetriesExhaustedError(...) from last_exc`** is intentional. `mypy --strict` cannot prove the loop entered, so the assertion satisfies both the type checker and a future reader. The assertion is reachable only if `retry_max_attempts >= 1` (configured default 3); a misconfiguration `retry_max_attempts=0` falls through to the assert as a `AssertionError` — that is acceptable behavior, distinct from a runtime upload failure.
- **Logging discipline (Constitution VIII)**: retry / warn / error logs carry `txn_num`, `attempt`, `status_code`, and `folder_path` via the `extra` dict; no property values, no response bodies beyond a 1024-char truncation. `TestLoggingDiscipline` verifies that a `clbNonGroup.BAC_CIF` value containing the sentinel `BAC_VALUE_THAT_MUST_NOT_LEAK_999999` never appears in any log record across an entire retry cycle.

---

## [0.11.0] — 2026-05-10

### Added

- **`cmcourier.adapters.assembly.pdf_assembler.PdfAssembler`** — concrete `IAssembler` for Stage S4 (REBIRTH §7). Dispatches on `RVABREPDocument.is_pdf`: native PDFs pass through via `shutil.copy2` to `{temp_dir}/{txn_num}.pdf` with `page_count` read from `doc.total_pages` (we trust RVABREP, do not parse the PDF); paged documents are glob-discovered, sorted by `int(extension)` to handle variable padding (REBIRTH §3.4), and merged via `img2pdf.convert` (fast path) with a `PIL.Image` + `PyPDF2.PdfMerger` fallback for mixed-content edge cases.
- **`cmcourier.adapters.assembly.pdf_assembler.AssemblerConfig`** — frozen+slots dataclass exposing `source_root`, `temp_dir`, and `image_type_map` (defaults from REBIRTH §7.5 — `B → image/tiff`, `O → application/pdf`, `C → image/jpeg`).
- **OneDrive temp-dir trap** (REBIRTH §7.4): if `temp_dir` resolves to a `./tmp` variant (`tmp`, `./tmp`, `tmp/`, `.\\tmp`), the assembler diverts to `Path(tempfile.gettempdir()) / "cmcourier_tmp"` and creates the dir at construction time. Constants `_ONEDRIVE_TRAP_VARIANTS` and `_DIVERTED_DIR_NAME` live as module-level frozensets.
- **Page discovery semantics**: glob `FILECODE.*` in the source directory, filter to entries whose extension is purely numeric (`str.isdigit`), sort by `int(extension)`. The native PDF extension `.PDF` is excluded by the digit filter. Missing source dir or zero numeric pages raises `SourceFileMissingError(file_path=...)`. A discovered/expected mismatch emits a `WARNING` log naming `txn_num` + counts but does NOT raise — the filesystem is the source of truth.
- **Dual-path assembly**: img2pdf primary, Pillow + PyPDF2 fallback. The fallback opens each page via `PIL.Image`, converts to RGB if necessary (mode `1` TIFFs cannot save as PDF directly), writes each page as a single-page PDF into a `BytesIO`, and merges via `PdfMerger`. If both paths fail, the assembler raises `PDFAssemblyFailedError(txn_num=..., reason=...)` with the secondary exception as `__cause__`.
- **18 integration tests** in `tests/integration/adapters/test_pdf_assembler.py` across 9 groups: construction, native passthrough, paged happy path (TIFF + JPEG + variable padding + unrelated-PDF exclusion), page-count mismatch WARNING, source-files missing, fallback path (monkey-patched img2pdf), both-paths-fail, output validation (PyPDF2 reader inspection), logging discipline. Branch coverage on `pdf_assembler.py`: **98%** (target ≥ 90%).
- **`tests/integration/adapters/conftest.py`** — session-scoped autouse fixture generator using Pillow to materialize the binary fixtures (TIFF / JPEG / PDF) under `tests/fixtures/assembly/`. Idempotent (skips existing files). Generated binaries are gitignored.
- **`.gitignore`** updated with patterns for the generated assembly fixtures (`tests/fixtures/assembly/**/*.{pdf,PDF,tif,tiff,jpg,jpeg}` plus numeric-extension page files like `.001`, `.10`, `.540`).

### Changed

- `src/cmcourier/adapters/assembly/__init__.py` re-exports `PdfAssembler` and `AssemblerConfig`.

### Verification

- `pytest -v`: **288 / 288 pass** in ~33 s (270 from earlier changes + 18 new).
- `pytest --cov=src/cmcourier`: total branch coverage **96.55%**; `adapters/assembly/pdf_assembler.py` at **98%**.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean across 28 source files (the existing `img2pdf` / `PyPDF2` `ignore_missing_imports` blocks in `pyproject.toml` cover the new module's third-party imports).
- `pre-commit run --all-files`: ruff (legacy alias), ruff format, mypy all pass.

### Rationale

- **Stage S4 is self-contained** — filesystem only, no network, no AS400. With S4 shipping, the only remaining adapter for the MVP `rvabrep-pipeline` is S5 (CMIS upload). Tracking + service triangle + S0 strategies are all already in place.
- **Both assembly paths included in MVP** (per user direction): the Pillow/PyPDF2 fallback adds ~30 LOC and ~2 tests but exercises real `PIL` + `PyPDF2` code under a monkey-patched img2pdf, so the adapter is "fit for purpose" from v1 without leaving a half-shipped fallback to wire up later.
- **`page_count` comes from `doc.total_pages` for native PDFs, from the glob result for paged docs**. Parsing the native PDF would be extra IO with no business value — RVABREP is the authority for the document's intended page count, and the staged PDF is what we ship to CM regardless.
- **Page-count mismatch is a WARNING, not an error**. The filesystem is the source of truth. If a paged document has 540 pages claimed in RVABREP but only 539 on disk, the migration still ships 539 — refusing would block real production data. Operators see the WARNING in tier-2 logs and investigate offline.
- **OneDrive trap baked into the constructor** (not a callable utility) because misconfiguration here destroys throughput silently (locked files, retry storms). Catching it at construction surfaces the diversion immediately in startup logs; tier-3 ops can grep for `temp_dir` divergence.
- **Synthetic-fixture pattern** mirrors change 005 (xlsx generation in `tests/conftest.py`) — binary blobs stay out of git history; regeneration is sub-second and deterministic. This keeps repo size flat and avoids merge conflicts on opaque binaries.
- **PyPDF2 v3 deprecation warning** (`PyPDF2 is deprecated. Please move to the pypdf library instead.`) is acknowledged but accepted for now. A follow-up change can migrate to `pypdf` without touching the assembler's public API; the migration is a constitutional amendment of the `Constraints` section, not a domain change.

---

## [0.10.0] — 2026-05-10

### Added

- **`cmcourier.services.indexing.IndexingService`** — concrete Stage S1 (REBIRTH §10.1). Given a `TriggerRecord`, returns every non-deleted `RVABREPDocument` matching `(shortname, system_id)`. CIF is intentionally NOT a filter — CIF self-healing is the responsibility of Stage S3 (REBIRTH §6.5).
- **Two public APIs**: `find_documents(trigger) -> list[RVABREPDocument]` raises `RVABREPNotFoundError` / `RVABREPDeletedError` / `IndexingError`; `find_documents_batch(triggers) -> Iterator[(trigger, list)]` yields one pair per input trigger with empty lists on miss (silent — orchestrators decide semantics). Batched API chunks input into IN-list batches of 50 (REBIRTH §10.1) issuing one `get_by_fields_in` call per chunk.
- **`cmcourier.services.indexing.IndexingColumnsConfig`** — frozen+slots dataclass mapping adapter row keys onto `RVABREPDocument` fields. Defaults match REBIRTH §3.2 physical column names verbatim (`ABABCD`, `ABAACD`, `ABAANB`, `ABACST`, `ABAHCD` = id_rvi, …); tests override every column to the CSV fixture's friendly names.
- **Duplicate `txn_num` handling**: WARNING log + first-wins (mirrors MappingService's REBIRTH §4.3 precedent). No exception is raised. Production data quality issues surface in logs, not in the pipeline's error path.
- **Row coercion**: `creation_date` parses via `parse_cymmdd`; `last_view_date` of `'0'` or `''` becomes `None`; `total_pages` coerces to `int` with empty/`None` → `0`; every other field is `str()`-coerced defensively against pandas / pyodbc returning native ints.
- **22 unit tests** in `tests/unit/services/test_indexing.py` across 7 groups (construction, single-trigger, duplicates, batched, coercion, error wrap, logging). Branch coverage on `services/indexing.py`: **96%** (target ≥ 95%).
- **1 fixture CSV** under `tests/fixtures/services/rvabrep_index_sample.csv`: 15 synthetic rows covering vanilla multi-match, fully-deleted, mixed-deleted, duplicate txn_num, same-shortname-across-systems, `last_view_date='0'` / `''`, PDF and paged variants.

### Changed

- `src/cmcourier/services/__init__.py` re-exports `IndexingService` and `IndexingColumnsConfig` (alongside the prior 15 public symbols).
- **`cmcourier.domain.exceptions.RVABREPDeletedError`** amended from `(txn_num, delete_code)` to `(shortname, system_id, deleted_count)`. The exception's first real consumer (IndexingService) describes the SET case "every matching row is deleted", not "this specific record is deleted". `tests/unit/domain/test_exceptions.py` updated to assert the new shape. No production code uses the old signature.

### Verification

- `pytest -v`: **270 / 270 pass** in ~24 s (248 from earlier changes + 22 new).
- `pytest --cov=src/cmcourier`: total branch coverage **96.40%**; `services/indexing.py` at **96%**.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean across 27 source files.
- `pre-commit run --all-files`: ruff (legacy alias), ruff format, mypy all pass.

### Rationale

- **Closes the service triangle**. Mapping (S2, change 004), Metadata (S3, change 005), and now Indexing (S1) are the three services every CMCourier pipeline relies on. With this change, the next milestone is the first orchestrator that wires S0..S6 end-to-end.
- **CIF is NOT a filter here**. REBIRTH §6.5 makes CIF self-healing a Stage S3 responsibility — adding CIF to the WHERE clause would either reject legitimate documents (when the trigger's CIF is missing) or duplicate CIF resolution logic across two stages. Single source of truth wins.
- **Batched API yields empty on miss, not raises**. Single-trigger callers (single-doc pipeline, doctor command) want typed errors. Orchestrator callers want to keep processing the batch — a missing trigger becomes a tracking event, not an exception that aborts the iterator. The two APIs express the two semantics cleanly.
- **One `get_by_fields_in` per chunk, Python-side grouping by `(shortname, system_id)`**: triggers in the same chunk may have different `system_id`s, so passing `system_id` as a fixed filter would over-restrict. The over-fetch is bounded (cardinality of shortnames across systems is small in practice).
- **`RVABREPDeletedError` amendment is justified**: the exception's original `(txn_num, delete_code)` shape modeled a single-doc workflow that hadn't shipped. The set-semantic shape `(shortname, system_id, deleted_count)` matches the actual S1 use case where "every matching row is deleted" is the failure surface. The single-doc pipeline, when it lands, can introduce a separate exception (or extend this one additively) without churn.
- **Logging discipline (Constitution VIII)**: the WARNING for duplicate txn_num carries `shortname` and `duplicate_count` in `extra`, never the values of `cif` / `index2..6`. The test in `TestLoggingDiscipline` asserts that the CIF value `'456789'` from the duplicate fixture row never appears in any log record.

---

## [0.9.0] — 2026-05-10

### Added

- **`cmcourier.adapters.tracking.sqlite.SQLiteTrackingStore`** — concrete `ITrackingStore` over stdlib `sqlite3`. Two-connection model (sync reader + async writer daemon thread fed by a `queue.Queue`); WAL journal + `synchronous=OFF` + 64 MiB page cache + temp_store=MEMORY (REBIRTH §9.3); batched commits up to 500 writes or every 1 s (REBIRTH §9.4); cross-batch idempotency via the partial index `idx_migration_log_uploaded` on `rvabrep_txn_num WHERE status='S5_DONE'`; within-batch idempotency via the unique index `idx_migration_log_txn_batch` on `(rvabrep_txn_num, batch_id)` plus `INSERT OR IGNORE` on `mark_stage_pending`. `start_batch` is the only synchronous write (returns a UUID4 the caller needs immediately). `flush()` blocks on `queue.join()` for test determinism and orchestrators that need to read state they just wrote. `close()` is idempotent and drains pending writes.
- **`MigrationRecord.batch_id: str`** — new required field on the domain dataclass (`src/cmcourier/domain/models.py`) between `rvabrep_file_name` and `status`. Resolves a port inconsistency where `mark_stage_pending(record, stage)` had no way to know the record's batch — putting it on the record itself is cleaner than amending the port signature.
- **`tests/integration/adapters/test_sqlite_tracking_store.py`** — 25 integration tests against a real per-test SQLite file (no mocks; Constitution Principle VI) across 7 groups: schema, batch lifecycle, per-stage state machine, queries, lifecycle, error wrapping, and the writer's 500-row batch cap. `_make_record(batch_id, txn_num, **overrides)` helper at module level.
- **2 new unit tests** in `tests/unit/domain/test_models.py` covering the new `batch_id` field on `MigrationRecord` (default-value rejection + presence on construction). Existing `MigrationRecord` constructions in the file updated to pass `batch_id="batch-test-001"`.

### Changed

- `src/cmcourier/adapters/tracking/__init__.py` re-exports `SQLiteTrackingStore`.

### Verification

- `pytest -v`: **248 / 248 pass** in ~22 s (222 from earlier changes + 25 new integration tests + 1 new unit test on the new field; net +26).
- `pytest --cov=src/cmcourier`: total branch coverage **96.41 %**; `adapters/tracking/sqlite.py` at **92 %** (target ≥ 90 %).
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean across 26 source files.
- `pre-commit run --all-files`: ruff (legacy alias), ruff format, mypy all pass.

### Rationale

- Stage S6 (Tracking) is transversal — every pipeline depends on it. Without it, no orchestrator can resume after a crash, no `is_uploaded` skip-check is possible, and no per-stage retry can be scoped. This change ships the only tracking backend the MVP needs.
- **Two SQLite connections, one writer thread** is the lightest design that simultaneously meets the throughput target (REBIRTH §9.4 calls out a 200 000-document target on a single process) and respects SQLite's threading rules. WAL coordinates the two connections so a writer never blocks a reader. `synchronous=OFF` is acceptable because every operation is idempotent (Constitution Principle II) — a crashed batch is replayed, not corrupted.
- **`start_batch` is the only synchronous write** because the caller needs the UUID4 immediately to attach to records that flow into subsequent stages. Every other write is `enqueue + return` so orchestrators are not bottlenecked on disk.
- **Idempotency is encoded in the schema**, not in Python: the unique index on `(rvabrep_txn_num, batch_id)` lets `INSERT OR IGNORE` be the entire body of `mark_stage_pending`'s SQL; the partial index on `WHERE status='S5_DONE'` makes `is_uploaded` an O(1) read regardless of how many batches have run. Constitution Principle II is structural in this adapter.
- **`preprocess_staging` and `document_cache` tables are explicitly OUT OF SCOPE** for this change — the 3-phase pipeline and the cross-mode metadata cache that use them are deferred to post-MVP (`docs/roadmap/POST-MVP.md`). Shipping only the two tables the MVP actually needs avoids ALM debt later.
- **Logging discipline (Constitution Principle VIII)**: logs identify operational keys (`txn_num`, `batch_id`) but never field values; `error_message` bodies live in the DB but are never echoed back to logs.

---

## [0.8.0] — 2026-05-10

### Added

- **`cmcourier.services.triggers.csv.CsvTriggerStrategy`** — concrete `S0Strategy` over any tabular `IDataSource`. Validates required columns at first row; treats blank `CIF` as `None` (CIF self-healing in stage S3 covers it); skips rows with blank `shortname`/`system_id` with an INFO log of the count. Lazy iteration.
- **`cmcourier.services.triggers.direct_rvabrep.DirectRvabrepTriggerStrategy`** — concrete `S0Strategy` that scans RVABREP itself, with optional `RvabrepFilters(systems, document_types)`. Picks the smaller filter for the IN-list query and rejects the other in Python during iteration. Deduplicates `(shortname, system_id)` pairs (first occurrence wins, matching REBIRTH §4.3 / MappingService precedent).
- **`cmcourier.services.triggers.stubs.{As400TriggerStrategy, LocalScanTriggerStrategy}`** — concrete `S0Strategy` placeholders. Constructor succeeds; `acquire()` raises `NotImplementedError` with messages naming the missing dependency. Same late-fail pattern used for `as400:<alias>` in 005.
- **3 frozen+slots config dataclasses**: `CsvTriggerColumnsConfig` (defaults match REBIRTH §12 trigger config — `ShortName`, `CIF`, `SystemID`), `RvabrepColumnsConfig` (defaults match RVABREP physical columns from §3.2 — `ABABCD`, `ABACCD`, `ABAACD`, `ABAHCD`), `RvabrepFilters`.
- **21 unit tests** in `tests/unit/services/test_trigger_strategies.py` (3 test classes covering CSV, RVABREP, stubs). All using real `TabularDataSource` over CSV fixtures. Branch coverage on `services/triggers/*`: **100%**.
- **4 fixture CSVs** under `tests/fixtures/services/triggers/`: `trigger_list.csv` (5 rows incl. blanks), `trigger_list_alt_columns.csv` (custom column names), `trigger_list_missing_col.csv` (validates required-column error), `rvabrep_export.csv` (8 rows, 4 unique pairs after dedup).

### Changed

- `src/cmcourier/services/__init__.py` re-exports the 7 new public symbols from `triggers/` (in addition to the 8 from `mapping`/`metadata`).

### Verification

- `pytest -v`: **222 / 222 pass** in ~3 s (201 from earlier changes + 21 new).
- `pytest --cov`: total project branch coverage holds at ≥94%; `services/triggers/*` at **100%**.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.services.*`: clean across 25 source files.
- `pre-commit run --all-files`: clean.

### Rationale

- Stage S0 (Trigger Acquisition) is the entry point of every pipeline. With S0 unimplemented, no orchestrator could run end-to-end. This change ships the two real strategies needed for the MVP pipelines (`rvabrep-pipeline`, `csv-trigger-pipeline`) and gates the other two with explicit stubs that document the missing dependency.
- **No `TriggerService` wrapper class.** The `S0Strategy` port already represents the trigger-acquisition abstraction; orchestrators in future changes instantiate the appropriate strategy directly per pipeline. The strategies ARE the service.
- The `source_descriptor` parameter on `S0Strategy.acquire()` is silently ignored by every strategy. It's a vestigial port parameter from 002; refining the port to remove it is out of scope (would require an amendment to 002's spec).
- Stubs raise at `acquire()`, not at construction. That lets orchestrators dispatch to them with valid wiring and surface the "missing dependency" error to operators only when the strategy is actually used.

---

## [0.7.0] — 2026-05-10

### Added

- **`cmcourier.services.metadata.MetadataService`** — most complex service in CMCourier so far; engine of stage S3 (Metadata Resolution) per REBIRTH §6. Per-field fallback chain with validation regexes (`re.fullmatch`), default-value fallback (validated against the first source's regex), CIF self-healing (returns a new `TriggerRecord` since the input is frozen), and field-alias normalization (case-insensitive forward map).
- **Five frozen+slots dataclasses**: `MetadataConfig`, `FieldSourceConfig`, `SourceConfig`, `ValidationConfig`, `MetadataResolution`. Carry the configuration shape and the resolution result.
- **Source types supported**: `trigger` (read TriggerRecord attribute), `rvabrep` (read RVABREPDocument attribute), `csv:<alias>` (lookup via IDataSource). `as400:<alias>` raises `NotImplementedError` with an explicit message naming the missing AS400 adapter — that source type lights up when the AS400 adapter ships.
- **Eager pre-fetching of CSV sources** at construction. Cache keyed by `(alias, key_column, key_value, value_column)` so a single CSV source serves multiple fields without re-iterating. `setdefault` preserves first-occurrence on duplicate keys (matches MappingService's REBIRTH §4.3 first-wins precedent).
- **CIF self-healing** (REBIRTH §6.5): if `trigger.cif is None` and `BAC_CIF` is among the canonical fields to resolve, the service resolves `BAC_CIF` first and returns a new `TriggerRecord` with the resolved CIF. Subsequent CSV lookups (which use `trigger.cif` as the lookup key) see the resolved value.
- **`MetadataResolution`** as the typed return shape: `metadata: ResolvedMetadata` + `healed_trigger: TriggerRecord`. Callers (orchestrators, in later changes) MUST use `result.healed_trigger` for subsequent stages.
- **32 unit tests** in `tests/unit/services/test_metadata.py` covering construction + pre-fetch (3), vanilla per source type (3), fallback chain (5), CIF self-healing (4), aliases (3), source dispatch (3), type immutability (2), and edge cases (9). Branch coverage on `metadata.py`: **99%** (target ≥95%).
- **3 CSV fixtures** under `tests/fixtures/services/metadata/`: `clients.csv`, `accounts.csv`, `cards.csv`. Synthetic CIFs (`123456`, `234567`, `345678`) and synthetic names (`JUAN PEREZ TEST`, etc.).

### Changed

- **Pre-commit hook bumped**: `.pre-commit-config.yaml` `ruff-pre-commit` rev from `v0.4.10` to `v0.15.12` to align with the local venv's resolved version. Five changes in a row had hit the version drift; this resolves it. Ruff's hook IDs changed slightly (`ruff` → `ruff (legacy alias)`, `ruff-format` → `ruff format`) but behavior is identical.
- `src/cmcourier/services/__init__.py` re-exports the six new public symbols from `metadata` (in addition to the two from `mapping`).

### Verification

- `pytest -v`: **201 / 201 pass** in ~3 s (169 from earlier changes + 32 new).
- `pytest --cov=src/cmcourier`: total branch coverage **94%+**. Coverage on `services/metadata.py`: **99%**.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.services.*`: clean across 21 source files.
- `pre-commit run --all-files`: ruff (legacy alias), ruff format, mypy all pass.

### Rationale

- The metadata layer is the heart of CMCourier's "configurability" promise: every CMIS property comes from the fallback chain, with validation per source and a safety-net default. Without this service, no document can be uploaded with correct metadata.
- **Pre-fetching included in this change (not deferred)**: REBIRTH §6.6 explicitly notes that without it, a 200,000-document migration would fire tens of thousands of point queries against AS400. The pre-fetch is central to the architecture, not an optimization to bolt on later.
- **CIF self-healing returns a new `TriggerRecord` instead of mutating**: domain models are `frozen=True`. The contract is documented and tested; orchestrators threading `healed_trigger` forward is the next change's responsibility.
- **`as400:<alias>` raises `NotImplementedError` with explicit message**: cleaner than partially-implementing it. The handler will be added in one line when the AS400 adapter ships; tests pin the contract today.
- **Logging discipline (Constitution Principle VIII)**: the service logs field NAMES (`BAC_CIF`, `BAC_Nombre_Cliente`) but NEVER field VALUES. Customer name, account number, and CIF VALUES are PII; field names are not.

---

## [0.6.0] — 2026-05-09

### Added

- **`cmcourier.services.mapping.MappingService`** — the first service-layer class. Caches the Modelo Documental (REBIRTH §4) at construction from any `IDataSource` and exposes `get_mapping(id_rvi)`, `get_all()`, `count()`, and `__contains__`. Stage S2 of every pipeline depends on this lookup, as does the future `doctor` command's mapping-completeness check.
- **`cmcourier.services.mapping.MappingColumnsConfig`** — frozen dataclass for column-name overrides. Defaults match REBIRTH §4.1 (`"ID CLASE DOCUMENTAL"`, `"ID RVI"`, `"ID Corto"`, `"CLASE DOCUMENTAL"`, `"METADATOS"`).
- **Duplicate handling** per REBIRTH §4.3: first occurrence of a repeated `ID RVI` wins; subsequent occurrences are dropped with a `WARNING` log entry naming the duplicate value.
- **Empty-ID-RVI handling**: rows with blank or whitespace-only `ID RVI` cells are silently skipped; the constructor logs an `INFO` line with the skipped count.
- **METADATOS parsing**: comma-separated, whitespace-tolerant, empty-fragment-filtering. `(""," CIF, NUM "," CIF , ", "CIF,", "CIF,,NUM_CUENTA")` all yield clean tuples without surprises.
- **`tests/unit/services/test_mapping.py`** — 21 unit tests using a real `TabularDataSource` over `tests/fixtures/services/modelo_documental.csv` (no IDataSource mocks; the SUT does no I/O so the adapter is wiring, not the system under test). Coverage on `services/mapping.py`: **100 %**.
- **`tests/fixtures/services/modelo_documental.csv`** — 8-row fixture with vanilla rows, METADATOS edge cases (empty, whitespace, trailing comma, doubled comma), one duplicate `ID RVI`, and one empty-ID row.

### Changed

- `src/cmcourier/services/__init__.py` re-exports `MappingService` and `MappingColumnsConfig` so callers write `from cmcourier.services import MappingService`.
- README "Status checklist" ticks the fourth-change milestone.

### Verification

- `pytest -v`: **169 / 169 pass** in 1.32 s (148 from earlier changes + 21 new).
- `pytest --cov=src/cmcourier`: **total branch coverage 95.34 %** (threshold 80 %); `services/mapping.py` 100 %; `domain/*` 95-100 %; `adapters/sources/tabular.py` 96 %.
- `ruff check`, `ruff format --check`, `mypy --strict`: all clean.
- `pre-commit run --all-files`: ruff, ruff-format, mypy all pass.

### Rationale

- **First service layer in CMCourier**. Validates that the hexagonal architecture established by 001-003 holds together end-to-end: `services/mapping.py` imports only `cmcourier.domain.*` (Constitution Principle I); the test wires a real `TabularDataSource` adapter; the service raises the domain-defined `IDRViNotMappedError` on cache miss. Future services (metadata, trigger, document) follow the same shape.
- **Eager-load + dict cache** chosen over lazy-with-cache-miss-query because the Modelo Documental is small (< 1000 rows in practice) and stage S2 needs O(1) lookup at pipeline scale.
- **Field aliases (CIF → BAC_CIF, REBIRTH §6.2) NOT handled here**. They are the responsibility of the metadata service (next change). Mapping exposes raw names from the source.
- **Logging via stdlib `logging.getLogger(__name__)`** is PII-safe in this layer because `id_rvi` is a document-class code, not customer data. The PII masking helper (`cli/ui/logging.py`, forthcoming) routes the loggers properly when it lands.

---

## [0.5.0] — 2026-05-09

### Added

- **`cmcourier.adapters.sources.tabular.TabularDataSource`** — first concrete `IDataSource` implementation. Reads CSV and XLSX files via pandas (with `openpyxl` as the engine for `.xlsx`/`.xls`), exposes the full IDataSource contract minus the SQL methods, and normalizes pandas `NaN` to Python `None` at the port boundary so callers never see pandas-specific sentinels.
- **`tests/integration/adapters/test_tabular_data_source.py`** — 34 integration tests parametrized over CSV / XLSX. Covers the contract methods, lifecycle (`close`, idempotency, post-close access), file-extension dispatch (case-insensitive, unknown rejected), encoding override (latin-1 fixture), and multi-sheet XLSX selection. Branch coverage on the new module: 96 % (target ≥ 90 %).
- **`tests/fixtures/sources/`** — synthetic test fixtures: `sample.csv`, `bad_extension.txt`, `latin1.csv` (committed), and `sample.xlsx` / `multi_sheet.xlsx` (generated at session start by a new `tests/conftest.py` autouse fixture; `*.xlsx` is gitignored to keep binaries out of the repo).
- **`openpyxl>=3.1,<4.0`** added to runtime dependencies — required by `pandas.read_excel` for `.xlsx` files.

### Changed

- `tests/conftest.py` now hosts a session-scoped autouse fixture (`_generate_xlsx_fixtures`) that materializes `sample.xlsx` and `multi_sheet.xlsx` at session start if they do not exist. Previously the file held only a docstring.
- `src/cmcourier/adapters/sources/__init__.py` re-exports `TabularDataSource` so callers write `from cmcourier.adapters.sources import TabularDataSource`.
- `.gitignore` excludes `tests/fixtures/sources/*.xlsx` (deterministic regeneration; binary diffs in git are noise).

### Verification

- `pytest`: **148 / 148 pass** in 2.81 s (112 unit + 34 integration + 2 smoke tests).
- `pytest --cov=src/cmcourier`: **total branch coverage 94.33 %** (threshold 80 %; tabular.py 96 %, domain layer 95-100 %).
- `ruff check`, `ruff format --check`: clean.
- `mypy src/cmcourier/`: clean across 19 source files.
- `pre-commit run --all-files`: ruff, ruff-format, mypy all pass.

### Rationale

- Provides the first concrete adapter so subsequent service-layer changes (004+) have a real `IDataSource` to test against without depending on AS400 — Constitution Principle VI's canonical dev/test substitute. The AS400 adapter, when it lands, implements the same port; both are interchangeable behind the abstraction.
- `query()` and `query_stream()` raise `NotImplementedError` with explicit messages rather than fake SQL via `pandasql` or `duckdb`. The IDataSource port is broad enough to cover both AS400 (SQL) and tabular (field-based) use cases; service code that calls `query()` knows it is talking to a SQL-capable adapter. A future ISP refactor of the port can split the SQL methods off if the asymmetry becomes painful.
- `dtype=str` always — preserves leading zeros (`"000456"` does not become integer 456) and unifies type semantics across CSV/XLSX. Type interpretation is a service-layer responsibility via factories, not an adapter concern.
- One class for both formats — they share the IDataSource methods identically; only loading differs. Two classes would duplicate ~80 % of the code without benefit.
- `openpyxl` is a transitive technical consequence of the explicit XLSX scope decision for this change. Not a constitutional amendment.

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

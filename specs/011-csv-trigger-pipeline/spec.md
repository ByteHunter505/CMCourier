# Spec — 011-csv-trigger-pipeline

**Status**: Draft
**Pipeline**: `csv-trigger-pipeline`: `S0(csv) → S1 → S2 → S3 → S4 → S5 → S6 (transversal)`.
**Constitution alignment**: I (hexagonal — orchestrator wires ports only, no
direct I/O), II (idempotency — `is_uploaded` and `is_stage_done` skip
short-circuits), III (single-responsibility — orchestrator is pure
coordination, no business logic), VI (real test pyramid — pipeline tested
end-to-end with real adapters, network stubbed via `responses`).

---

## 1. Intent

Implement `CsvTriggerPipeline` — the first runnable MVP orchestrator
wiring stages `S0..S6` against a CSV trigger source. With every adapter
and service now real (changes 003-010), this is the single composition
that produces a working end-to-end migration loop.

This change ALSO ships the smallest possible amendment to the
`ITrackingStore` port (`list_txn_nums_for_batch`) needed for stage-by-stage
resume. The port amendment is documented + tested as part of the same
change so port + first consumer ship together.

---

## 2. Scope

### In scope

- `cmcourier.orchestrators.csv_trigger.CsvTriggerPipeline` — orchestrator
  class with one public `run` method taking a CSV path, batch size, and
  optional resume parameters.
- `cmcourier.orchestrators.csv_trigger.RunReport` — frozen dataclass
  returned by `run`. Fields: `batch_id`, `total_triggers`, `total_docs`,
  `s1_done`, `s1_skipped_cross_batch`, `s2_done`, `s2_failed`, `s3_done`,
  `s3_failed`, `s4_done`, `s4_failed`, `s5_done`, `s5_failed`,
  `elapsed_seconds`.
- **Cross-batch idempotency skip**: after S1 emits a doc,
  if `is_uploaded(txn_num)` returns True, skip the doc entirely (no
  `migration_log` row for this batch). Counts toward
  `s1_skipped_cross_batch`.
- **Per-stage state machine**: for every doc that
  reaches S1_DONE, the orchestrator transitions through S2_PENDING →
  S2_DONE → ... → S5_DONE via `mark_stage_pending` /
  `mark_stage_done` / `mark_stage_failed`. Doc-level errors do NOT halt
  the batch; they are tracked and the orchestrator continues with
  remaining docs.
- **Stage-by-stage resume**: `run(batch_id=..., from_stage=N)`
  reuses an existing batch and skips stages 1..N-1. Within a single run,
  every stage skip-checks `is_stage_done(txn, batch_id, S(stage)_DONE)`
  per doc — so re-runs are idempotent regardless of where the orchestrator
  is invoked from.
- **`ITrackingStore` port amendment**: new abstract method
  `list_txn_nums_for_batch(batch_id) -> set[str]` returning the set of
  rvabrep_txn_num values in `migration_log` for the given batch.
  Implemented in `SQLiteTrackingStore` via `SELECT DISTINCT
  rvabrep_txn_num FROM migration_log WHERE batch_id = ?`.
- **Trigger-level errors** (`RVABREPNotFoundError`, `RVABREPDeletedError`)
  are LOGGED at WARNING but do NOT create migration_log rows — they
  occur before any document identity exists.

### Out of scope

- CLI Click command (`cmcourier csv-trigger-pipeline run`) — deferred to
  a follow-up change. 011 ships the orchestrator class only; tests
  invoke it directly.
- Pydantic config + YAML loader — deferred (the test harness wires
  adapters by hand).
- TUI — deferred. Logging goes through stdlib `logging`.
- Two-batch producer-consumer — deferred. 011 processes
  one batch end-to-end before returning.
- Pre-flight `doctor` validation — deferred.
- Adaptive heavy/light upload lanes — post-MVP.
- Other pipelines (`rvabrep-pipeline`, `as400-trigger-pipeline`,
  `local-scan-pipeline`, `single-doc`) — each lands as its own change.
  All four follow the SAME stage chain; they differ only in S0.

---

## 3. Functional requirements (RFC 2119)

### Port amendment

- **REQ-001** `ITrackingStore` MUST gain an abstract method
  `list_txn_nums_for_batch(self, batch_id: str) -> set[str]`. Existing
  `SQLiteTrackingStore` MUST implement it. The implementation MUST
  use a synchronous read on the reader connection (consistent with
  `is_uploaded` and `is_stage_done`).
- **REQ-002** Calling `list_txn_nums_for_batch` for a non-existent
  `batch_id` MUST return an empty set (NOT raise).

### Construction

- **REQ-003** `CsvTriggerPipeline.__init__` MUST accept the following
  collaborators by keyword: `trigger_strategy: S0Strategy`,
  `indexing_service: IndexingService`,
  `mapping_service: MappingService`,
  `metadata_service: MetadataService`,
  `assembler: PdfAssembler`,
  `uploader: CmisUploader`,
  `tracking_store: ITrackingStore`.
- **REQ-004** The constructor MUST NOT perform any I/O. The pipeline is
  lazy: all work happens inside `run`.

### `run` signature

- **REQ-005** `run` MUST have the signature
  `run(*, source_descriptor: str, batch_size: int = 1000, batch_id: str | None = None, from_stage: int = 1) -> RunReport`.
- **REQ-006** Parameter validation:
  - `batch_size >= 1`
  - `1 <= from_stage <= 5`
  - If `from_stage > 1`, `batch_id` MUST be provided (resume requires an
    existing batch).
  - If `from_stage == 1` AND `batch_id` is provided, the pipeline
    continues an existing batch from scratch (idempotent — already-done
    stages skip via `is_stage_done`).
  - Otherwise (`from_stage == 1` AND `batch_id is None`), the pipeline
    starts a fresh batch via `tracking_store.start_batch`.
- **REQ-007** Validation failures MUST raise `ValueError` with a
  message identifying the offending parameter.

### Stage S0 — Trigger acquisition

- **REQ-008** The orchestrator MUST iterate
  `trigger_strategy.acquire(source_descriptor)` and materialize the
  triggers into a list (the list is needed for resume scope filtering).
- **REQ-009** A `S0Strategy` exception MUST propagate out of `run`
  unchanged. The batch (if started) is NOT auto-completed; the operator
  re-invokes with the same `batch_id` after fixing the upstream source.

### Stage S1 — Indexing + tracking entry

- **REQ-010** For each trigger, the orchestrator MUST call
  `indexing_service.find_documents(trigger)` and handle the result:
  - **Success (list of docs)**: each doc enters the pipeline.
  - **`RVABREPNotFoundError`**: log a `WARNING` with
    `extra={"shortname", "system_id"}`. No migration_log row. The
    trigger is dropped silently from the batch.
  - **`RVABREPDeletedError`**: log a `WARNING` similarly. No
    migration_log row.
  - **`IndexingError` (wrapped data source failure)**: log an `ERROR`
    naming the trigger; the doc is dropped; the batch continues.
- **REQ-011** For each doc emitted by S1:
  - If `tracking_store.is_uploaded(doc.txn_num)` returns True, the doc
    MUST be SKIPPED (no migration_log row, no further stages). The
    orchestrator MUST count this in `RunReport.s1_skipped_cross_batch`
    and log an `INFO` with `extra={"txn_num", "reason": "cross_batch_uploaded"}`.
  - Otherwise, the orchestrator MUST call
    `tracking_store.mark_stage_pending(record, StageStatus.S1_PENDING)`
    followed by
    `tracking_store.mark_stage_done(doc.txn_num, batch_id, StageStatus.S1_DONE)`
    in immediate succession. The `MigrationRecord` is built from the
    trigger and doc fields plus `batch_id` and
    `created_at=datetime.now()`.

### Stage-by-stage resume

- **REQ-012** When `from_stage > 1`, S0+S1 still execute (re-read CSV,
  re-index from RVABREP), but the orchestrator MUST filter the
  resulting docs to ONLY those whose `txn_num` is in
  `tracking_store.list_txn_nums_for_batch(batch_id)`. Docs emitted by
  the fresh S1 run but NOT in the prior batch's scope are skipped with
  an INFO log naming `txn_num` and `reason="resume_out_of_scope"`.
- **REQ-013** Within stages S2..S5, every iteration MUST start with
  `if tracking_store.is_stage_done(txn_num, batch_id, S(N)_DONE): skip
  the work AND advance state to the next stage`. The skip MUST be
  counted as part of `RunReport.s(N)_done`.

### Stage S2 — Mapping

- **REQ-014** For each doc not already at S2_DONE:
  - `mark_stage_pending(record, StageStatus.S2_PENDING)`.
  - Call `mapping_service.get_mapping(doc.index7)`.
  - On success: `mark_stage_done(..., S2_DONE)`. Pass `(trigger, doc, mapping)`
    to the next stage.
  - On `IDRViNotMappedError`: `mark_stage_failed(..., S2_FAILED, str(exc))`.
    Drop the doc from subsequent stages. Increment
    `RunReport.s2_failed`.
- **REQ-015** Any other exception MUST mark the stage as failed AND
  surface in the failed counter; the doc is dropped from subsequent stages.

### Stage S3 — Metadata

- **REQ-016** For each `(trigger, doc, mapping)` not already at S3_DONE:
  - `mark_stage_pending(record, S3_PENDING)`.
  - Call `metadata_service.resolve(trigger, doc, mapping)`.
  - On success: `mark_stage_done(..., S3_DONE)`. The resulting
    `MetadataResolution.healed_trigger` REPLACES the original trigger
    for subsequent stages.
  - On `SourceFailedError` / `DefaultValidationFailedError`:
    `mark_stage_failed(..., S3_FAILED, str(exc))`. Drop the doc.

### Stage S4 — Assembly

- **REQ-017** For each `(doc, mapping, metadata, healed_trigger)` not
  already at S4_DONE:
  - `mark_stage_pending(record, S4_PENDING)`.
  - Call `assembler.assemble(doc)`.
  - On success: `mark_stage_done(..., S4_DONE)`.
  - On `SourceFileMissingError` / `PDFAssemblyFailedError`:
    `mark_stage_failed(..., S4_FAILED, str(exc))`. Drop the doc.

### Stage S5 — Upload

- **REQ-018** For each `(staged_file, mapping, metadata)` not already at
  S5_DONE:
  - `mark_stage_pending(record, S5_PENDING)`.
  - Build the document_name as `f"{doc.txn_num}.pdf"`.
  - Build the mime_type as `"application/pdf"`.
  - Call `uploader.upload(staged_file, mapping.cm_folder,
    mapping.cm_object_type, document_name, mime_type, metadata.properties)`.
  - On success: `mark_stage_done(..., S5_DONE)`. Increment
    `RunReport.s5_done`.
  - On `CMISClientError` / `CMISServerError` / `RetriesExhaustedError`:
    `mark_stage_failed(..., S5_FAILED, str(exc))`. Drop the doc.

### Batch finalization

- **REQ-019** After all stages complete (or fail), the orchestrator MUST
  call `tracking_store.complete_batch(batch_id)` exactly once. If any
  stage raised through (S0 source failure, REQ-009), `complete_batch`
  is NOT called.
- **REQ-020** The orchestrator MUST call `tracking_store.flush()` before
  reading state for any `is_stage_done` / `is_uploaded` check that
  depends on writes from the same run (orchestrator's "read my own
  writes" anchor).

### `RunReport`

- **REQ-021** `RunReport` MUST be a `frozen=True, slots=True` dataclass
  with the fields listed in §2 (in scope). All counters MUST be
  non-negative integers; `elapsed_seconds` MUST be a non-negative
  `float`.
- **REQ-022** Counter invariants:
  - `s1_done + s1_skipped_cross_batch == total_docs` (docs emitted by S1
    minus deleted/missing).
  - `s2_done + s2_failed == s1_done` (every S1_DONE doc reaches an S2
    terminal).
  - Same shape for S3, S4, S5.
  - `total_triggers >= 0` is the count of triggers from S0.

### Logging discipline (Constitution VIII)

- **REQ-023** All log records MUST carry `batch_id` in `extra`. Per-doc
  records MUST carry `txn_num`. Per-stage records MUST carry `stage`.
- **REQ-024** Log records MUST NOT carry resolved property VALUES
  (CIF, customer name, file content). They MAY carry property NAMES
  (`BAC_CIF`, `BAC_Nombre_Cliente`).

---

## 4. Acceptance scenarios

Test fixtures are wired by hand (no Pydantic config, no CLI). Each
scenario builds a complete adapter graph using the synthetic fixtures
established by changes 003-010.

### 4.1 Fresh full-run happy path
- Given: trigger CSV with 2 triggers; both map to 1 RVABREP doc each;
  both docs have a valid mapping + metadata; both have page files on
  disk; CMIS upload mocked to return 201 with succinctProperties.
- When: `run(source_descriptor=triggers.csv, batch_size=10)`.
- Then: `RunReport.s5_done == 2`, all other failed counters == 0,
  `complete_batch` called once, `batch_id` is a non-empty UUID4 string.

### 4.2 Trigger not in RVABREP → logged, no migration_log row
- Given: trigger CSV with 1 trigger that does NOT match any RVABREP row.
- When: `run(...)`.
- Then: `RunReport.total_docs == 0`, `s1_done == 0`. A WARNING log line
  names the trigger shortname. `migration_log` contains zero rows for
  this batch.

### 4.3 Cross-batch is_uploaded skip
- Given: a prior batch left `migration_log` with txn `TXN0000001` at
  `S5_DONE`. A NEW batch contains a trigger that resolves to that same
  txn.
- When: `run(...)` for the new batch.
- Then: `RunReport.s1_skipped_cross_batch == 1`. No migration_log row
  is created for this doc in the new batch (only the old batch's row
  exists for it).

### 4.4 S2 mapping not found
- Given: a doc whose `index7` (id_rvi) is not in the Modelo Documental.
- When: `run(...)`.
- Then: `RunReport.s2_failed == 1`, `s3_done == 0` for this doc, the
  migration_log row is at `S2_FAILED` with `error_message` containing
  the missing `id_rvi`.

### 4.5 S3 metadata source failed
- Given: a doc whose metadata source fails for a required field with
  no default.
- When: `run(...)`.
- Then: `RunReport.s3_failed == 1`, row at `S3_FAILED`.

### 4.6 S4 source file missing
- Given: a doc whose first page file is not on disk.
- When: `run(...)`.
- Then: `RunReport.s4_failed == 1`, row at `S4_FAILED`.

### 4.7 S5 CMIS 4xx fail-fast
- Given: CMIS mock returns 400 for the upload.
- When: `run(...)`.
- Then: `RunReport.s5_failed == 1`, row at `S5_FAILED`.

### 4.8 Resume from S3 after S2 success
- Given: an existing batch with all docs at `S2_DONE`. CMIS mock
  configured to succeed.
- When: `run(batch_id=existing, from_stage=3)`.
- Then: S0+S1 re-execute idempotently (no new rows). S2 is skipped per
  doc (`is_stage_done` short-circuits). S3..S5 process. Final state:
  every doc at `S5_DONE`.

### 4.9 Resume out-of-scope doc filter
- Given: a CSV that emits 3 triggers, only 2 of whose txns are in the
  prior batch's `migration_log`.
- When: `run(batch_id=existing, from_stage=3)`.
- Then: the 3rd doc is logged at INFO with
  `reason="resume_out_of_scope"` and is NOT processed.

### 4.10 Idempotent re-run from from_stage=1
- Given: a fully-completed prior batch (`from_stage=1` with same
  `batch_id`).
- When: `run(batch_id=existing, from_stage=1)`.
- Then: every stage's `is_stage_done` check fires for every doc — no
  upload POSTs are issued, no mapping_service calls. `RunReport.s5_done`
  equals the number of docs in scope (counted by skipping, not
  re-uploading).

### 4.11 Heterogeneous batch — partial successes
- Given: 4 triggers: 1 succeeds end-to-end, 1 fails at S2, 1 fails at
  S3, 1 fails at S5.
- When: `run(...)`.
- Then: `RunReport == (s5_done=1, s2_failed=1, s3_failed=1, s5_failed=1)`.
  `complete_batch` is called once. The batch row in `migration_batch`
  has a non-NULL `completed_at`.

### 4.12 S0 fails → run raises, complete_batch NOT called
- Given: a `S0Strategy.acquire(source_descriptor)` that raises (e.g.,
  CSV missing).
- When: `run(...)`.
- Then: the exception propagates out of `run`. No `complete_batch` call
  was made (verified via a side-channel SQL query on `migration_batch`).

### 4.13 list_txn_nums_for_batch returns empty for unknown batch
- Given: `SQLiteTrackingStore` with no rows for `batch_id="missing"`.
- When: `list_txn_nums_for_batch("missing")` is called.
- Then: returns `set()`. (No exception.)

### 4.14 RunReport invariants
- For every scenario where `run(...)` returns, `s2_done + s2_failed ==
  s1_done` AND `s5_done + s5_failed + dropped_intermediate ==
  s1_done`, where `dropped_intermediate` accounts for docs that failed
  in earlier stages.

### 4.15 healed_trigger propagates to upload metadata
- Given: a trigger with `cif=None` and the metadata service performs
  CIF self-healing returning `cif="000123"`.
- When: `run(...)`.
- Then: the resulting CMIS upload's `properties["clbNonGroup.BAC_CIF"]`
  is `"000123"` (verified via `responses.calls[-1].request.body`
  inspection OR via the `_FROZEN_CIF` sentinel in the metadata
  config).

### 4.16 Cross-batch is_uploaded skip is observable in logs
- Given: scenario 4.3.
- When: caplog captures records at INFO level.
- Then: at least one record carries
  `extra["reason"] == "cross_batch_uploaded"` and
  `extra["txn_num"] == "TXN0000001"`.

---

## 5. Non-functional requirements

- **NFR-001** The orchestrator MUST be agnostic to the concrete adapters
  beyond the typed interfaces (`S0Strategy`, `IndexingService`,
  `MappingService`, `MetadataService`, `PdfAssembler`, `CmisUploader`,
  `ITrackingStore`). Replacing any one with a different implementation
  MUST not require orchestrator changes.
- **NFR-002** Memory: the orchestrator MUST process triggers in batch
  (materializing the list is required for resume scope filtering) but
  per-doc state is dropped after each stage. No accumulation of
  intermediate file bytes in memory.
- **NFR-003** Branch coverage on `orchestrators/csv_trigger.py` MUST
  be ≥ 85%. The orchestrator's branch surface is dominated by
  per-stage exception handlers; covering every error path is the
  test plan's primary driver.
- **NFR-004** Function length cap (Constitution III): every method ≤ 50
  lines. `run` itself MUST stay under that budget; per-stage loops are
  extracted into private helpers.

---

## 6. Tooling expectations

- `ruff check src/ tests/`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.orchestrators.*`: clean.
- `pre-commit run --all-files`: clean.
- `pytest`: full suite passes; net positive test count (~20 new).

---

## 7. Open questions / risks

- **Risk**: orchestrator test setup is the largest in the project (every
  adapter + every service). Mitigation: a shared `conftest.py` at
  `tests/integration/pipeline/` builds the adapter graph from existing
  fixtures plus a CMIS stub. The orchestrator tests then call
  `run(...)` and assert on the returned `RunReport` + side effects.
- **Risk**: `MetadataService` config has many knobs (sources, validation,
  defaults). For pipeline tests, the metadata config MUST be terse and
  predictable. Mitigation: tests use a fixed three-source CSV graph
  (clients / accounts / cards) matching the existing 005 fixtures, with
  required fields trimmed to `BAC_CIF` and `BAC_Nombre_Cliente`.
- **Open question**: should `RunReport` include error breakdowns per
  stage (which docs failed)? **Resolved**: no — tests inspect the
  tracking store directly for that. RunReport is counters + identity
  only.
- **Risk**: stage-by-stage resume tests are stateful (require seeded
  tracking state). Mitigation: each resume test starts by running a
  fresh pipeline to a known intermediate state, then a second `run`
  with `from_stage > 1`. Both calls share the same `SQLiteTrackingStore`
  instance via the test fixture; cross-batch tests use TWO instances on
  the same file.
- **Risk**: the orchestrator wires 7 collaborators. If any one's
  constructor changes signature, the orchestrator tests break. This
  coupling is intentional — the pipeline IS the wiring. Mitigation:
  none needed; this is the cost of "wiring is testable".

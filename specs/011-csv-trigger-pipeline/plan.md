# Plan — 011-csv-trigger-pipeline

**Status**: Draft
**Spec**: `specs/011-csv-trigger-pipeline/spec.md`

---

## 1. Architecture in one paragraph

One orchestrator class `CsvTriggerPipeline` that wires the seven
collaborators (`S0Strategy`, `IndexingService`, `MappingService`,
`MetadataService`, `PdfAssembler`, `CmisUploader`, `ITrackingStore`) and
exposes a single public `run` method. Internally, `run` calls a chain of
private `_stage_sN` methods that share a small in-memory state machine:
each stage filters its input list, processes each item with idempotent
skip-checks via the tracking store, and yields the survivors to the next
stage. `RunReport` (frozen dataclass) aggregates the per-stage counters.
The `ITrackingStore` port gains one method (`list_txn_nums_for_batch`)
needed by resume.

---

## 2. Module layout

```
src/cmcourier/orchestrators/csv_trigger.py
├── RunReport                          # frozen+slots dataclass
├── _StageItem                          # private dataclass for stage state
├── CsvTriggerPipeline
│   ├── __init__(*, trigger_strategy, indexing_service, mapping_service,
│   │           metadata_service, assembler, uploader, tracking_store)
│   ├── run(*, source_descriptor, batch_size=1000,
│   │        batch_id=None, from_stage=1) -> RunReport
│   ├── _validate_parameters(batch_size, from_stage, batch_id)
│   ├── _resolve_batch_id(batch_id, from_stage) -> str
│   ├── _stage_s0_s1(triggers, batch_id, resume_scope) -> list[_StageItem]
│   ├── _stage_s2(items, batch_id) -> list[_StageItem]
│   ├── _stage_s3(items, batch_id) -> list[_StageItem]
│   ├── _stage_s4(items, batch_id) -> list[_StageItem]
│   ├── _stage_s5(items, batch_id) -> int            # returns s5_done
│   └── _build_record(item, batch_id, stage) -> MigrationRecord
```

Each `_stage_sN` returns a smaller (or equal) list of survivors. Every
method ≤ 50 lines.

---

## 3. Public API contracts

### 3.1 `RunReport`

```python
@dataclass(frozen=True, slots=True)
class RunReport:
    batch_id: str
    total_triggers: int
    total_docs: int
    s1_done: int
    s1_skipped_cross_batch: int
    s2_done: int
    s2_failed: int
    s3_done: int
    s3_failed: int
    s4_done: int
    s4_failed: int
    s5_done: int
    s5_failed: int
    elapsed_seconds: float
```

### 3.2 `_StageItem`

```python
@dataclass(slots=True)
class _StageItem:
    trigger: TriggerRecord
    document: RVABREPDocument
    mapping: CMMapping | None = None
    metadata: ResolvedMetadata | None = None
    staged_file: StagedFile | None = None
    cm_object_id: str | None = None
```

Not frozen — fields fill in as stages succeed.

### 3.3 `CsvTriggerPipeline.run`

```python
def run(
    self,
    *,
    source_descriptor: str,
    batch_size: int = 1000,
    batch_id: str | None = None,
    from_stage: int = 1,
) -> RunReport:
    """Run the csv-trigger pipeline end-to-end.

    Raises:
        ValueError: parameter validation failure.
        Any S0Strategy exception: propagates without calling complete_batch.
    """
```

---

## 4. Algorithm sketches

### 4.1 `run` orchestration

```python
def run(self, *, source_descriptor, batch_size, batch_id, from_stage):
    start = time.monotonic()
    self._validate_parameters(batch_size, from_stage, batch_id)
    resolved_batch_id = self._resolve_batch_id(batch_id, from_stage)

    triggers = list(self._trigger_strategy.acquire(source_descriptor))
    total_triggers = len(triggers)
    resume_scope = (
        self._tracking_store.list_txn_nums_for_batch(resolved_batch_id)
        if from_stage > 1
        else None
    )

    items_after_s1, s1_skipped = self._stage_s0_s1(triggers, resolved_batch_id, resume_scope)
    s2_items, s2_failed = self._stage_s2(items_after_s1, resolved_batch_id) if from_stage <= 2 else self._restate_s2(items_after_s1, resolved_batch_id)
    s3_items, s3_failed = self._stage_s3(s2_items, resolved_batch_id) if from_stage <= 3 else self._restate_s3(...)
    s4_items, s4_failed = self._stage_s4(s3_items, resolved_batch_id) if from_stage <= 4 else self._restate_s4(...)
    s5_done_count, s5_failed = self._stage_s5(s4_items, resolved_batch_id) if from_stage <= 5 else self._restate_s5(...)

    self._tracking_store.flush()
    self._tracking_store.complete_batch(resolved_batch_id)

    return RunReport(
        batch_id=resolved_batch_id,
        total_triggers=total_triggers,
        total_docs=len(items_after_s1) + s1_skipped,
        s1_done=len(items_after_s1),
        s1_skipped_cross_batch=s1_skipped,
        s2_done=len(s2_items),
        s2_failed=s2_failed,
        s3_done=len(s3_items),
        s3_failed=s3_failed,
        s4_done=len(s4_items),
        s4_failed=s4_failed,
        s5_done=s5_done_count,
        s5_failed=s5_failed,
        elapsed_seconds=time.monotonic() - start,
    )
```

Simplification: rather than maintain a separate `_restate_sN` path, every
stage's loop body checks `is_stage_done` per-doc and SKIPS the work
silently — counting the doc as "done" without re-doing it. Then the only
asymmetry is whether to ADVANCE the item to the next stage:

Actually, the cleanest pattern is: every stage's body, even on
`from_stage > N`, does the same logic. The skip-check inside each stage
handles both "fresh re-run" and "explicit resume" identically. The
orchestrator does NOT need separate paths.

Revised:

```python
def run(self, *, source_descriptor, batch_size, batch_id, from_stage):
    ...
    items, s1_skipped = self._stage_s0_s1(triggers, resolved_batch_id, resume_scope)
    items, s2_failed = self._stage_s2(items, resolved_batch_id)
    items, s3_failed = self._stage_s3(items, resolved_batch_id)
    items, s4_failed = self._stage_s4(items, resolved_batch_id)
    s5_done, s5_failed = self._stage_s5(items, resolved_batch_id)
    ...
```

The `from_stage` parameter only feeds into:
- `resume_scope` filtering inside `_stage_s0_s1`.
- A defensive log line at the start of `run` naming the requested resume.

The skip-check inside each `_stage_sN` provides the actual idempotency.

### 4.2 `_stage_s0_s1`

```python
def _stage_s0_s1(self, triggers, batch_id, resume_scope):
    items: list[_StageItem] = []
    skipped_cross_batch = 0
    for trigger in triggers:
        try:
            docs = self._indexing_service.find_documents(trigger)
        except RVABREPNotFoundError as exc:
            _log.warning("pipeline: trigger has no rvabrep rows", extra={...})
            continue
        except RVABREPDeletedError as exc:
            _log.warning("pipeline: every rvabrep row deleted", extra={...})
            continue
        except IndexingError as exc:
            _log.error("pipeline: indexing failed", extra={...})
            continue

        for doc in docs:
            if resume_scope is not None and doc.txn_num not in resume_scope:
                _log.info("pipeline: doc out of resume scope",
                          extra={"txn_num": doc.txn_num, "reason": "resume_out_of_scope"})
                continue
            if self._tracking_store.is_uploaded(doc.txn_num):
                _log.info("pipeline: doc already uploaded in prior batch",
                          extra={"txn_num": doc.txn_num, "reason": "cross_batch_uploaded"})
                skipped_cross_batch += 1
                continue
            item = _StageItem(trigger=trigger, document=doc)
            record = self._build_record(item, batch_id, StageStatus.S1_PENDING)
            self._tracking_store.mark_stage_pending(record, StageStatus.S1_PENDING)
            self._tracking_store.mark_stage_done(doc.txn_num, batch_id, StageStatus.S1_DONE)
            items.append(item)
    return items, skipped_cross_batch
```

Length: ~28 lines. Within budget.

### 4.3 `_stage_s2` (template for S3-S4-S5)

```python
def _stage_s2(self, items, batch_id):
    survivors: list[_StageItem] = []
    failed = 0
    for item in items:
        txn = item.document.txn_num
        if self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S2_DONE):
            # Already done — rehydrate mapping for downstream stages.
            try:
                item.mapping = self._mapping_service.get_mapping(item.document.index7)
            except IDRViNotMappedError:
                # Shouldn't happen if S2_DONE, but defensively drop.
                continue
            survivors.append(item)
            continue
        record = self._build_record(item, batch_id, StageStatus.S2_PENDING)
        self._tracking_store.mark_stage_pending(record, StageStatus.S2_PENDING)
        try:
            mapping = self._mapping_service.get_mapping(item.document.index7)
        except IDRViNotMappedError as exc:
            self._tracking_store.mark_stage_failed(txn, batch_id, StageStatus.S2_FAILED, str(exc))
            failed += 1
            continue
        self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S2_DONE)
        item.mapping = mapping
        survivors.append(item)
    return survivors, failed
```

Same shape for S3, S4, S5 — each ~25 lines.

### 4.4 `_stage_s3` differences

```python
def _stage_s3(self, items, batch_id):
    survivors: list[_StageItem] = []
    failed = 0
    for item in items:
        assert item.mapping is not None
        txn = item.document.txn_num
        if self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S3_DONE):
            try:
                resolution = self._metadata_service.resolve(item.trigger, item.document, item.mapping)
            except (SourceFailedError, DefaultValidationFailedError):
                continue
            item.metadata = resolution.metadata
            item.trigger = resolution.healed_trigger
            survivors.append(item)
            continue
        record = self._build_record(item, batch_id, StageStatus.S3_PENDING)
        self._tracking_store.mark_stage_pending(record, StageStatus.S3_PENDING)
        try:
            resolution = self._metadata_service.resolve(item.trigger, item.document, item.mapping)
        except (SourceFailedError, DefaultValidationFailedError) as exc:
            self._tracking_store.mark_stage_failed(txn, batch_id, StageStatus.S3_FAILED, str(exc))
            failed += 1
            continue
        self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S3_DONE)
        item.metadata = resolution.metadata
        item.trigger = resolution.healed_trigger
        survivors.append(item)
    return survivors, failed
```

### 4.5 `_stage_s4`

```python
def _stage_s4(self, items, batch_id):
    survivors: list[_StageItem] = []
    failed = 0
    for item in items:
        txn = item.document.txn_num
        if self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S4_DONE):
            try:
                item.staged_file = self._assembler.assemble(item.document)
            except (SourceFileMissingError, PDFAssemblyFailedError):
                continue
            survivors.append(item)
            continue
        record = self._build_record(item, batch_id, StageStatus.S4_PENDING)
        self._tracking_store.mark_stage_pending(record, StageStatus.S4_PENDING)
        try:
            staged = self._assembler.assemble(item.document)
        except (SourceFileMissingError, PDFAssemblyFailedError) as exc:
            self._tracking_store.mark_stage_failed(txn, batch_id, StageStatus.S4_FAILED, str(exc))
            failed += 1
            continue
        self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S4_DONE)
        item.staged_file = staged
        survivors.append(item)
    return survivors, failed
```

### 4.6 `_stage_s5`

```python
def _stage_s5(self, items, batch_id):
    s5_done = 0
    failed = 0
    for item in items:
        txn = item.document.txn_num
        assert item.mapping is not None and item.metadata is not None and item.staged_file is not None
        if self._tracking_store.is_stage_done(txn, batch_id, StageStatus.S5_DONE):
            s5_done += 1
            continue
        record = self._build_record(item, batch_id, StageStatus.S5_PENDING)
        self._tracking_store.mark_stage_pending(record, StageStatus.S5_PENDING)
        try:
            cm_object_id = self._uploader.upload(
                file=item.staged_file,
                folder_path=item.mapping.cm_folder,
                object_type_id=item.mapping.cm_object_type,
                document_name=f"{txn}.pdf",
                mime_type="application/pdf",
                properties=dict(item.metadata.properties),
            )
        except (CMISClientError, CMISServerError, RetriesExhaustedError) as exc:
            self._tracking_store.mark_stage_failed(txn, batch_id, StageStatus.S5_FAILED, str(exc))
            failed += 1
            continue
        self._tracking_store.mark_stage_done(txn, batch_id, StageStatus.S5_DONE)
        item.cm_object_id = cm_object_id
        s5_done += 1
    return s5_done, failed
```

### 4.7 `_build_record`

```python
def _build_record(self, item, batch_id, stage):
    return MigrationRecord(
        trigger_shortname=item.trigger.shortname,
        trigger_cif=item.trigger.cif or "",
        trigger_system_id=item.trigger.system_id,
        rvabrep_txn_num=item.document.txn_num,
        rvabrep_file_name=item.document.file_name,
        batch_id=batch_id,
        status=stage,
        created_at=datetime.now(),
        cm_folder=item.mapping.cm_folder if item.mapping else None,
        cm_object_type=item.mapping.cm_object_type if item.mapping else None,
        source_file_path=str(item.staged_file.path) if item.staged_file else None,
        page_count=item.staged_file.page_count if item.staged_file else None,
        file_size_bytes=item.staged_file.size_bytes if item.staged_file else None,
    )
```

### 4.8 ITrackingStore port amendment

In `src/cmcourier/domain/ports.py`:

```python
class ITrackingStore(ABC):
    ...
    @abstractmethod
    def list_txn_nums_for_batch(self, batch_id: str) -> set[str]:
        """Return every rvabrep_txn_num currently tracked under batch_id."""
```

In `src/cmcourier/adapters/tracking/sqlite.py`:

```python
def list_txn_nums_for_batch(self, batch_id: str) -> set[str]:
    try:
        rows = self._reader.execute(
            "SELECT DISTINCT rvabrep_txn_num FROM migration_log WHERE batch_id = ?",
            (batch_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise TrackingError("list_txn_nums_for_batch failed", batch_id=batch_id) from exc
    return {row[0] for row in rows}
```

---

## 5. Test plan

### 5.1 Fixture strategy

A `tests/integration/pipeline/conftest.py` builds a **pipeline harness**
fixture that wires every collaborator from the existing fixtures, plus a
SQLite tracking store in `tmp_path`. The harness exposes:
- The orchestrator instance.
- The underlying tracking store (for assertions).
- The CMIS uploader (for `responses` registration).
- A `_register_cmis_stubs(scenarios)` helper that pre-stubs the warmup +
  folder creation + upload responses for a list of expected docs.

New CSV fixtures under `tests/fixtures/pipeline/`:
- `triggers.csv` — 4 triggers.
- `triggers_unmapped.csv` — trigger that resolves to a doc whose
  `id_rvi` is not in `modelo_documental.csv`.
- (Mapping / metadata sources reuse `tests/fixtures/services/` — no
  duplication.)
- (RVABREP source reuses `tests/fixtures/services/rvabrep_index_sample.csv`.)
- (Page binaries reuse `tests/fixtures/assembly/`.)

The test harness wires `assembler.source_root` to
`tests/fixtures/assembly/paged_tiff` (and similar paths for each test
case that exercises S4).

### 5.2 Tests in `tests/integration/pipeline/test_csv_trigger_pipeline.py`

Grouped tests (~20):

| Group | Tests | Acceptance scenarios |
|-------|-------|----------------------|
| `TestPortAmendment` (in SQLite tests) | 2 | 4.13 + empty-set return |
| `TestParameterValidation` | 4 | REQ-006 / REQ-007 (4 invalid combinations) |
| `TestFreshFullRun` | 3 | 4.1 + RunReport invariants + complete_batch called |
| `TestS1ErrorHandling` | 2 | 4.2 + IndexingError → ERROR log, no row |
| `TestCrossBatchSkip` | 2 | 4.3, 4.16 |
| `TestStageFailures` | 4 | 4.4, 4.5, 4.6, 4.7 |
| `TestResume` | 3 | 4.8, 4.9, 4.10 |
| `TestHeterogeneous` | 1 | 4.11 |
| `TestS0Failure` | 1 | 4.12 |
| `TestHealedCIF` | 1 | 4.15 |

Total: 20 orchestrator tests + 2 in the existing
test_sqlite_tracking_store.py for the port amendment.

### 5.3 Patterns

- Each test that requires CMIS interaction is decorated with
  `@responses.activate` and the harness's
  `_register_cmis_stubs` is called before `run`.
- Resume tests: a first `run(...)` call seeds state, then a second
  `run(...)` with `batch_id=` + `from_stage=` exercises the resume
  semantics. The same `pipeline_harness` fixture is used across both
  calls (same tracking store instance).
- For `TestCrossBatchSkip`, the SQLite tracking store is constructed
  with a pre-seeded row at `S5_DONE` in a previous batch (raw SQL
  insertion in the test setup, or a first complete pipeline run).

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..002 (port amendment) | §4.8 | TestPortAmendment + Test 4.13 |
| REQ-003..004 (construction) | §3.3 | construction smoke (in TestParameterValidation) |
| REQ-005..007 (run signature) | §4.1 | TestParameterValidation |
| REQ-008..009 (S0) | §4.2 | TestS0Failure |
| REQ-010..011 (S1 + cross-batch) | §4.2 | TestS1ErrorHandling, TestCrossBatchSkip |
| REQ-012..013 (resume) | §4.1 | TestResume |
| REQ-014..018 (S2..S5) | §4.3-§4.6 | TestFreshFullRun, TestStageFailures |
| REQ-019..020 (finalization) | §4.1 | TestS0Failure (complete_batch NOT called); TestHeterogeneous (called once) |
| REQ-021..022 (RunReport) | §3.1 | every test asserts on RunReport fields |
| REQ-023..024 (logging) | §4.2-§4.6 | TestS1ErrorHandling + TestCrossBatchSkip caplog assertions |
| NFR-003 (coverage) | — | `pytest --cov` |
| NFR-004 (50-line cap) | — | Visual review of every method |

---

## 7. Files touched

```
NEW   src/cmcourier/orchestrators/csv_trigger.py
EDIT  src/cmcourier/orchestrators/__init__.py
EDIT  src/cmcourier/domain/ports.py                 # port amendment
EDIT  src/cmcourier/adapters/tracking/sqlite.py     # implementation
EDIT  tests/integration/adapters/test_sqlite_tracking_store.py  # 2 new tests
EDIT  tests/unit/domain/test_ports.py               # method name in abstract set
NEW   tests/integration/pipeline/conftest.py
NEW   tests/integration/pipeline/test_csv_trigger_pipeline.py
NEW   tests/fixtures/pipeline/triggers.csv
NEW   tests/fixtures/pipeline/triggers_unmapped.csv
EDIT  CHANGELOG.md                                  # [0.13.0]
EDIT  README.md                                     # Status checklist
NEW   specs/011-csv-trigger-pipeline/{spec,plan,tasks}.md
```

No new dependencies. All adapters / services from changes 003-010 are
the building blocks.

---

## 8. Risks

- **Risk**: the orchestrator's per-stage loops have nearly identical
  shape (~25 lines each). Tempting to abstract into a generic
  `_run_stage(items, stage_pending, stage_done, stage_failed,
  do_work_fn)` template method. Avoid this for now — Constitution III
  rule of three. Three identical bodies are still under the abstraction
  budget. Revisit only if a 4th pipeline (rvabrep / as400 / local-scan)
  shares the body literally.
- **Risk**: rehydrating already-done items across stages requires
  re-calling services (mapping, metadata, assembler). For idempotent
  services this is correct; for assembler it means re-writing the PDF
  to disk on every resume. Acceptable for MVP — the cost is bounded
  by batch size.
- **Risk**: `_StageItem` is mutable, breaking the project's
  "frozen dataclasses everywhere" pattern. This is an intentional
  exception — the item carries per-doc state through stages, and
  fields fill in monotonically. Frozen dataclasses with `replace()` per
  stage would double the allocation cost without adding safety.
- **Risk**: error paths in S2-S5 lose `__cause__` chain (we
  stringify `exc`). Mitigation: the underlying exceptions are logged
  before stringification; the operator has both the message in
  tracking AND the typed log line.

---

## 9. Estimated effort

- Spec / plan / tasks: done
- Phase 1 (port amendment + 2 tests): ~30 min
- Phase 2 (pipeline fixtures + ~20 RED tests): ~150 min
- Phase 3 (impl GREEN): ~120 min
- Phase 4 (verification): ~25 min
- Phase 5 (docs + commit + merge): ~20 min
- **Total**: ~5 h 25 min — the largest single change of the project.

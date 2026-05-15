# Spec — 008-indexing-service

**Status**: Draft
**Stage**: S1 — RVABREP Indexing
**Constitution alignment**: Principle I (hexagonal), II (idempotency surfaces but not authority), III (single-responsibility service), VI (real test pyramid via TabularDataSource).

---

## 1. Intent

Provide `IndexingService` — the concrete implementation of Stage S1. Given a
`TriggerRecord`, find every non-deleted `RVABREPDocument` that matches the
trigger and return it as a typed domain object. The service is the engine the
`rvabrep-pipeline`, `csv-trigger-pipeline`, `as400-trigger-pipeline`, and
`local-scan-pipeline` use after S0 emits triggers.

This change closes the **service triangle** (Mapping S2 + Metadata S3 +
Indexing S1) that every pipeline depends on before any orchestrator can be
wired.

---

## 2. Scope

### In scope

- A `services/indexing.py` module exporting `IndexingService` and
  `IndexingColumnsConfig`.
- Single-trigger lookup: `find_documents(trigger) -> list[RVABREPDocument]`.
- Batched lookup: `find_documents_batch(triggers) -> Iterator[tuple[TriggerRecord, list[RVABREPDocument]]]`
  — uses `IDataSource.get_by_fields_in()` to chunk shortnames in IN-lists of
  50.
- Deleted-row filtering: rows where `delete_code != ""` are excluded.
- Duplicate `txn_num` handling: WARNING log + first-wins (matches
  `MappingService` precedent for duplicate `ID RVI`, the spec).
- Typed error raising: `RVABREPNotFoundError`, `RVABREPDeletedError`.
- A configurable column map (`IndexingColumnsConfig`) so the same service
  works against AS400 (physical names `ABABCD`, `ABAACD`, …) and against a
  CSV fixture (friendly names like `index1`, `system_code`).
- Unit tests against `TabularDataSource` over CSV fixtures (Constitution
  Principle VI: real adapter, no IDataSource mocks).

### Out of scope

- AS400 ODBC adapter — that change ships separately (post-MVP per
  `docs/roadmap/POST-MVP.md`).
- CIF filtering: the trigger's `cif` field is **not** used in the WHERE
  clause. Reason: the spec designates CIF self-healing as a Stage S3
  responsibility. Filtering by CIF here would either reject legitimate docs
  when the trigger's CIF is missing, or duplicate CIF resolution logic
  across two stages.
- Streaming a flat iterator of `RVABREPDocument` (without the originating
  trigger). The batched API yields `(TriggerRecord, list[...])` because
  downstream stages (S2 mapping, S3 metadata) need the trigger to remain
  bound to its documents.
- Cache layer in front of the data source: Modelo Documental is small and
  cached at construction by `MappingService`; RVABREP is too large to fully
  prefetch. Lookups go to the adapter every time.

---

## 3. Functional requirements (RFC 2119)

### Construction

- **REQ-001** The constructor MUST accept an `IDataSource`, an
  `IndexingColumnsConfig`, and an optional `batch_size: int = 50`.
- **REQ-002** The constructor MUST NOT execute any query against the data
  source. The service is lazy: queries fire on `find_documents` /
  `find_documents_batch`.
- **REQ-003** `IndexingColumnsConfig` MUST be a `frozen=True, slots=True`
  dataclass exposing field names for: `shortname_column`, `system_id_column`,
  `txn_num_column`, `delete_code_column`, plus every other column the
  service maps onto `RVABREPDocument`. Defaults MUST match the spec
  physical column names (`ABABCD`, `ABAACD`, `ABAANB`, `ABACST`, …).

### Single-trigger lookup

- **REQ-004** `find_documents(trigger: TriggerRecord) -> list[RVABREPDocument]`
  MUST return every non-deleted RVABREP row matching `trigger.shortname` AND
  `trigger.system_id`.
- **REQ-005** The returned list MUST preserve the order returned by the
  underlying data source.
- **REQ-006** Rows with non-empty `delete_code` MUST be filtered out of the
  result.
- **REQ-007** If the data source returns zero rows for the trigger, the
  service MUST raise `RVABREPNotFoundError(shortname, system_id)`.
- **REQ-008** If the data source returns at least one row but every row has
  non-empty `delete_code`, the service MUST raise
  `RVABREPDeletedError(shortname, system_id, deleted_count)`.
- **REQ-009** If two or more rows share the same `txn_num`, the service MUST
  log a `WARNING` naming the duplicate `txn_num`, the trigger shortname, and
  the count; the FIRST occurrence is kept and subsequent occurrences are
  dropped silently (matches `MappingService` the spec precedent).

### Batched lookup

- **REQ-010** `find_documents_batch(triggers: Iterable[TriggerRecord]) -> Iterator[tuple[TriggerRecord, list[RVABREPDocument]]]`
  MUST yield exactly one `(trigger, docs)` pair per input trigger.
- **REQ-011** The service MUST chunk `triggers` into groups of at most
  `batch_size` and issue ONE `get_by_fields_in` call per chunk against the
  data source.
- **REQ-012** Triggers that resolve to zero non-deleted rows MUST be yielded
  with an empty list `[]` — `find_documents_batch` does NOT raise on
  per-trigger missing/deleted; that policy belongs to the orchestrator (which
  uses the typed errors from `find_documents` for single-trigger paths).
- **REQ-013** Triggers grouped in the same batch but with different
  `system_id` MUST still produce correct per-trigger results — the batched
  query returns rows for the union of shortnames; the service groups results
  by `(shortname, system_id)` in Python before yielding.
- **REQ-014** If a trigger appears twice in the input iterable, the service
  MUST yield it twice — input order is preserved.

### Column mapping

- **REQ-015** The service MUST translate adapter rows (dict with keys named
  per `IndexingColumnsConfig`) into `RVABREPDocument` instances by reading
  each field via the configured column name.
- **REQ-016** Date fields (`creation_date`, `last_view_date`) MUST be parsed
  via `parse_cymmdd`. A `last_view_date` of `"0"` or empty string MUST be
  stored as `None`.
- **REQ-017** Integer fields (`total_pages`) MUST be coerced via `int()`.
  A value of `None` or empty string MUST be coerced to `0`.
- **REQ-018** Every other field MUST be coerced to `str()` (defensive against
  pandas / pyodbc returning ints when a value looks numeric).

### Error wrapping

- **REQ-019** Any exception raised by the underlying `IDataSource` MUST be
  re-raised as `IndexingError` with structured context (`shortname`,
  `system_id`, plus the original exception via `from`).
- **REQ-020** `RVABREPNotFoundError`, `RVABREPDeletedError`, and the
  duplicate WARNING path MUST NOT be wrapped in `IndexingError` — they are
  the typed domain results of the service.

### Logging discipline (Constitution VIII)

- **REQ-021** Logs MUST identify field NAMES and operational keys (column
  names, `shortname`, `txn_num`) but MUST NOT log VALUES of `cif`,
  `index2..6`, or any free-text indexed field.

---

## 4. Acceptance scenarios

### 4.1 Vanilla single-trigger lookup
- Given a `TabularDataSource` over a CSV with 3 rows matching
  `(shortname='JUANPEREZ01', system_id='1')`, none deleted.
- When `find_documents(TriggerRecord(shortname='JUANPEREZ01', cif=None, system_id='1'))` is called.
- Then the service returns a list of 3 `RVABREPDocument` instances, in CSV
  row order.

### 4.2 Single-trigger not found
- Given a CSV with no row matching `('UNKNOWN', '1')`.
- When `find_documents` is called.
- Then the service raises `RVABREPNotFoundError` with context
  `shortname='UNKNOWN'`, `system_id='1'`.

### 4.3 Single-trigger all deleted
- Given a CSV with 2 rows matching the trigger, both with `delete_code='D'`.
- When `find_documents` is called.
- Then the service raises `RVABREPDeletedError` with `deleted_count=2`.

### 4.4 Single-trigger mixed deleted
- Given a CSV with 3 rows matching: 1 active + 2 with `delete_code='D'`.
- When `find_documents` is called.
- Then the service returns a list of length 1 (the active row), no error.

### 4.5 CIF is ignored
- Given a CSV where one row has `cif=123456` and another has `cif=999999`,
  both with the same `(shortname, system_id)`.
- When `find_documents` is called with `TriggerRecord(cif=None)`.
- Then both rows are returned (CIF does not filter).
- And when called with `TriggerRecord(cif='123456')`, the result is the same
  (CIF still does not filter).

### 4.6 Duplicate txn_num — WARNING + first-wins
- Given a CSV with 2 rows sharing the same `txn_num`, both non-deleted.
- When `find_documents` is called.
- Then the service returns a list of length 1 (first row) AND emits a
  `WARNING` log line naming the duplicate `txn_num`, the trigger
  `shortname`, and count `2`.

### 4.7 Batched lookup over 100 triggers
- Given 100 triggers and `batch_size=50`.
- When `find_documents_batch(triggers)` is consumed.
- Then exactly 2 `get_by_fields_in` calls are issued against the adapter
  (instrumentable by wrapping the adapter), and the iterator yields exactly
  100 `(trigger, list)` pairs in input order.

### 4.8 Batched lookup, mixed missing
- Given 3 triggers: 2 with matching rows, 1 with no match.
- When `find_documents_batch(triggers)` is consumed.
- Then 3 pairs are yielded; the missing one has `docs == []`. No exception
  is raised.

### 4.9 Batched lookup, same shortname different system_id
- Given two triggers `(JUANPEREZ01, '1')` and `(JUANPEREZ01, '5')` and
  RVABREP rows under both system_ids.
- When `find_documents_batch` is consumed.
- Then each trigger gets exactly the docs under its system_id, not the
  union.

### 4.10 Adapter exception wrapping
- Given an adapter whose `get_by_fields` raises a synthetic `RuntimeError`.
- When `find_documents` is called.
- Then `IndexingError` is raised, with the `RuntimeError` accessible via
  `__cause__`.

### 4.11 Date and pages coercion
- Given a CSV row with `creation_date='1251117'`, `last_view_date='0'`,
  `total_pages='540'`.
- When the service builds the `RVABREPDocument`.
- Then `creation_date == datetime(2025, 11, 17)`, `last_view_date is None`,
  `total_pages == 540`.

### 4.12 Config defaults match the spec
- Given an `IndexingColumnsConfig()` with no overrides.
- Then `shortname_column == 'ABABCD'`, `system_id_column == 'ABAACD'`,
  `txn_num_column == 'ABAANB'`, `delete_code_column == 'ABACST'`, …
  (matching the spec).

---

## 5. Non-functional requirements

- **NFR-001** Single-trigger lookup latency MUST be a single
  `get_by_fields(filters={shortname, system_id})` call. No iteration over
  the full RVABREP — the adapter is responsible for filtering at source.
- **NFR-002** Batched lookup MUST issue at most `ceil(N / batch_size)`
  queries for N input triggers (one IN-list query per chunk).
- **NFR-003** Memory: batched lookup buffers at most `batch_size` rows of
  trigger metadata plus the rows of one chunk's worth of RVABREP. No
  materialization of the full RVABREP scan.
- **NFR-004** Branch coverage on `services/indexing.py` MUST be ≥ 95%.
- **NFR-005** Function length cap (Constitution III): every method ≤ 50
  lines.

---

## 6. Tooling expectations

- `ruff check src/ tests/`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.services.*`: clean.
- `pre-commit run --all-files`: clean.
- `pytest`: full suite passes; net positive test count.

---

## 7. Open questions / risks

- **Risk**: AS400 ODBC adapter does not exist yet. Mitigation: tests use
  `TabularDataSource` over CSV fixtures (the spec column names are just
  strings; the test fixture can use them verbatim or the friendly names via
  `IndexingColumnsConfig` overrides — both paths are tested).
- **Risk**: `get_by_fields_in` on `TabularDataSource` is the first real
  caller. Mitigation: smoke test in the batched-lookup tests will exercise
  it. If a regression surfaces, fix in `adapters/sources/tabular.py` within
  this change (the adapter pre-dates this service but its IN-list path is
  under-tested).
- **Open question**: should the service expose `find_one(txn_num) -> RVABREPDocument`
  for the future `single-doc` pipeline? **Resolved**: out of scope for 008;
  add as a follow-up change when `single-doc` lands.

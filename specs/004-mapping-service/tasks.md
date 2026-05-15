# Tasks — 004-mapping-service

**Status**: Draft (under review)
**Spec**: `specs/004-mapping-service/spec.md`
**Plan**: `specs/004-mapping-service/plan.md`

---

## Phase 1 — Fixture

- [ ] **1.1** Create `tests/fixtures/services/` directory.
- [ ] **1.2** Create `tests/fixtures/services/modelo_documental.csv` per `plan.md §5.1` (8 rows: 1 vanilla, 1 multi-metadata, 1 empty METADATOS, 1 whitespace METADATOS, 1 trailing-comma, 1 doubled-comma, 1 duplicate FF17, 1 empty ID RVI).

---

## Phase 2 — Tests (RED)

- [ ] **2.1 (R)** Create `tests/unit/services/test_mapping.py` with the test class shape from `plan.md §5.2`. Cover all REQ-019..024 scenarios.
- [ ] **2.2 (R)** Run `pytest tests/unit/services/test_mapping.py -v`. Confirm every test fails with `ImportError` (mapping module doesn't exist yet).

---

## Phase 3 — Implementation (GREEN)

- [ ] **3.1 (G)** Create `src/cmcourier/services/mapping.py` per `plan.md §4` — module docstring + `__all__` + imports + `MappingColumnsConfig` dataclass + helpers `_is_blank`, `_parse_metadata_list` + `MappingService` class with `__init__`, `_load`, `_validate_columns`, `get_mapping`, `get_all`, `count`, `__contains__`.
- [ ] **3.2 (G)** Update `src/cmcourier/services/__init__.py` to re-export `MappingColumnsConfig` and `MappingService`.
- [ ] **3.3 (G)** Run `pytest tests/unit/services/test_mapping.py -v`. Iterate until all tests pass.
- [ ] **3.4 (Rf)** Refactor if any duplication or unclear naming surfaces.

---

## Phase 4 — Verification

- [ ] **4.1** `ruff check src/ tests/` — clean.
- [ ] **4.2** `ruff format --check src/ tests/` — clean (or apply `ruff format src/ tests/`).
- [ ] **4.3** `mypy src/cmcourier/` — clean (strict on `cmcourier.services.*` per existing override).
- [ ] **4.4** `pytest --cov=src/cmcourier --cov-report=term-missing` — coverage on `services/mapping.py` ≥ 95%; total ≥ 80%.
- [ ] **4.5** `pre-commit run --all-files` — clean.
- [ ] **4.6** Full `pytest -v` — all suites green (148 + 16 = ~164 tests).

---

## Phase 5 — Docs + commit

- [ ] **5.1** Update `CHANGELOG.md` with `[0.6.0]` block per `plan.md §6`.
- [ ] **5.2** Update `README.md` Status checklist: tick "Fourth change: first service (mapping)".
- [ ] **5.3** PII grep on new files. Confirm only synthetic identifiers.
- [ ] **5.4** Stage all files. Confirm git status matches:
  ```
  modified: README.md
  modified: CHANGELOG.md
  modified: src/cmcourier/services/__init__.py
  added: src/cmcourier/services/mapping.py
  added: tests/unit/services/test_mapping.py
  added: tests/fixtures/services/modelo_documental.csv
  added: specs/004-mapping-service/{spec,plan,tasks}.md
  ```
- [ ] **5.5** Commit:
  ```
  feat(services): add MappingService over Modelo Documental

  First service-layer class in CMCourier. Caches the Modelo Documental
  from any IDataSource at construction and exposes get_mapping(id_rvi),
  get_all(), count(), and __contains__. Duplicate ID RVI rows obey
  the the spec first-wins rule and emit a WARNING log entry.
  Empty-ID-RVI rows are silently skipped (counted at INFO level).

  Validates the hexagonal architecture end-to-end: services/mapping.py
  imports only cmcourier.domain.* (no adapters), tests wire a real
  TabularDataSource against a CSV fixture, the service raises the
  domain-defined IDRViNotMappedError on cache miss.

  METADATOS parsing handles whitespace, trailing commas, doubled
  commas, and empty cells consistently. Field aliases (CIF → BAC_CIF
  per the spec) are NOT handled here — that is metadata service
  responsibility (later change).

  Verification:
  - pytest -v: 16 new tests + 148 existing all pass
  - coverage on services/mapping.py: XX%
  - ruff / mypy: clean
  - pre-commit: clean

  Constitution Principle I held: services depend on ports, not
  adapters. Test files import the adapter (test wiring is not the SUT).

  Closes specs/004-mapping-service/.
  ```

---

## Phase 6 — Optional PR / merge

- [ ] **6.1** Standard branch-pr workflow OR FF merge to main + delete branch.

---

## Verification mapping

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..008 (class) | 3.1 + tests 2.1 |
| REQ-009..014 (API) | 3.1 + tests 2.1 |
| REQ-015..018 (METADATOS) | 3.1 (`_parse_metadata_list`) + parametrized tests |
| REQ-019..024 (tests + coverage) | 2.1, 3.3, 4.4, 4.6 |
| REQ-025..027 (tooling) | 4.1..4.3, 4.5 |

| Acceptance scenario | Tasks |
|---------------------|-------|
| 4.1 vanilla lookup | `test_get_mapping_vanilla` |
| 4.2 unknown raises | `test_get_mapping_unknown_raises` |
| 4.3 duplicate first wins + warning | `test_duplicate_id_rvi_first_wins` + `test_duplicate_emits_warning` |
| 4.4 empty id_rvi skipped | `test_empty_id_rvi_row_skipped` + `test_empty_id_rvi_emits_info` |
| 4.5 missing column | `test_missing_required_column_raises` |
| 4.6 custom columns | `test_custom_columns` |
| 4.7 METADATOS edge cases | parametrized `test_metadata_*` |
| 4.8 `__contains__` | `test_contains` |
| 4.9 no PII | 5.3 |

---

## Estimated effort

- Phase 1: 5 min
- Phase 2: 30 min
- Phase 3: 30 min
- Phase 4: 10 min
- Phase 5: 15 min
- **Total**: ~1 h 30 min focused work.

---

## Notes for the implementor

- Constitution Principle I: `services/mapping.py` MUST NOT import from `cmcourier.adapters.*`. Verified at runtime by behavior; verified statically by mypy on the file.
- Logging: use `logging.getLogger(__name__)` at module level. No format string PII concern — `id_rvi` is a document-class code, not customer data.
- `caplog` test fixture: set `caplog.set_level(logging.WARNING)` (or `INFO`) before constructing the service so the records are captured.
- The test for the duplicate warning must NOT depend on log MESSAGE text exactly — assert on `caplog.records[0].levelno == logging.WARNING` and `"DUPLICATE_ID" in caplog.records[0].getMessage()` or similar (but use the actual id_rvi value `"FF17"` since the fixture uses it).
- 50-line function cap holds. `_load` is the longest method (~25 lines).

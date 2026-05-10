# Tasks — 006-trigger-service

**Status**: Draft (under review)
**Spec**: `specs/006-trigger-service/spec.md`
**Plan**: `specs/006-trigger-service/plan.md`

---

## Phase 1 — Fixtures

- [ ] **1.1** `tests/fixtures/services/triggers/trigger_list.csv` (5 rows: 4 valid + 1 blank ShortName).
- [ ] **1.2** `tests/fixtures/services/triggers/trigger_list_alt_columns.csv` (Cliente / Doc / Sistema columns; 1 row).
- [ ] **1.3** `tests/fixtures/services/triggers/trigger_list_missing_col.csv` (missing ShortName column).
- [ ] **1.4** `tests/fixtures/services/triggers/rvabrep_export.csv` (8 rows: 4 unique `(shortname, system_id)` + 1 blank ShortName + various `id_rvi` values for filter tests).

---

## Phase 2 — Tests RED

- [ ] **2.1 (R)** Create `tests/unit/services/test_trigger_strategies.py` with three test classes: `TestCsvTriggerStrategy`, `TestDirectRvabrepTriggerStrategy`, `TestStubStrategies`. Cover REQ-006..024.
- [ ] **2.2 (R)** Run pytest. Confirm ImportError on every test.

---

## Phase 3 — Implementation GREEN

- [ ] **3.1 (G)** Create `src/cmcourier/services/triggers/__init__.py` (re-exports — placeholder until impls land).
- [ ] **3.2 (G)** `src/cmcourier/services/triggers/csv.py` per plan §4.1.
- [ ] **3.3 (G)** `src/cmcourier/services/triggers/direct_rvabrep.py` per plan §4.2.
- [ ] **3.4 (G)** `src/cmcourier/services/triggers/stubs.py` per plan §4.3.
- [ ] **3.5 (G)** Update `src/cmcourier/services/triggers/__init__.py` re-exports.
- [ ] **3.6 (G)** Update `src/cmcourier/services/__init__.py` to re-export the 7 new public names.
- [ ] **3.7 (G)** Run pytest, iterate until all tests pass.
- [ ] **3.8 (Rf)** Refactor as needed; ensure 50-line function cap.

---

## Phase 4 — Verification

- [ ] **4.1** `ruff check src/ tests/` — clean.
- [ ] **4.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **4.3** `mypy src/cmcourier/` — clean (strict on services.*).
- [ ] **4.4** `pytest --cov=src/cmcourier --cov-report=term` — coverage on `services/triggers/*` ≥ 95%, total ≥ 80%.
- [ ] **4.5** `pre-commit run --all-files` — clean.

---

## Phase 5 — Docs + commit

- [ ] **5.1** Update `CHANGELOG.md` `[0.8.0]` per plan §6.
- [ ] **5.2** Update `README.md` Status checklist: tick "Sixth change: TriggerService".
- [ ] **5.3** PII grep on new files. Synthetic only.
- [ ] **5.4** Stage all files. Confirm git status matches.
- [ ] **5.5** Commit:
  ```
  feat(services): add S0 trigger strategies (CSV, RVABREP, stubs)

  Concrete S0Strategy implementations for stage S0 (Trigger Acquisition)
  per REBIRTH §5.1.

  CsvTriggerStrategy reads triggers from any tabular IDataSource. Validates
  required columns at first row; yields TriggerRecord per non-blank row;
  treats blank CIF as None (CIF self-healing in stage S3 covers it).

  DirectRvabrepTriggerStrategy scans RVABREP itself with optional filters
  (systems + document_types). Deduplicates (shortname, system_id) pairs
  with first-occurrence-wins (matches REBIRTH §4.3 / MappingService
  precedent).

  As400TriggerStrategy and LocalScanTriggerStrategy are concrete
  S0Strategy stubs whose acquire() raises NotImplementedError with
  messages naming their missing dependencies. Construction succeeds so
  orchestrators can dispatch and surface the error late, matching the
  pattern from as400:<alias> in 005.

  No TriggerService wrapper class — the S0Strategy port already represents
  the abstraction; orchestrators instantiate strategies directly.

  Verification:
  - pytest -v: all tests pass (~219 total = 201 + ~18 new)
  - coverage on services/triggers/*: XX% branch (target ≥95%)
  - ruff / mypy --strict: clean
  - pre-commit: clean

  Constitution Principle I: services/triggers/ imports cmcourier.domain.*
  + stdlib only. Principle VIII: cif VALUES never logged.

  Closes specs/006-trigger-service/.
  ```

---

## Verification mapping

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..005 | 3.1..3.6 |
| REQ-006..013 | 3.2 + tests |
| REQ-014..021 | 3.3 + tests |
| REQ-022..024 | 3.4 + tests |
| REQ-025..030 | 2.1, 4.4 |
| REQ-031..033 | 4.1..4.5 |

---

## Estimated effort

- Phase 1: 10 min
- Phase 2: 60 min
- Phase 3: 60 min
- Phase 4: 15 min
- Phase 5: 15 min
- **Total**: ~2 h 40 min focused work.

---

## Notes

- Constitution Principle I: NO adapter imports in services/triggers/. Tests have them (wiring).
- 50-line function cap: `acquire` is ~30 lines for CSV / RVABREP; `_iter_filtered_rows` is ~20 lines. All well under 50.
- The `del source_descriptor` line is intentional — silences the unused-arg warning while documenting "yes, we read it, no, we don't use it".
- The `yield  # pragma: no cover` after the raise in stubs is the Python idiom for "this function is a generator that always raises before yielding". The `# pragma: no cover` tells coverage that the unreachable line is intentionally unreachable.

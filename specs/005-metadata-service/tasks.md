# Tasks — 005-metadata-service

**Status**: Draft (under review)
**Spec**: `specs/005-metadata-service/spec.md`
**Plan**: `specs/005-metadata-service/plan.md`

---

## Phase 1 — Fixtures

- [ ] **1.1** Create `tests/fixtures/services/metadata/` directory.
- [ ] **1.2** Create `clients.csv` per plan §5.1 (CIF, Nombre_Cliente, Tipo_Cliente — 3 rows).
- [ ] **1.3** Create `accounts.csv` per plan §5.1 (CIF, Num_Cuenta — 2 rows; one CIF that exists in `clients.csv`, one that does not).
- [ ] **1.4** Create `cards.csv` per plan §5.1 (CIF, Num_Cuenta_Tarjeta — 2 rows).

---

## Phase 2 — Tests RED

- [ ] **2.1 (R)** Create `tests/unit/services/test_metadata.py` with the test class + ~22 tests per plan §5.2:
  - Construction + pre-fetch (3 tests)
  - Vanilla resolution per source type (3 tests)
  - Fallback chain (5 tests)
  - CIF self-healing (4 tests)
  - Aliases (3 tests)
  - Source dispatch (3 tests)
  - Type immutability (2 tests)
- [ ] **2.2 (R)** Add `_CountingSource` test helper class for the pre-fetch-reduces-calls scenario.
- [ ] **2.3 (R)** Run `pytest tests/unit/services/test_metadata.py -v`. Confirm every test fails with `ImportError`.

---

## Phase 3 — Dataclasses + helpers

- [ ] **3.1 (G)** Create `src/cmcourier/services/metadata.py` with module docstring, `__all__`, imports, logger.
- [ ] **3.2 (G)** Define the five frozen dataclasses (`ValidationConfig`, `SourceConfig`, `FieldSourceConfig`, `MetadataConfig`, `MetadataResolution`) per plan §3.1.
- [ ] **3.3 (G)** Implement helper functions: `_validates(value, validation)`, `_normalize_fields(raw_fields)`, source dispatch constants `_CSV_PREFIX`, `_AS400_PREFIX`.
- [ ] **3.4 (G)** Run pytest — the type immutability tests should pass; everything else still fails.

---

## Phase 4 — MetadataService class

- [ ] **4.1 (G)** Implement `MetadataService.__init__` with `prefetch_enabled` branching to `_prefetch_csv_sources()`.
- [ ] **4.2 (G)** Implement `_prefetch_csv_sources` per plan §3.3 (validates aliases exist in registry, builds 4-tuple cache, `setdefault` for first-wins).
- [ ] **4.3 (G)** Implement source dispatch: `_fetch_from_source`, `_fetch_trigger`, `_fetch_rvabrep`, `_fetch_csv` (with cache lookup OR `get_by_fields` fallback when prefetch disabled).
- [ ] **4.4 (G)** Implement `_resolve_one` per plan §3.5 (full fallback chain, default validation, error raising).
- [ ] **4.5 (G)** Implement `resolve` per plan §3.4 (CIF self-healing first, then main loop, returns `MetadataResolution`).
- [ ] **4.6 (G)** Run `pytest tests/unit/services/test_metadata.py -v` — iterate until all 22 tests pass.
- [ ] **4.7 (Rf)** Refactor for clarity: ensure 50-line function cap, helpers named clearly, no duplication.

---

## Phase 5 — Re-exports + verification

- [ ] **5.1 (G)** Update `src/cmcourier/services/__init__.py` to re-export the six new public symbols (`MetadataService`, `MetadataResolution`, `MetadataConfig`, `FieldSourceConfig`, `SourceConfig`, `ValidationConfig`).
- [ ] **5.2** `ruff check src/ tests/` — clean.
- [ ] **5.3** `ruff format src/ tests/` — apply.
- [ ] **5.4** `mypy src/cmcourier/` — clean (services is in strict-mode override).
- [ ] **5.5** `pytest --cov=src/cmcourier --cov-report=term` — total coverage stays ≥ 80%; coverage on `services/metadata.py` ≥ 95%.
- [ ] **5.6** Resolve any `ruff format --check` drift between local venv and pre-commit hook v0.4.10 — see decision below in §"Resolve ruff drift".
- [ ] **5.7** `pre-commit run --all-files` — clean.

---

## Phase 6 — Docs + commit

- [ ] **6.1** Update `CHANGELOG.md` with the `[0.7.0]` block per plan §6.
- [ ] **6.2** Update `README.md` Status checklist: tick the fifth-change milestone.
- [ ] **6.3** PII grep on new files. Synthetic identifiers only (CIFs `123456`, `234567`, `345678`; names `JUAN PEREZ TEST`, `MARIA GOMEZ TEST`, `EMPRESA SA TEST`).
- [ ] **6.4** Stage all files. Confirm git status matches expected list (3 fixtures, 1 metadata.py, 1 test_metadata.py, services/__init__.py modified, CHANGELOG modified, README modified, 3 spec files).
- [ ] **6.5** Commit:
  ```
  feat(services): add MetadataService with fallback chain + CIF self-healing

  Most complex service in CMCourier so far. Implements stage S3 of
  every pipeline: per-field metadata resolution with ordered fallback
  chain, validation regexes (re.fullmatch), default-value fallback,
  field-alias normalization (case-insensitive), and CIF self-healing
  (returns a new TriggerRecord with cif populated when the input had
  cif=None).

  Source types supported: trigger (read TriggerRecord attribute),
  rvabrep (read RVABREPDocument attribute), csv:<alias> (lookup via
  IDataSource). as400:<alias> raises NotImplementedError with a
  message naming the missing AS400 adapter change.

  Pre-fetching of CSV sources happens at construction by default;
  the cache is keyed by (alias, key_column, key_value, value_column)
  so a single CSV source serves multiple fields without re-iterating.
  setdefault preserves first-occurrence on duplicate keys, matching
  MappingService's the spec first-wins precedent.

  Five frozen+slots dataclasses (MetadataConfig, FieldSourceConfig,
  SourceConfig, ValidationConfig, MetadataResolution) carry the
  configuration and result shapes. The service raises domain-defined
  exceptions: ConfigurationError, SourceFailedError, and
  DefaultValidationFailedError.

  Constitution Principle VIII (PII discipline) enforced: logs identify
  field NAMES only, never field VALUES. Customer name, account
  number, and CIF VALUES are PII; the field names "BAC_CIF",
  "BAC_Nombre_Cliente" are not.

  Verification:
  - pytest -v: all tests pass (~191 total = 169 + 22 new)
  - coverage on services/metadata.py: XX% branch (target ≥95%)
  - ruff / mypy --strict: clean
  - pre-commit run --all-files: clean

  Closes specs/005-metadata-service/.
  ```

---

## Resolve ruff drift (planned for this change)

Five changes in a row hit the local-venv-vs-hook-v0.4.10 format drift. Decision for this change: **bump the hook rev** (vs. pinning local ruff). Steps:

- [ ] **Drift.1** Identify the latest stable ruff-pre-commit rev (check upstream).
- [ ] **Drift.2** Update `.pre-commit-config.yaml` `repo: ruff-pre-commit rev:` to that version.
- [ ] **Drift.3** Run `pre-commit run --all-files`. Accept any reformatting.
- [ ] **Drift.4** Run `ruff format --check src/ tests/` from local venv. Confirm 0 drift.
- [ ] **Drift.5** Bump-the-hook is committed AS PART OF this change's implementation commit (not a separate `chore:` because the drift directly affects this change's file count).

If bumping the hook causes new lint errors that we don't want to fix in scope, fall back to pinning local ruff in pyproject.toml dev deps.

---

## Verification mapping

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..008 (types) | 3.2 + immutability tests in 2.1 |
| REQ-009..014 (constructor + pre-fetch) | 4.1, 4.2 + tests in 2.1 |
| REQ-015..022 (resolution flow) | 4.4, 4.5 + tests in 2.1 |
| REQ-023..026 (dispatch) | 4.3 + dispatch tests in 2.1 |
| REQ-027..029 (aliases) | 3.3 (`_normalize_fields`) + tests in 2.1 |
| REQ-030..035 (tests) | 2.1 + 5.5 |
| REQ-036..038 (tooling) | 5.2..5.4, 5.7 |

| Acceptance scenario | Tasks |
|---------------------|-------|
| 4.1 vanilla trigger | `test_trigger_source` |
| 4.2 fallback validation | `test_first_source_fails_validation_second_succeeds` |
| 4.3 default value | `test_all_sources_fail_default_used` |
| 4.4 default fails validation | `test_default_validation_fails_raises` |
| 4.5 CIF self-healing happy | `test_cif_self_healing_happy_path` + `test_self_healed_cif_used_for_subsequent_csv_lookups` |
| 4.6 CIF self-healing failure | `test_cif_self_healing_failure_propagates` |
| 4.7 alias normalization | `test_alias_normalization_case_insensitive` |
| 4.8 unknown field | `test_unknown_field_raises` |
| 4.9 pre-fetch reduces calls | `_CountingSource` assertion |
| 4.10 as400 NotImplementedError | `test_as400_source_raises_not_implemented` |
| 4.11 no PII | 6.3 |

---

## Estimated effort

- Phase 1 (fixtures): 10 min
- Phase 2 (tests RED): 90 min  ← largest because there are 22 tests covering many edge cases
- Phase 3 (dataclasses + helpers): 30 min
- Phase 4 (service class): 60 min
- Phase 5 (verification + ruff drift fix): 30 min
- Phase 6 (docs + commit): 20 min
- **Total**: ~4 hours focused work.

This is the longest change so far. The complexity is in Phase 2 (test breadth) and Phase 4 (resolution flow + self-healing + dispatch + pre-fetch).

---

## Notes for the implementor

- Constitution Principle I: NO adapter imports inside `services/metadata.py`. The test file imports `TabularDataSource` (wiring); the SUT does not.
- 50-line function cap binds. `_resolve_one` is the longest at ~25 lines; `resolve` is ~20. `_prefetch_csv_sources` ~25.
- PII discipline: log field NAMES, never VALUES. Code review must catch any drift here.
- `caplog` test for "no value-leaks in logs" is OPTIONAL but a nice-to-have if the implementor has time. Otherwise rely on visual inspection during code review.
- The `_CountingSource` test helper goes in the same test file (not a shared fixture conftest entry) because it's specific to this change.
- After bumping the ruff hook rev, the test_smoke.py from earlier changes may reformat — that's expected and accepted in this commit.

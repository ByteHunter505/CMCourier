# Tasks — 003-tabular-data-source-adapter

**Status**: Draft (under review)
**Spec**: `specs/003-tabular-data-source-adapter/spec.md`
**Plan**: `specs/003-tabular-data-source-adapter/plan.md`

---

## Phase 1 — Dependency

- [ ] **1.1** Edit `pyproject.toml`. Add `"openpyxl>=3.1,<4.0"` to `[project].dependencies`.
- [ ] **1.2** Run `pip install -e .[dev]` to install `openpyxl`. Confirm no errors.
- [ ] **1.3** Confirm `python -c "import openpyxl; print(openpyxl.__version__)"` works.

---

## Phase 2 — Test fixtures

- [ ] **2.1** Create `tests/fixtures/sources/sample.csv` with the synthetic data described in plan.md §5.1 (header: `Name,Age,Birth`; 5 rows; one row with a blank `Age` cell for `NaN` testing; one row with `Name="JUANPEREZ01"` appearing twice for `get_by_fields` testing).
- [ ] **2.2** Create `tests/fixtures/sources/bad_extension.txt` with arbitrary content.
- [ ] **2.3** Create `tests/fixtures/sources/latin1.csv` with a name field containing characters that fail under UTF-8 (e.g., `"Núñez"`), encoded as Latin-1.
- [ ] **2.4** Update `tests/conftest.py` with the `_generate_xlsx_fixtures` session-scoped autouse fixture per plan.md §5.1. It generates `sample.xlsx` and `multi_sheet.xlsx` if absent.
- [ ] **2.5** Manually run pytest once (no test code yet — just `pytest --collect-only`). Confirm the conftest fixture creates the XLSX files in `tests/fixtures/sources/`.
- [ ] **2.6** Add `tests/fixtures/sources/sample.xlsx` and `multi_sheet.xlsx` to `.gitignore`? **No** — they are deterministic test outputs; alternatively, commit them. Decision: **gitignore them** because regeneration is sub-second and binary diffs in git are noise. Add `tests/fixtures/sources/*.xlsx` to `.gitignore`.

---

## Phase 3 — Integration tests (RED)

- [ ] **3.1 (R)** Create `tests/integration/adapters/test_tabular_data_source.py`. Write the test class skeleton from plan.md §5.2 with:
  - The CSV/XLSX parametrized adapter fixture
  - `test_count`, `test_get_all_yields_dicts`, `test_nan_normalized_to_none`, `test_get_by_fields_equality`, `test_get_by_fields_missing_key_raises`, `test_get_by_fields_in`
  - `test_query_raises`, `test_query_stream_raises`
  - `test_close`, `test_close_is_idempotent`, `test_operation_after_close_raises`
  - `test_unknown_extension_raises`, `test_nonexistent_file_raises`, `test_encoding_override`, `test_encoding_mismatch_raises`
  - `test_multi_sheet_selection`, `test_extension_case_insensitive`
- [ ] **3.2 (R)** Run `pytest -m integration tests/integration/adapters/test_tabular_data_source.py`. Confirm collection succeeds and every test fails with `ImportError` (TabularDataSource doesn't exist yet).

---

## Phase 4 — Implementation (GREEN)

- [ ] **4.1 (G)** Create `src/cmcourier/adapters/sources/tabular.py` with the implementation per plan.md §4 (constructor, dispatch, `_normalize_row`, every IDataSource method).
- [ ] **4.2 (G)** Update `src/cmcourier/adapters/sources/__init__.py` to re-export `TabularDataSource`.
- [ ] **4.3 (G)** Run `pytest -m integration tests/integration/adapters/test_tabular_data_source.py -v`. Iterate until all tests pass. Expect to fix at least one cell-comparison or `NaN` corner case during this loop.
- [ ] **4.4 (Rf)** Refactor `_normalize_row` and the IDataSource methods if any duplication or unclear name surfaces. Ensure 50-line function cap holds (Constitution Principle III).

---

## Phase 5 — Tooling + verification

- [ ] **5.1** Run `ruff check src/ tests/`. Fix any issues.
- [ ] **5.2** Run `ruff format src/ tests/`. Confirm clean.
- [ ] **5.3** Run `mypy src/cmcourier/`. Adapter is in `cmcourier.adapters.*` (baseline mypy, not strict). Fix any errors.
- [ ] **5.4** Run `pytest --cov=src/cmcourier/adapters/sources/tabular --cov-report=term-missing tests/integration/adapters/test_tabular_data_source.py`. Confirm ≥ 90 % branch coverage. If under, add tests for uncovered branches or document the miss.
- [ ] **5.5** Run `pre-commit run --all-files`. Confirm clean.
- [ ] **5.6** Run `pytest -v` (full suite). Confirm 112 unit tests + ~36 integration tests all pass.

---

## Phase 6 — Documentation + commit

- [ ] **6.1** Update `CHANGELOG.md` with the `[0.5.0]` block per plan.md §7.
- [ ] **6.2** Update `README.md` Status checklist: tick `Third change: first concrete adapter (CSV data source)` (rename from "CSV" to "tabular CSV+XLSX" if needed).
- [ ] **6.3** Update `docs/INDEX.md`: under the future "How it works" section, add a placeholder for `docs/explanation/tabular-data-source.md` (deferred — actual content in a later change if it deserves a standalone explanation; for now the spec/plan suffice).
- [ ] **6.4** PII grep:
  ```bash
  grep -rEn '\b\d{6}\b' src/cmcourier/adapters/ tests/integration/adapters/ tests/fixtures/sources/
  grep -rEni '(juan|maria|carlos|jose|laura|martin)\s+(perez|gomez|rodriguez|gonzalez|sanchez|martinez)' src/cmcourier/adapters/ tests/integration/adapters/ tests/fixtures/sources/
  ```
  Confirm only synthetic identifiers (`JUANPEREZ01`).
- [ ] **6.5** Stage all files. Confirm `git status` matches:
  ```
  modified: pyproject.toml
  modified: README.md
  modified: CHANGELOG.md
  modified: tests/conftest.py
  modified: src/cmcourier/adapters/sources/__init__.py
  modified: docs/INDEX.md
  modified: .gitignore
  added: src/cmcourier/adapters/sources/tabular.py
  added: tests/integration/adapters/test_tabular_data_source.py
  added: tests/fixtures/sources/sample.csv
  added: tests/fixtures/sources/bad_extension.txt
  added: tests/fixtures/sources/latin1.csv
  added: specs/003-tabular-data-source-adapter/{spec,plan,tasks}.md
  ```
- [ ] **6.6** Commit:
  ```
  feat(adapters): add TabularDataSource for CSV and XLSX files

  First concrete IDataSource implementation. Dispatches by file extension
  (.csv via pandas.read_csv, .xlsx via pandas.read_excel + openpyxl),
  exposes get_all / count / get_by_fields / get_by_fields_in / close,
  raises NotImplementedError on the SQL methods (tabular sources have no
  SQL surface — callers use field-based methods).

  Always loads as dtype=str to preserve leading zeros and unify type
  semantics across formats. NaN values are normalized to None at the
  port boundary so callers never see pandas-specific sentinels.

  Test fixtures live under tests/fixtures/sources/. CSV/TXT files are
  committed; XLSX files are generated at session start by a conftest
  fixture (deterministic, sub-second) and gitignored.

  openpyxl>=3.1,<4.0 added as a runtime dependency (required by
  pandas.read_excel). Not a constitutional amendment — transitive
  consequence of supporting XLSX, a scope decision the user made
  for this change.

  Verification:
  - pytest -v: 112 unit + ~36 integration pass
  - coverage on adapters/sources/tabular: XX% (target ≥90%)
  - ruff check / format: clean
  - mypy src/cmcourier/: clean
  - pre-commit run --all-files: clean

  Constitution Principle VI: this is the test substitute for AS400.
  AS400 will land in a later change implementing the same IDataSource
  port; both are interchangeable behind the abstraction.

  Closes specs/003-tabular-data-source-adapter/.
  ```

---

## Phase 7 — Optional PR / merge

- [ ] **7.1** Push branch / open PR / merge per project workflow.

---

## Verification mapping (spec REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..010 (class) | 4.1, 4.2 + tests in 3.1 |
| REQ-011..020 (IDataSource methods) | 4.1 + tests in 3.1 |
| REQ-021..024 (dispatch) | 4.1 + `test_unknown_extension_raises`, `test_extension_case_insensitive` |
| REQ-025..032 (tests) | 3.1, 4.3, 5.6 |
| REQ-033 (coverage) | 5.4 |
| REQ-034..035 (mypy / ruff) | 5.1..5.3 |

| Acceptance scenario | Tasks |
|---------------------|-------|
| 4.1 CSV happy path | `test_get_all_yields_dicts` (csv param) |
| 4.2 XLSX same shape | `test_get_all_yields_dicts` (xlsx param) |
| 4.3 NaN → None | `test_nan_normalized_to_none` |
| 4.4 get_by_fields | `test_get_by_fields_equality` |
| 4.5 get_by_fields_in | `test_get_by_fields_in` |
| 4.6 unknown extension | `test_unknown_extension_raises` |
| 4.7 nonexistent file | `test_nonexistent_file_raises` |
| 4.8 SQL methods raise | `test_query_raises`, `test_query_stream_raises` |
| 4.9 operation after close | `test_close`, `test_close_is_idempotent`, `test_operation_after_close_raises` |
| 4.10 multi-sheet XLSX | `test_multi_sheet_selection` |
| 4.11 encoding override | `test_encoding_override`, `test_encoding_mismatch_raises` |

---

## Estimated effort

- Phase 1 (deps): 5 min
- Phase 2 (fixtures): 25 min
- Phase 3 (tests RED): 45 min
- Phase 4 (implementation GREEN): 45 min
- Phase 5 (tooling): 15 min
- Phase 6 (docs + commit): 20 min
- **Total**: ~2 h 35 min focused work.

---

## Notes for the implementor

- The `dtype=str` rule is non-negotiable. Do not be tempted to expose a `dtype` parameter "for flexibility" — it is the wrong abstraction at this layer.
- The conftest fixture is `autouse=True` and `scope="session"`. Do NOT make it a regular fixture that test methods request — the XLSX generation must happen exactly once per pytest session, before any test runs.
- If pandas warns about `keep_default_na`, treat it as a `FutureWarning` to address now (not later) — read the doc for the version we resolved and adjust.
- The mypy hook in `.pre-commit-config.yaml` may need `pandas-stubs` and `types-openpyxl` (if it exists) added to `additional_dependencies` after this change. Verify locally first; if the hook fails, fix `.pre-commit-config.yaml` in the same commit.
- The 50-line function cap binds. If a method approaches 30 lines, look at whether a helper would clarify it.

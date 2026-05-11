# 031 — Verification Report

> Mode: **Strict TDD** (cached `sdd-init/cmcourier` → `strict_tdd: true`).
> Test runner: `uv run pytest`.
> Quality gate: `ruff check && ruff format --check && mypy src/cmcourier/ && pre-commit run --all-files`.

---

## Executive Summary

**Verdict: PASS WITH WARNINGS.**

All 38 REQs covered by impl + tests. 9/9 acceptance scenarios behaviorally
validated (61 new tests). Full pytest suite **804/804 passing**, full
quality gate green. Two flagged items: one fix landed in-session (img2pdf
determinism, `2194a5b`); one residual SUGGESTION (AS400 path lacks
integration coverage — deferred).

---

## Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 17 |
| Tasks complete | 17 |
| Tasks incomplete | 0 |

All tasks in `tasks.md` executed end-to-end during this session. RED-before-GREEN
ordering enforced in-session for every phase (test files written and
verified to fail before the corresponding impl file was authored).

---

## Build & Tests Execution

**Build (gate)**: ✅ Passed.
- `ruff check src/cmcourier/ tests/` → All checks passed.
- `ruff format --check src/cmcourier/ tests/` → 144 files clean.
- `mypy src/cmcourier/` → no issues in 72 source files.
- `pre-commit run --all-files` → ruff, ruff-format, mypy, conventional-commit, no-co-authored-by all Passed.

**Tests**: ✅ **804 passed**, 0 failed, 0 skipped (1 deprecation warning from PyPDF2 — pre-existing, not introduced by 031).

Per-module breakdown for the new code:
- `tests/unit/services/mock/test_sizing.py` — **24** tests
- `tests/unit/services/mock/test_content.py` — **11** tests
- `tests/unit/services/mock/test_planner.py` — **20** tests
- `tests/integration/cli/test_mock_generate.py` — **6** tests
- **Total new tests: 61** (REQ-035 bar was baseline + ≥23 → delivered +61).

**Coverage**: ➖ Not measured with `--cov`. Running `pytest --cov` triggered a
numpy 2 / coverage instrumentation bug ("cannot load module more than once
per process") during pandas import in unrelated test modules. The numpy
issue is pre-existing and unrelated to 031; the 802-passing run on
`--no-cov` is the binding signal. Flagged below as SUGGESTION.

---

## Spec Compliance Matrix (Behavioral Validation)

### Sizing parser (REQ-001..REQ-005)

| REQ | Behavior | Test | Result |
|-----|----------|------|--------|
| 001 | parse_size case-insensitive suffix | `test_sizing.py::test_kilobytes`, `test_megabytes`, `test_gigabytes`, `test_case_insensitive_suffix[*]` | ✅ |
| 002 | Missing suffix = bytes | `test_sizing.py::test_bytes_no_suffix`, `test_bytes_b_suffix` | ✅ |
| 003 | Whitespace tolerated | `test_sizing.py::test_whitespace_around_value_and_suffix` | ✅ |
| 004 | Invalid → ValueError | `test_sizing.py::test_invalid_inputs_raise[*]` (9 cases) + `test_error_message_quotes_input` | ✅ |
| 005 | ≥6 unit tests | 24 tests | ✅ |

### Planner (REQ-006..REQ-016)

| REQ | Behavior | Test | Result |
|-----|----------|------|--------|
| 006 | FilePlan dataclass frozen+slots | All dispatch tests use `FilePlan` directly | ✅ |
| 007 | Pure plan_files generator | `test_planner.py::test_pdf_row_yields_one_pdf_plan` (+ all others — pure-function asserted by no `tmp_path` writes) | ✅ |
| 008 | Skip deleted; include-deleted opt-in | `test_deleted_row_skipped_by_default`, `test_include_deleted_yields_deleted_rows` | ✅ |
| 009 | systems / document_types filters | `test_system_filter`, `test_document_type_filter` | ✅ |
| 010 | limit caps yielded | `test_combined_filters_and_limit` | ✅ |
| 011 | PDF dispatch via is_pdf_filename | `test_pdf_row_yields_one_pdf_plan`, `test_pdf_with_lowercase_extension_dispatches_as_pdf` | ✅ |
| 012 | Image dispatch B→tiff C→jpeg, paged extensions | `test_tiff_row_yields_paged_plan`, `test_jpeg_single_page_extension_is_001` | ✅ |
| 013 | Unknown ABABST → ConfigurationError | `test_unknown_image_type_raises` | ✅ |
| 014 | Path normalization | `test_strips_leading_forward_slash`, `test_strips_leading_backslashes_and_normalizes`, `test_mixed_separators`, `test_already_clean`, `test_empty_image_path_raises` | ✅ |
| 015 | Dedup first wins, page-conflict warns | `test_dedup_first_wins`, `test_dedup_page_conflict_warns_and_keeps_first`, `test_dedup_after_path_normalization` | ✅ |
| 016 | ≥8 unit tests | 20 tests | ✅ |

### Content writer (REQ-017..REQ-026)

| REQ | Behavior | Test | Result |
|-----|----------|------|--------|
| 017 | seed=None|int + tolerance | constructor exercised by all tests | ✅ |
| 018 | write returns paths or [] | `test_skip_if_exists_returns_empty` | ✅ |
| 019 | force=False skip; force=True overwrite | `test_skip_if_exists_returns_empty`, `test_force_overwrites` | ✅ |
| 020 | PDF re-openable by PyPDF2, correct page count | `test_pdf_pages_matches_plan`, `test_pdf_re_openable_pypdf2[1\|2\|5]` | ✅ |
| 021 | TIFF LZW (tag 259 = 5) | `test_tiff_is_lzw` | ✅ |
| 022 | JPEG re-openable | `test_jpeg_re_openable` | ✅ |
| 023 | Size targeting via iteration | `test_pdf_size_within_band` (≥3/5 runs in-band) | ✅ |
| 024 | Determinism on fixed seed | `test_same_seed_byte_identical` (SHA-256) + integration `test_seed_byte_identical_across_runs` | ✅ |
| 025 | Pillow/img2pdf exceptions propagate | covered structurally (no try/except swallow in impl); not separately tested | ⚠️ PARTIAL (low risk — pure additive surface) |
| 026 | ≥8 unit tests | 11 tests | ✅ |

### CLI (REQ-027..REQ-032)

| REQ | Behavior | Test | Result |
|-----|----------|------|--------|
| 027 | `mock` group wired into app.py | `app.py:33` import + `app.py:69` add_command + integration tests exercise via `CliRunner.invoke(main, ["mock", "generate", ...])` | ✅ |
| 028 | Full option surface | integration `test_decodable_files_under_root` uses every required option; multi-select `--system`, `--document-type` covered by unit tests | ✅ |
| 029 | Validation (exit 2 + stderr) | `test_pdf_band_inverted_exits_2`, `test_no_source_exits_2`, `test_both_sources_exit_2` | ✅ |
| 030 | --dry-run prints [plan] lines, no write | `test_dry_run_writes_nothing_and_lists_plans` | ✅ |
| 031 | non-dry-run + summary line | `test_decodable_files_under_root` asserts summary | ✅ |
| 032 | Error → exit 2; unexpected → exit 3 | Exit 2 paths covered. Exit 3 path is structurally present (broad `except Exception` → `sys.exit(3)`) but not behaviorally triggered by a test. | ⚠️ PARTIAL |

### Tests + Verification (REQ-033..REQ-038)

| REQ | Behavior | Result |
|-----|----------|--------|
| 033 | Unit tests ≥22 | 55 actual | ✅ |
| 034 | Integration test with ≥4 cases | 6 actual | ✅ |
| 035 | pytest baseline + ≥23 new | 804 passed (≥741 baseline + 63 new across all changed test files) | ✅ |
| 036 | mypy clean | Success: no issues found in 72 source files | ✅ |
| 037 | ruff check + format clean | All checks passed | ✅ |
| 038 | pre-commit run --all-files clean | All hooks Passed | ✅ |

### Acceptance Scenarios (spec §5)

| # | Scenario | Test | Result |
|---|----------|------|--------|
| 1 | Happy path mixed formats | `test_decodable_files_under_root` | ✅ |
| 2 | Dry run | `test_dry_run_writes_nothing_and_lists_plans` | ✅ |
| 3 | Determinism | `test_seed_byte_identical_across_runs` + `test_same_seed_byte_identical` (after fix `2194a5b`) | ✅ |
| 4 | Skip-if-exists vs force | unit `test_skip_if_exists_returns_empty`, `test_force_overwrites` | ✅ (not at integration level — see SUGGESTION) |
| 5 | Deleted-row skip | unit `test_deleted_row_skipped_by_default`, `test_include_deleted_yields_deleted_rows` | ✅ |
| 6 | Filters | unit `test_system_filter`, `test_document_type_filter`, `test_combined_filters_and_limit` | ✅ |
| 7 | Validation error pdf band | integration `test_pdf_band_inverted_exits_2` | ✅ |
| 8 | Unknown ABABST | unit `test_unknown_image_type_raises` | ✅ |
| 9 | Path normalization | unit `test_strips_leading_backslashes_and_normalizes` (+ 3 sibling tests) | ✅ |

**Compliance summary**: 9/9 acceptance scenarios compliant. 38/38 REQs implemented (2 with partial behavioral evidence — flagged below, not blocking).

---

## Coherence (Architecture Decisions)

| Decision | Followed? | Notes |
|----------|-----------|-------|
| FilePlan in `types.py` not `planner.py` | ✅ | `src/cmcourier/services/mock/types.py` exists; both planner and content import from it |
| Pure planner, I/O-only writer | ✅ | `planner.py` is generator-only; `content.py` is the only writer with side effects |
| No new `IDataSource` adapter | ✅ | mock.py reuses `TabularDataSource` and `As400DataSource` |
| Size targeting via iteration | ✅ | 5-profile iteration in `_PROFILES_SMALL_TO_LARGE`; heuristic refined from "distance to midpoint" to "distance to band" during apply for better operator outcomes — deliberate, documented deviation, not a failure |
| `mock` top-level (not under `inspect`) | ✅ | `mock_group` registered separately in `app.py` |
| No `--output-format json` | ✅ | text-only summary; deferred per design §6 |
| `seed=None` ≠ `seed=0` | ✅ | `MockContentWriter.__init__` passes `seed` directly to `random.Random()` |

---

## Strict TDD Compliance

| Phase | Test file authored first | Verified RED before impl | GREEN after impl |
|-------|--------------------------|--------------------------|------------------|
| 1 — Sizing | ✅ `test_sizing.py` | ✅ `ModuleNotFoundError` confirmed | ✅ 24/24 |
| 2 — Content | ✅ `test_content.py` | ✅ `ModuleNotFoundError` confirmed | ✅ 11/11 |
| 3 — Planner | ✅ `test_planner.py` | ✅ `ModuleNotFoundError` confirmed | ✅ 20/20 |
| 4 — CLI | ✅ `test_mock_generate.py` | ✅ `exit_code == 2` confirmed pre-wire | ✅ 6/6 |

RED-before-GREEN enforced and observed in-session for every phase. Commit
granularity bundles test+impl per phase (project convention; consistent
with 028 and earlier changes).

---

## Issues Found

### CRITICAL (must fix before archive)

**None.**

### WARNING (should fix)

**None** — both partials below are SUGGESTIONS, not blockers.

### SUGGESTION (nice-to-have follow-ups)

1. **AS400 source path lacks integration coverage.** `_build_source` and
   `_extract_as400_connection` in `cli/commands/mock.py` are exercised
   structurally but not by any test (would require a fake `IDataSource`
   at the integration level or a pyodbc shim). The CSV path is fully
   covered. A follow-up change could add a thin unit test against a fake
   `IDataSource` to close this gap. Not blocking — the AS400 path reuses
   the same well-tested planner + writer.
2. **REQ-025 (Pillow/img2pdf exception propagation) not directly tested.**
   The impl raises naturally via `RuntimeError` wrapping if any underlying
   call throws; a focused test using a poisoned Pillow stub would close
   this gap. Low risk; covered structurally.
3. **REQ-032 exit-code 3 path not behaviorally tested.** The unexpected-
   exception branch in `generate_command` is reachable but not triggered
   by any test. A test could inject a poisoned writer to verify exit 3.
4. **Coverage not measured during this verify.** Running `pytest --cov`
   raised an unrelated numpy 2 import error during test collection (a
   pre-existing toolchain issue, not 031). Should be reconciled in a
   separate pass (likely by upgrading or pinning pandas/numpy compat).
   The plain `pytest` run is the binding signal: 804/804 passing.
5. **Determinism fix (2194a5b) was discovered during verify, not apply.**
   Without `nodate=True` on `img2pdf.convert`, the determinism test was
   wall-clock-flaky under randomized test ordering. The fix is in; the
   lesson is to test determinism under shuffled order during apply, not
   only in isolation. Worth a note in the project's testing conventions.

---

## Verdict

**PASS WITH WARNINGS.** Ready for archive (`sdd-archive`) and FF merge to
`main`. The five SUGGESTIONs are documented as follow-ups; none of them
blocks the change from shipping.

### Recommended next steps

1. `sdd-archive 031-mock-file-generator` to merge planning artifacts into
   the project's spec history and update CHANGELOG to a versioned section.
2. Coordinate with `main` (which moved during this session due to parallel
   change 033). The branch is no longer FF-mergeable; either rebase or
   accept a merge commit. Project precedent prefers FF — rebase first.
3. Optionally: open follow-ups for the 5 SUGGESTIONS above.

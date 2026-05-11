# 031 — Mock File Generator (proposal)

> Status: **Proposed** — 2026-05-11
> Author: bitBreaker
> Predecessor: `exploration.md`
> Note: Change **030** is in flight in parallel; this is **031**.

---

## 1. Summary

New CLI subcommand `cmcourier mock generate` that reads an
RVABREP source (CSV or AS400) and materializes a folder tree
of **valid** mock files under a configurable root, mirroring
exactly the `<source_root>/<ABAICD>/<ABAJCD>` layout that
`PdfAssembler` (S4) expects. PDFs become multi-page `.pdf`
files (one file, N pages per `ABABUN`); paged images become
`<file_code>.001..NNN` siblings. File weights are bounded by
`--pdf-min/max` and `--img-min/max` with suffix parsing
(`10kb`, `2mb`). Flags: `--seed`, `--dry-run`, `--force`,
`--include-deleted`, `--limit`, `--system`, `--document-type`.

## 2. Motivation

- Dry runs and integration tests need synthetic data on a
  filesystem the operator controls (prod file server is
  unavailable / contains real customer documents).
- The pipeline's S4 calls `img2pdf` / Pillow / PyPDF2 — random
  bytes fail at the first decode. Mocks **must be valid**.
- Perf testing needs controlled file-size distributions, not
  whatever happened to land in the prod share.
- Operator-friendly (Click subcommand, discoverable via
  `cmcourier --help`), not a stray `scripts/*.py`.

## 3. Scope

### In Scope
- `cmcourier mock generate` Click subcommand in `cli/commands/mock.py`.
- Sources (mutually exclusive): `--rvabrep-csv PATH` | `--rvabrep-as400` (uses config-driven connection).
- Required: `--root PATH`.
- Size bounds with suffix parsing: `--pdf-min`, `--pdf-max`, `--img-min`, `--img-max`.
- Filters: `--limit N`, `--system ID` (repeatable), `--document-type ID` (repeatable).
- Behavior flags: `--seed INT`, `--dry-run`, `--force`, `--include-deleted`.
- Valid file generation: PDF via `img2pdf` (multi-page), TIFF via Pillow LZW, JPEG via Pillow.
- Path normalization: backslash → forward slash; strip leading separators.

### Out of Scope
- Generating non-RVABREP data (CMM mapping CSV, triggers CSV).
- OCR-realistic / human-readable content.
- A teardown / cleanup subcommand (operator uses `rm -rf`).
- Re-creating the AS400 schema; we only READ rows.
- Streaming mocks directly to CMIS (not needed; pipeline does that).
- Per-`ABABST` configurable pixel dimensions; sensible defaults only.

## 4. Capabilities

### New Capabilities
- `mock-file-generator`: CLI + service module that translates an RVABREP row stream into a deterministic, valid mock file tree on disk, with controlled size distribution.

### Modified Capabilities
- None. Pure additive — only edit to an existing file is one `main.add_command(mock_group)` line in `cli/app.py`.

## 5. Approach

- Pure functions in `services/mock/`: `sizing.py` (suffix parser), `planner.py` (row → file plan with dedup, deleted-row skip, multi-page expansion, path normalization).
- I/O in `services/mock/content.py`: write valid PDF / TIFF / JPEG bytes targeting a size band (`±10%` tolerance).
- Thin Click wrapper in `cli/commands/mock.py`: parse options, instantiate `IDataSource` (`TabularDataSource` or `As400DataSource`), drive planner → content.
- Strict TDD throughout (`sdd-init/cmcourier` → `strict_tdd: true`).
- Decomposed into 4 phases (sizing → content → planner → CLI+wiring), full breakdown in `plan.md`.

## 6. Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/cmcourier/cli/commands/mock.py` | NEW | Click group + `generate` subcommand. |
| `src/cmcourier/cli/app.py` | MODIFIED (+1 line) | `main.add_command(mock_group)`. |
| `src/cmcourier/services/mock/` | NEW | `sizing.py`, `planner.py`, `content.py`, `__init__.py`. |
| `tests/unit/services/mock/` | NEW | One module per service component. |
| `tests/integration/cli/test_mock_generate.py` | NEW | End-to-end via CliRunner on a tiny CSV fixture. |
| `CHANGELOG.md` | MODIFIED (on archive) | One-line entry. |

## 7. Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `img2pdf` size targeting is non-linear (JPEG quality × noise × pages). | Med | Iterate with ±10% tolerance band; document in spec. |
| Default Pillow TIFF is heavy; can blow `--img-min 5kb`. | Med | Force `compression="tiff_lzw"`, small pixel dims. |
| Integration tests requiring live AS400. | Low | Cover AS400 path via unit-level fake `IDataSource`; CSV covers the end-to-end. |
| Parallel change 030 touches CLI. | Low | Pure additive surface (new module + 1 line). Resolve at apply time if needed. |

## 8. Rollback Plan

Pure additive change. Rollback = `git revert <merge-commit>` which removes `cli/commands/mock.py`, `services/mock/*`, the `app.py` registration line, and the test modules. No schema migration, no config changes, no DB state, no CMIS state.

## 9. Dependencies

- `img2pdf`, `Pillow`, `PyPDF2` — already in `pyproject.toml` (used by `PdfAssembler`).
- No new runtime deps. Reuses `IDataSource` adapters.

## 10. Success Criteria

- [ ] `cmcourier mock generate --rvabrep-csv <fixture> --root <tmp> --pdf-min 10kb --pdf-max 100kb --img-min 5kb --img-max 50kb` produces files that `img2pdf` / Pillow / PyPDF2 can re-open without exceptions.
- [ ] `--dry-run` prints the plan and writes zero bytes.
- [ ] `--seed N` produces byte-identical output across runs.
- [ ] Re-running without `--force` is a no-op (skip-if-exists).
- [ ] Rows with non-empty `delete_code` are skipped by default; included with `--include-deleted`.
- [ ] Unit + integration tests pass under Strict TDD; no existing tests regress.
- [ ] Estimate respected: ~4–5h, 4 phases.

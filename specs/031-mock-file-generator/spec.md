# 031 — Mock File Generator

> Status: **Proposed** — 2026-05-11
> Author: bitBreaker
> Predecessor: `proposal.md`, `exploration.md`
> Note: Change **030** is in flight in parallel; this is **031**.

---

## 1. Summary

Add `cmcourier mock generate`, a CLI subcommand that reads an
RVABREP source (CSV via `TabularDataSource` or AS400 via
`As400DataSource`) and materializes a folder tree of **valid**
mock documents under a configurable root. Output layout
mirrors what `PdfAssembler` (S4) expects:
`<root>/<ABAICD>/<ABAJCD>` for PDFs and
`<root>/<ABAICD>/<file_code>.001..NNN` for paged-image
documents. File weights are bounded per-format with
suffix-parsed options (`10kb`, `2mb`). PDFs are real
multi-page PDFs; TIFFs use LZW compression; JPEGs are
standard. Pure additive surface, no production code touched
except a one-line `add_command` in `cli/app.py`.

---

## 2. Motivation

See `proposal.md §2`. Briefly: dry runs, end-to-end
integration tests, and perf testing need a controllable,
deterministic file tree on a filesystem the operator owns,
populated with files the existing S4 stack (`img2pdf`,
Pillow, PyPDF2) can actually decode.

---

## 3. Scope

See `proposal.md §3`. **In**: new Click subcommand + service
module + tests. **Out**: non-RVABREP data, OCR-realistic
content, teardown command, per-`ABABST` configurable pixel
dimensions, streaming-to-CMIS.

---

## 4. Requirements

### Size parser (`services/mock/sizing.py`)

- **REQ-001**: Pure function
  `parse_size(text: str) -> int` accepts case-insensitive
  inputs of the form `<number>[ ]?<suffix>?` where `<suffix>`
  ∈ {`b`, `kb`, `mb`, `gb`} and `<number>` is a positive int
  or decimal. Returns the byte count using **binary units**
  (`1 kb = 1024`, `1 mb = 1024²`, `1 gb = 1024³`).
- **REQ-002**: Missing suffix is treated as bytes
  (`"500"` → 500).
- **REQ-003**: Whitespace around the value/suffix is
  tolerated (`" 2 mb "` → 2 097 152).
- **REQ-004**: Invalid inputs (negative, non-numeric, unknown
  suffix, empty string) raise `ValueError` with a message
  naming the offending input.
- **REQ-005**: ≥6 unit tests cover the matrix: each suffix,
  decimal value, whitespace, missing suffix, error cases.

### Planner (`services/mock/planner.py`)

- **REQ-006**: Dataclass `FilePlan` (frozen, slots) with
  fields: `dir_path: Path`, `file_code: str`,
  `kind: Literal["pdf", "tiff", "jpeg"]`, `pages: int`,
  `size_min: int`, `size_max: int`, `extensions:
  tuple[str, ...]` (e.g. `(".PDF",)` or `(".001", ".002")`).
- **REQ-007**: Pure function
  `plan_files(rows, columns, filters, size_bounds,
  include_deleted=False) -> Iterator[FilePlan]`. No I/O. No
  randomness. Order preserved from input.
- **REQ-008**: Rows with `columns.delete_code` non-empty
  are skipped unless `include_deleted` is true.
- **REQ-009**: Rows are filtered by `filters.systems`
  (ABAACD) and `filters.document_types` (ABAHCD); both
  default to "no filter". Empty values do not match.
- **REQ-010**: `filters.limit` (optional positive int) caps
  the number of **planned** files (post-filter, post-dedup).
- **REQ-011**: PDF detection uses
  `domain.models.is_pdf_filename(file_name)` — case-
  insensitive `.PDF` suffix. PDFs yield a single `FilePlan`
  with `kind="pdf"`, `pages=max(1, total_pages)`,
  `extensions=(".PDF",)`.
- **REQ-012**: Non-PDF rows yield a single `FilePlan` with
  `kind` derived from `image_type` (`B`→`tiff`, `C`→`jpeg`).
  `pages = max(1, total_pages)`. `extensions` is
  `(".001", ".002", ..., f".{pages:03d}")`.
- **REQ-013**: `image_type` not in {`B`, `C`, `O`} on a
  non-PDF row raises `ConfigurationError` with the offending
  code and the row's txn_num.
- **REQ-014**: `image_path` is normalized: backslashes →
  forward slashes, leading `/` or `\` stripped, collapsed
  via `Path(...)`. Empty after normalization → planner
  raises `ConfigurationError`.
- **REQ-015**: Dedup key is
  `(normalized_dir_path, file_code)`. If multiple rows share
  the same key, only the first is emitted; subsequent rows
  with the same key whose `total_pages` differ from the
  first emit a `warning`-level log record with both txn_nums
  and both page counts. The first row's page count wins.
- **REQ-016**: ≥8 unit tests cover: deleted-row skip,
  include-deleted opt-in, system filter, doc-type filter,
  combined filters, limit, PDF vs image dispatch, dedup
  with page-count conflict, path normalization (POSIX and
  Windows-style inputs), unknown `image_type` raise.

### Content generator (`services/mock/content.py`)

- **REQ-017**: Class `MockContentWriter(seed: int | None,
  tolerance: float = 0.10)`. `seed=None` uses system
  entropy. `tolerance` is the acceptable fractional
  deviation from the midpoint of `[size_min, size_max]`.
- **REQ-018**: `writer.write(plan: FilePlan, target_dir:
  Path, *, force: bool) -> list[Path]` creates `target_dir`
  if missing, then writes the file(s) under it and returns
  the list of paths it wrote.
- **REQ-019**: If `force` is false and **all** target paths
  for the plan already exist, `write` returns `[]` without
  re-writing.
- **REQ-020**: `kind="pdf"`: produces a single
  `<file_code>.PDF` via `img2pdf.convert([...])` over `pages`
  JPEG buffers built in-memory with Pillow. The PDF MUST be
  re-openable by `PyPDF2.PdfReader` and report
  `len(reader.pages) == plan.pages`.
- **REQ-021**: `kind="tiff"`: produces `pages` files
  (`<file_code>.001`..`<file_code>.NNN`), each a single-page
  TIFF saved with `compression="tiff_lzw"`. Each file MUST
  be re-openable by `PIL.Image.open(...)` and reportable as
  TIFF.
- **REQ-022**: `kind="jpeg"`: produces `pages` files
  (`<file_code>.001`..`<file_code>.NNN`), each a single-page
  JPEG. Each file MUST be re-openable by
  `PIL.Image.open(...)` and reportable as JPEG.
- **REQ-023**: Size targeting: each produced file's byte
  count SHOULD fall within
  `[size_min, size_max] ± tolerance × midpoint`. The writer
  iterates pixel dimensions / JPEG quality / random-noise
  density up to 5 attempts; if no attempt lands in the band,
  writes the closest attempt and logs a `warning`.
- **REQ-024**: Determinism: with a fixed `seed`, two runs
  over identical plans MUST produce byte-identical files.
- **REQ-025**: `writer` MUST NOT swallow exceptions from
  Pillow / img2pdf; they propagate as `RuntimeError` wrapping
  the original.
- **REQ-026**: ≥8 unit tests cover: PDF page count matches,
  PDF re-openable by PyPDF2, TIFF compression actually LZW,
  JPEG re-openable, size within band for each format,
  determinism with fixed seed, skip-if-exists,
  force-overwrite.

### CLI (`cli/commands/mock.py`)

- **REQ-027**: Click group `mock` (`@click.group(name="mock")`)
  with one subcommand `generate`. The group is wired into
  the root CLI via `main.add_command(mock_group)` in
  `cli/app.py`, alongside the existing
  `analyze_group`/`batch_group`/`inspect_group`
  registrations.
- **REQ-028**: `generate` accepts the following options:
  - Source (mutually exclusive, exactly one required):
    - `--rvabrep-csv <PATH>` (existing CSV).
    - `--rvabrep-as400` (uses `--config <PATH>` to read
      `indexing` and AS400 connection blocks).
  - `--config <PATH>` (required when `--rvabrep-as400` is
    set; optional otherwise — when present, the column
    overrides under `indexing.columns` are honored).
  - `--root <PATH>` (required; created if missing).
  - `--pdf-min <SIZE>`, `--pdf-max <SIZE>` (required; both
    accept suffix syntax per `parse_size`).
  - `--img-min <SIZE>`, `--img-max <SIZE>` (required).
  - `--limit <N>`, `--system <ID>` (multi), `--document-type
    <ID>` (multi).
  - `--seed <INT>` (default: system entropy).
  - `--dry-run`, `--force`, `--include-deleted` (flags).
- **REQ-029**: Validation (exit 2 on failure with stderr
  message): `pdf_min ≤ pdf_max`, `img_min ≤ img_max`,
  exactly one of `--rvabrep-csv` / `--rvabrep-as400`,
  `--rvabrep-as400` requires `--config`.
- **REQ-030**: `--dry-run`: prints one line per planned file
  to stdout in the format
  `[plan] <rel_path>  kind=<kind>  pages=<n>  size=<min>..<max>`;
  writes zero bytes; exits 0.
- **REQ-031**: Non-dry-run: streams `IDataSource.get_all()`
  → `plan_files(...)` → `MockContentWriter.write(...)` and
  prints a summary line on stdout when done:
  `wrote <created> files (<skipped> skipped, <bytes> total)`.
- **REQ-032**: Errors (`ConfigurationError`,
  `FileNotFoundError`, `ValueError` from `parse_size`)
  exit with code 2 and a stderr message that includes the
  offending input. Unexpected exceptions exit with code 3.

### Tests

- **REQ-033**: Unit tests live in `tests/unit/services/mock/`
  (`test_sizing.py`, `test_planner.py`, `test_content.py`).
  Counts per REQ above (≥6 + ≥8 + ≥8 = ≥22 unit tests).
- **REQ-034**: Integration test
  `tests/integration/cli/test_mock_generate.py` invokes the
  CLI via Click's `CliRunner` against a 3-row CSV fixture
  containing one PDF row (ABABUN=2), one TIFF row
  (ABABUN=3), one JPEG row (ABABUN=1). Asserts:
  files exist at the expected paths, each is decodable by
  the right library, dry-run mode writes nothing,
  `--seed 42` is byte-deterministic across two consecutive
  runs.

### Verification

- **REQ-035**: `pytest` MUST pass with the new tests; the
  pre-031 baseline count plus ≥23 new tests (≥22 unit +
  ≥1 integration cluster).
- **REQ-036**: `mypy src/cmcourier/` clean.
- **REQ-037**: `ruff check` + `ruff format --check` clean.
- **REQ-038**: `pre-commit run --all-files` clean.

---

## 5. Acceptance scenarios

1. **Happy path — CSV, mixed formats**
   - **Given** a 3-row RVABREP CSV: one PDF with
     `ABABUN=2`, one TIFF (`ABABST=B`) with `ABABUN=3`, one
     JPEG (`ABABST=C`) with `ABABUN=1`, distinct
     `image_path` for each.
   - **When** the operator runs
     `cmcourier mock generate --rvabrep-csv f.csv
     --root /tmp/m --pdf-min 20kb --pdf-max 200kb
     --img-min 5kb --img-max 50kb --seed 1`.
   - **Then** the tree contains: `<path1>/<code1>.PDF` (a
     PDF with 2 pages), `<path2>/<code2>.001`,
     `<path2>/<code2>.002`, `<path2>/<code2>.003` (TIFF
     LZW), `<path3>/<code3>.001` (JPEG). Each file is
     re-openable by its respective library. Sizes fall
     within `±10%` of their respective bands. Exit 0.

2. **Dry run**
   - **Given** the same fixture.
   - **When** the operator adds `--dry-run`.
   - **Then** stdout lists 5 planned files (1 PDF + 3 TIFF
     + 1 JPEG) with one `[plan]` line each. `/tmp/m` is
     either missing or empty. Exit 0.

3. **Determinism**
   - **Given** the same fixture, run twice with
     `--seed 42`.
   - **Then** every produced file's SHA-256 matches between
     runs.

4. **Skip-if-exists vs force**
   - **Given** a populated `/tmp/m` from a prior run.
   - **When** the operator re-runs without `--force`.
   - **Then** stdout reports
     `wrote 0 files (5 skipped, 0 total)` and no file's
     mtime changed.
   - **When** the operator re-runs with `--force`.
   - **Then** stdout reports
     `wrote 5 files (0 skipped, …)` and every file's mtime
     was updated.

5. **Deleted-row skip**
   - **Given** a CSV row with non-empty `ABACST`.
   - **When** the operator runs without `--include-deleted`.
   - **Then** that row's files are NOT created. With
     `--include-deleted`, they ARE.

6. **Filters**
   - **Given** a 100-row CSV spanning 3 systems and 5
     document types.
   - **When** the operator runs with
     `--system A --system B --document-type X --limit 10`.
   - **Then** at most 10 files are created, all from rows
     where `ABAACD ∈ {A, B}` AND `ABAHCD == X`.

7. **Validation error**
   - **Given** the operator passes
     `--pdf-min 200kb --pdf-max 100kb`.
   - **Then** exit 2 and stderr says
     `ConfigurationError: --pdf-min (204800) must be ≤
     --pdf-max (102400)`.

8. **Unknown `ABABST`**
   - **Given** a CSV row with `ABABST=Z` and a non-PDF
     `ABAJCD`.
   - **Then** exit 2 and stderr says
     `ConfigurationError: unknown image_type 'Z' for
     txn_num=...`.

9. **Path normalization**
   - **Given** a CSV row with
     `ABAICD="\\\\server\\share\\docs\\2024"` (Windows
     escaped).
   - **Then** the file is created at
     `<root>/server/share/docs/2024/<file>` on POSIX with
     no literal backslashes in the path.

---

## 6. Risks

See `proposal.md §7`. Material risk is `img2pdf` size
targeting non-linearity (mitigated by REQ-023's 5-attempt
iteration and `±10%` tolerance band) and TIFF default-weight
overshoot (mitigated by REQ-021's mandatory LZW).

---

## 7. Dependencies

- `img2pdf`, `Pillow`, `PyPDF2` — already present
  (`pyproject.toml`, used by `PdfAssembler`).
- `pandas` — already present (`TabularDataSource`).
- No new dependencies.

---

## 8. Estimate

~4–5h, 4 phases per `plan.md` (sizing → content → planner →
CLI+wiring). Strict TDD. No coverage threshold delta
expected.

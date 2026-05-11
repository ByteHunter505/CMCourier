# 031 — Mock File Generator (exploration)

> Status: **Exploring** — 2026-05-11
> Author: bitBreaker
> Note: Change 030 is being developed in parallel; this one is **031**.

---

## 1. Topic

New CLI subcommand `cmcourier mock generate` that consumes an
RVABREP source (CSV **or** AS400) and materializes a folder
structure of **valid** mock files under a configurable root,
mirroring exactly the layout that `PdfAssembler` (stage S4)
expects: `<root>/<ABAICD>/<ABAJCD>` for PDFs and
`<root>/<ABAICD>/<file_code>.001..NNN` for paged images.

Goal: feed the real pipeline end-to-end (S0–S5) against a
synthetic dataset without needing the production file server,
for dry runs, perf testing, and integration tests.

---

## 2. Current State

### 2.1 RVABREP column mapping (authoritative — `config/schema.py:149-168`)

| Logical field   | Physical column | Notes |
|-----------------|-----------------|-------|
| `shortname`     | `ABABCD`        | index1 |
| `system_id`     | `ABAACD`        | system_code |
| `delete_code`   | `ABACST`        | non-empty ⇒ row marked deleted |
| `txn_num`       | `ABAANB`        | document key |
| `id_rvi`        | `ABAHCD`        | index7, document type per RVI |
| `image_type`    | `ABABST`        | `B` = TIFF, `C` = JPEG, `O` = PDF |
| `image_path`    | `ABAICD`        | folder under `source_root` |
| `file_name`     | `ABAJCD`        | base filename (e.g. `DOC0001.001` or `DOC0001.PDF`) |
| `total_pages`   | `ABABUN`        | int — used by assembler for sanity check |
| `creation_date` | `ABAADT`        | not needed for the mock |

User's mapping in the prompt matches exactly. Confirmed.

### 2.2 What the S4 assembler expects (`pdf_assembler.py:103-156`)

**Native PDF branch** (`is_pdf_filename(file_name)` ⇒ name
ends in `.PDF` case-insensitive):

```python
src = source_root / image_path / file_name
shutil.copy2(src, temp_dir / f"{txn_num}.pdf")
StagedFile(path=..., size_bytes=stat().st_size, page_count=total_pages)
```

→ The assembler **trusts `total_pages` from RVABREP and does
not parse the PDF**. A single-page PDF with `ABABUN=99` passes
S4 silently. But the CM server may count pages itself
downstream, so producing N real pages is the safe call.

**Paged-image branch:**

```python
source_dir = source_root / image_path
file_code = file_name.split(".")[0]
candidates = sorted(
    source_dir.glob(f"{file_code}.*"),
    key=lambda p: int(p.suffix.lstrip(".")),
)
# Filtered to numeric extensions only (.001/.002/...).
# WARN — not fail — on count mismatch vs total_pages.
img2pdf.convert([str(p) for p in candidates])
# Falls back to Pillow + PyPDF2 on any img2pdf exception.
```

→ Files **MUST be decodable** by `img2pdf` (or by Pillow as
fallback). Random bytes break this chain immediately.
`img2pdf` supports JPEG natively and TIFF via Pillow.

### 2.3 Data sources (`adapters/sources/`)

- `TabularDataSource` (`tabular.py`) — pandas-backed CSV/XLSX.
  Reads everything as `dtype=str`; NaN normalized to `None`.
  Already used by all `inspect` commands.
- `As400DataSource` (`as400.py`) — pyodbc-backed, lazy import.
  Same `IDataSource` contract. Connection string already
  formatted; just needs host/port/db/driver/user/pass.

Both expose `get_all() → Iterator[dict[str, Any]]`. Perfect
for a streaming mock generator that doesn't load everything
into memory.

### 2.4 CLI pattern (Click, not Typer)

Reference: `cli/commands/analyze.py`, `inspect.py`, `batch.py`.
Each command module exposes a `<name>_group` (or single
command), wired into `cli/app.py` with `main.add_command(...)`.
Option style: `--config`, `-c`, `click.Path(exists=True,
path_type=Path)`. Errors → `click.echo("...", err=True)` +
`sys.exit(2)`.

### 2.5 Project SDD conventions

GitHub Spec Kit layout, NOT openspec. Each change lives at
`specs/NNN-name/` with `spec.md` + `plan.md` + `tasks.md`.
Exploration file is new to this project (no precedent in
020-029) — adopting `exploration.md` here, will fold its
findings into `spec.md` and discard if it becomes redundant.

---

## 3. Affected Areas

| Path | Why |
|------|-----|
| `src/cmcourier/cli/commands/mock.py` (NEW) | New Click group + `generate` subcommand. |
| `src/cmcourier/cli/app.py` | Register `mock_group` via `main.add_command(...)`. |
| `src/cmcourier/services/mock/__init__.py` (NEW) | Service module — generator orchestration. |
| `src/cmcourier/services/mock/sizing.py` (NEW) | Parse `10kb`/`2mb` suffix into bytes; pure function. |
| `src/cmcourier/services/mock/content.py` (NEW) | Valid PDF/TIFF/JPEG byte generators backed by Pillow/img2pdf/PyPDF2. |
| `src/cmcourier/services/mock/planner.py` (NEW) | Translate RVABREP rows → list of files to create (no I/O). |
| `tests/unit/services/mock/test_sizing.py` (NEW) | Suffix parsing edge cases. |
| `tests/unit/services/mock/test_planner.py` (NEW) | Row → file plan, dedup, deleted rows, multi-page. |
| `tests/unit/services/mock/test_content.py` (NEW) | Valid PDF/TIFF/JPEG bytes within bounds. |
| `tests/integration/cli/test_mock_generate.py` (NEW) | End-to-end: tiny CSV → real files on disk → re-read with Pillow/PyPDF2. |
| `CHANGELOG.md` | One-line entry on archive. |

Pure additive — touches **zero** existing production code paths.
The only existing-file edit is `app.py:65` to register the
group, which is a one-line append matching the pattern used
by `analyze_group`.

---

## 4. Design Decisions Resolved Through Exploration

### 4.1 PDFs — generate N real pages

Even though `PdfAssembler` doesn't reparse PDFs, downstream
CMIS upload (`CmisUploader`) may verify, and tests that
re-open the PDF (Pillow / PyPDF2) need it valid. Generating N
pages also makes hitting the `--pdf-min`/`--pdf-max` bounds
natural — pad each page's image with random noise.

**Approach**: build N JPEG pages in memory with PIL using
random noise pixels, concatenate via `img2pdf.convert(...)`,
adjust noise density to hit a target byte count between
`pdf_min` and `pdf_max`.

### 4.2 ABABST unknown codes — strict raise

Three codes are documented (`B`=TIFF, `C`=JPEG, `O`=PDF). If
the RVABREP row carries something else, raise
`ConfigurationError`. CMCourier is already strict in pydantic;
matching that style is consistent and surfaces data-quality
issues early.

### 4.3 Dedup — skip-if-exists by default

Same `image_path + file_name` may appear in multiple RVABREP
rows (e.g. one document referenced from multiple txns). Default
behavior: if the target file (and all sibling pages for
multi-page docs) already exist on disk, skip. `--force`
overwrites.

### 4.4 Deleted rows — skip by default

`delete_code` non-empty ⇒ row was marked deleted. The
pipeline already skips these (see `IndexingService` /
`RVABREPDeletedError`). Match that. `--include-deleted` opts
in for completeness.

### 4.5 Single-page image extension — always `.001`

The S4 globber wants `FILECODE.<numeric>`. For
`ABABUN=1, ABABST=B|C`, generate exactly one file named
`<file_code>.001`. Confirmed against `pdf_assembler.py:138-145`.

### 4.6 Filters

- `--limit N` — stop after N rows. For smoke tests.
- `--system <id>` (repeatable) — filter on ABAACD.
- `--document-type <id>` (repeatable) — filter on ABAHCD.

Applied **after** row read but **before** planning, to keep
the planner pure.

### 4.7 Determinism — `--seed`

`--seed <int>` seeds Python's `random` and PIL's noise
generators. Default = system entropy. Tests use a fixed seed.

### 4.8 `--dry-run`

Prints a per-row plan: `[would create] /root/.../FILE.001 ~50KB
[TIFF] ABABUN=3`. Never writes. Useful pre-flight on large
RVABREPs.

### 4.9 Path normalization

AS400 `image_path` values are often Windows-style
(`\\server\share\path` or `path\with\backslashes`). On POSIX,
`Path("a/b") / Path("\\foo\\bar")` produces literal-backslash
directory names. Normalize:

```python
def normalize_image_path(s: str) -> Path:
    # Strip leading slashes/backslashes, normalize separators.
    s = s.replace("\\", "/").lstrip("/")
    return Path(s)
```

This makes the mock generator deterministic regardless of OS
the RVABREP was exported from. Document the transformation
clearly in `spec.md`.

### 4.10 PDF `total_pages` mismatch

Edge case: a PDF row with `ABABUN > 1` is unusual. Spec to
treat `ABABUN` as the page count even for PDFs — generate a
PDF with that many pages. For `ABABUN ≤ 0` or missing on a PDF
row, default to 1 and log a warning.

---

## 5. Approaches Considered

### Approach A — single-file script under `scripts/`
- Pros: trivial; no test pyramid; ships in 1h.
- Cons: not discoverable; no Click integration; no config
  loading; bypasses every project convention; you'd run it
  with `uv run python scripts/mock.py ...`.
- Effort: Low.

### Approach B — Click subcommand `cmcourier mock generate` **(chosen)**
- Pros: idiomatic; reuses `IDataSource`, config loader,
  observability setup; discoverable via `cmcourier --help`;
  testable both unit (planner/sizing/content) and integration
  (subprocess invoking the CLI).
- Cons: more code, more tests, more spec/plan ceremony.
- Effort: Medium.

### Approach C — service-only (no CLI), exposed for tests
- Pros: lightest.
- Cons: operator can't use it without writing Python — defeats
  the dry-run use case.
- Effort: Low.

---

## 6. Recommendation

**Approach B** with the design decisions in §4. Decomposed
into 4 phases mirroring the project's 4-phase rhythm:

1. **Phase 1** — `services/mock/sizing.py` (suffix parser) +
   tests. ~30min.
2. **Phase 2** — `services/mock/content.py` (valid PDF/TIFF/
   JPEG byte generators with size targeting) + tests. ~1.5h.
3. **Phase 3** — `services/mock/planner.py` (row → file plan,
   dedup, deleted-row skip, multi-page expansion, path
   normalization) + tests. ~1h.
4. **Phase 4** — `cli/commands/mock.py` (Click group, wiring,
   `--dry-run`, `--force`, `--seed`, filters) + integration
   test invoking the CLI on a tiny CSV fixture + `app.py`
   register + CHANGELOG. ~1.5h.

Total estimate: **~4–5h**. Strict TDD throughout (project has
`strict_tdd: true` from `sdd-init/cmcourier`).

---

## 7. Risks

- **`img2pdf` size targeting is non-linear.** JPEG quality vs
  noise density vs page count interact unpredictably; hitting
  exact byte targets needs iteration with a tolerance band
  (e.g. ±10%). Mitigation: aim for the midpoint, accept a
  spread; document in spec.
- **TIFF generation is heavier than JPEG.** PIL produces big
  TIFFs by default; need to control compression
  (`compression="tiff_lzw"`) and pixel dimensions to hit small
  `--img-min` values like 5kb.
- **AS400 in tests.** Integration test should NOT require a
  real AS400. Cover the AS400 path via unit tests with a fake
  `IDataSource`; CSV path covers the end-to-end integration.
- **Parallel change 030.** Coordinating with the other bot
  shouldn't be an issue — pure additive surface (new module,
  one `add_command` line). Conflict probability low; resolve
  during apply if needed.

---

## 8. Open Questions for Proposal Phase

None blocking. All design questions resolved in §4. Ready to
move to `sdd-propose`.

---

## 9. Ready for Proposal

**Yes.** Recommend orchestrator advance to `sdd-propose` for
`031-mock-file-generator` with Approach B and the 4-phase
breakdown above.

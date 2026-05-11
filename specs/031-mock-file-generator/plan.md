# 031 — Implementation Plan

> Companion to `spec.md`. Four phases, ~4–5h total.
> Strict TDD: every phase writes tests first, then minimal code, then refactor.
> Phase 1 is the warm-up. Phase 2 is the heaviest (size targeting + img2pdf).
> Phase 3 is the most logic-dense (filters + dedup + path norm).
> Phase 4 is wiring + smoke.

---

## Phase 1 — Sizing parser (~30min)

1. Create `cmcourier/services/mock/__init__.py` (empty marker
   module).
2. Create `cmcourier/services/mock/sizing.py`:
   ```python
   from __future__ import annotations
   __all__ = ["parse_size"]
   import re

   _RE = re.compile(
       r"^\s*(\d+(?:\.\d+)?)\s*(b|kb|mb|gb)?\s*$",
       re.IGNORECASE,
   )
   _MULT: dict[str | None, int] = {
       None: 1, "b": 1,
       "kb": 1024, "mb": 1024**2, "gb": 1024**3,
   }

   def parse_size(text: str) -> int:
       """Parse '10kb', '2.5mb', '500' (bytes) → int bytes.

       Binary units (1 kb = 1024). Whitespace tolerated.
       Raises ``ValueError`` on negative / non-numeric /
       unknown suffix / empty input.
       """
       ...
   ```
   Implementation: match `_RE`; if no match → raise
   `ValueError(f"invalid size {text!r}")`. Extract group(2)
   (suffix), lowercase, look up in `_MULT`. Return
   `int(float(group(1)) * mult)`. Negative inputs cannot
   match the regex (`\d+` is unsigned), so no separate
   negative check.
3. Create `tests/unit/services/mock/__init__.py` (empty).
4. Create `tests/unit/services/mock/test_sizing.py` with
   ≥6 tests (REQ-005):
   - `test_parse_size_bytes_no_suffix`: `"500"` → 500.
   - `test_parse_size_kb`: `"10kb"` → 10240.
   - `test_parse_size_mb`: `"2mb"` → 2_097_152.
   - `test_parse_size_decimal`: `"2.5kb"` → 2560.
   - `test_parse_size_whitespace`: `"  10 kb  "` → 10240.
   - `test_parse_size_case_insensitive`: `"10MB"` and
     `"10Mb"` both → 10_485_760.
   - `test_parse_size_rejects_invalid`: parametrized over
     `[""`, `"abc"`, `"-5kb"`, `"5tb"`, `"5 5kb"]` → each
     raises `ValueError`.

**Done when**: `pytest tests/unit/services/mock/test_sizing.py`
passes.

---

## Phase 2 — Content writer (~1.5h)

1. Create `cmcourier/services/mock/types.py`:
   ```python
   from __future__ import annotations
   __all__ = ["FilePlan"]
   from dataclasses import dataclass
   from pathlib import Path
   from typing import Literal

   FileKind = Literal["pdf", "tiff", "jpeg"]

   @dataclass(frozen=True, slots=True)
   class FilePlan:
       dir_path: Path
       file_code: str
       kind: FileKind
       pages: int
       size_min: int
       size_max: int
       extensions: tuple[str, ...]
   ```
   (FilePlan lives here, not `planner.py`, to keep planner
   and content writer importing from a neutral module — same
   pattern as `cmcourier/domain/models.py`.)

2. Create `cmcourier/services/mock/content.py`:
   ```python
   from __future__ import annotations
   __all__ = ["MockContentWriter"]

   import logging
   import random
   from io import BytesIO
   from pathlib import Path

   import img2pdf
   from PIL import Image
   from PyPDF2 import PdfReader  # only for type sanity

   from cmcourier.services.mock.types import FilePlan

   _log = logging.getLogger(__name__)

   _DEFAULT_TOLERANCE = 0.10
   _MAX_ATTEMPTS = 5
   _DEFAULT_DIMS = (800, 1000)  # px

   class MockContentWriter:
       def __init__(
           self,
           seed: int | None = None,
           tolerance: float = _DEFAULT_TOLERANCE,
       ) -> None:
           self._rng = random.Random(seed)
           self._tolerance = tolerance

       def write(
           self,
           plan: FilePlan,
           target_dir: Path,
           *,
           force: bool,
       ) -> list[Path]:
           target_dir.mkdir(parents=True, exist_ok=True)
           targets = [
               target_dir / f"{plan.file_code}{ext}"
               for ext in plan.extensions
           ]
           if not force and all(p.exists() for p in targets):
               return []
           if plan.kind == "pdf":
               self._write_pdf(plan, targets[0])
           elif plan.kind == "tiff":
               self._write_paged(plan, targets, "TIFF")
           elif plan.kind == "jpeg":
               self._write_paged(plan, targets, "JPEG")
           else:  # pragma: no cover — planner enforces
               raise ValueError(f"unknown kind {plan.kind!r}")
           return targets
   ```
   - `_write_pdf`: build `plan.pages` JPEG buffers in-memory
     via `_render_jpeg_buffer(dims, quality, noise_density)`
     for `_MAX_ATTEMPTS` parameter triples, concatenate via
     `img2pdf.convert([buf.getvalue() for buf in buffers])`,
     check byte count against `_target_byte_count(plan)`
     within tolerance, accept first hit or the closest
     attempt. Write final bytes to `targets[0]`.
   - `_write_paged`: for each target path, generate a single
     image and call `Image.save(path, format=fmt, **kwargs)`
     where `kwargs={"compression": "tiff_lzw"}` for TIFF,
     `kwargs={"quality": q}` for JPEG. Per-page iteration
     for size targeting.
   - `_render_jpeg_buffer(dims, quality, noise)`: build PIL
     Image with `Image.new("RGB", dims)` then fill with
     pixels from `self._rng`; save to `BytesIO` with
     `format="JPEG", quality=quality`.
   - `_target_byte_count(plan) = (plan.size_min + plan.size_max) // 2`.
   - `_within_tolerance(actual, target)`:
     `abs(actual - target) <= self._tolerance * target`.

3. `tests/unit/services/mock/test_content.py` with ≥8 tests
   (REQ-026):
   - `test_pdf_pages_matches_plan`: write a 3-page PDF
     plan, open with `PyPDF2.PdfReader`, assert
     `len(reader.pages) == 3`.
   - `test_pdf_re_openable_pypdf2`: no exceptions on
     `PdfReader(path)` for `pages ∈ {1, 2, 5}`.
   - `test_tiff_is_lzw`: open each generated `.001` with
     PIL, assert `img.tag_v2[259] == 5` (TIFF compression
     tag 259, value 5 = LZW).
   - `test_jpeg_re_openable`: open each `.001`, assert
     `img.format == "JPEG"`.
   - `test_pdf_size_within_band`: 5 runs with band
     `[10kb, 30kb]`, assert each result within `±20%` of
     midpoint (looser than `_tolerance` to account for the
     5-attempt cap).
   - `test_determinism_same_seed`: two writers with
     `seed=42`, same plan, identical SHA-256 across runs.
   - `test_skip_if_exists`: pre-create the target files,
     `force=False` → `write()` returns `[]`, mtimes
     unchanged.
   - `test_force_overwrite`: pre-create, `force=True` →
     mtimes change, content overwritten.

**Risk**: img2pdf size targeting is non-linear; bands much
narrower than 20% of midpoint may not be hittable in 5
attempts. Tests use wide bands. If real-world tuning needs
narrower bands, raise `_MAX_ATTEMPTS` or add quality binary
search — defer until needed.

**Done when**: `pytest tests/unit/services/mock/` passes
(sizing + content green).

---

## Phase 3 — Planner (~1h)

1. Create `cmcourier/services/mock/planner.py`:
   ```python
   from __future__ import annotations
   __all__ = [
       "PlannerFilters",
       "SizeBounds",
       "normalize_image_path",
       "plan_files",
   ]

   import logging
   from collections.abc import Iterable, Iterator
   from dataclasses import dataclass
   from pathlib import Path

   from cmcourier.config.schema import IndexingColumnsModel
   from cmcourier.domain.exceptions import ConfigurationError
   from cmcourier.domain.models import is_pdf_filename
   from cmcourier.services.mock.types import FilePlan

   _log = logging.getLogger(__name__)

   @dataclass(frozen=True, slots=True)
   class PlannerFilters:
       systems: tuple[str, ...] = ()
       document_types: tuple[str, ...] = ()
       limit: int | None = None

   @dataclass(frozen=True, slots=True)
   class SizeBounds:
       pdf_min: int
       pdf_max: int
       img_min: int
       img_max: int

   def normalize_image_path(s: str) -> Path:
       """Backslash → '/', strip leading separators,
       collapse to a relative ``Path``.
       """
       ...

   def plan_files(
       rows: Iterable[dict[str, object]],
       columns: IndexingColumnsModel,
       filters: PlannerFilters,
       size_bounds: SizeBounds,
       *,
       include_deleted: bool = False,
   ) -> Iterator[FilePlan]:
       ...
   ```

2. Logic order (single pass per row, dedup table updated
   inline):
   - Skip if `row[columns.delete_code_column]` non-empty and
     `not include_deleted`.
   - Skip if `filters.systems` non-empty and
     `row[columns.system_id_column] not in filters.systems`.
   - Skip if `filters.document_types` non-empty and
     `row[columns.index7_column] not in filters.document_types`.
   - Normalize `image_path = normalize_image_path(
     row[columns.image_path_column])`. Empty → raise.
   - Extract `file_name = row[columns.file_name_column]`,
     `file_code = file_name.split(".")[0]`,
     `total_pages = max(1, int(row[columns.total_pages_column] or 1))`.
   - PDF dispatch: `is_pdf_filename(file_name)` → kind=`pdf`,
     extensions=`(".PDF",)`, pages=`total_pages`.
   - Non-PDF dispatch: `image_type = row[columns.image_type_column]`.
     If `image_type == "B"` → kind=`tiff`; `"C"` → kind=`jpeg`.
     Anything else → raise `ConfigurationError(
     f"unknown image_type {image_type!r} for txn_num={...}")`.
     Extensions = `tuple(f".{i:03d}" for i in range(1, total_pages+1))`.
   - Dedup key `(image_path, file_code)`. If seen and pages
     differ, `_log.warning(...)` with both txn_nums + page
     counts; skip the duplicate. If seen and pages match,
     silently skip.
   - Yield `FilePlan(...)`. Count toward `filters.limit`;
     stop iteration when reached.

3. `tests/unit/services/mock/test_planner.py` with ≥8 tests
   (REQ-016):
   - `test_plan_pdf_row`: one PDF row → one FilePlan
     kind=pdf, extensions=(".PDF",).
   - `test_plan_tiff_row_3_pages`: one ABABST=B row,
     ABABUN=3 → one FilePlan kind=tiff with
     extensions=(".001",".002",".003").
   - `test_plan_jpeg_row_single_page`: ABABST=C, ABABUN=1 →
     extensions=(".001",).
   - `test_skips_deleted_by_default`: row with non-empty
     ABACST → not yielded.
   - `test_include_deleted_opt_in`: same row, opt-in → yielded.
   - `test_system_filter`: filter `systems=("A",)` keeps
     only system A rows.
   - `test_doctype_filter_and_limit`: combined filter +
     `limit=2` caps result.
   - `test_dedup_first_wins_warns_on_page_conflict`: two
     rows same (path, code), different pages → one yielded
     with first row's pages; warning emitted (caplog).
   - `test_path_normalization_windows`: input
     `"\\\\server\\share\\d"` → `Path("server/share/d")`.
   - `test_unknown_image_type_raises`: ABABST=Z, non-PDF →
     `ConfigurationError`.

**Done when**: `pytest tests/unit/services/mock/` passes —
3 modules green (sizing + content + planner).

---

## Phase 4 — CLI integration + wiring + integration test (~1.5h)

1. Create `cmcourier/cli/commands/mock.py`:
   ```python
   """`cmcourier mock generate` — synthetic file generator (031)."""
   from __future__ import annotations
   __all__ = ["mock_group"]

   import logging
   import sys
   from pathlib import Path

   import click

   from cmcourier.adapters.sources import TabularDataSource
   from cmcourier.adapters.sources.as400 import As400DataSource
   from cmcourier.config.loader import load_config
   from cmcourier.config.schema import IndexingColumnsModel, PipelineConfig
   from cmcourier.domain.exceptions import ConfigurationError
   from cmcourier.services.mock.content import MockContentWriter
   from cmcourier.services.mock.planner import (
       PlannerFilters, SizeBounds, plan_files,
   )
   from cmcourier.services.mock.sizing import parse_size

   _log = logging.getLogger(__name__)

   @click.group(name="mock")
   def mock_group() -> None:
       """Synthetic file-tree generator for dry runs / tests (031)."""

   @mock_group.command(name="generate")
   @click.option("--rvabrep-csv", type=click.Path(exists=True, dir_okay=False, path_type=Path))
   @click.option("--rvabrep-as400", is_flag=True, default=False)
   @click.option("--config", "config_path",
                 type=click.Path(exists=True, dir_okay=False, path_type=Path))
   @click.option("--root", type=click.Path(path_type=Path), required=True)
   @click.option("--pdf-min", required=True)
   @click.option("--pdf-max", required=True)
   @click.option("--img-min", required=True)
   @click.option("--img-max", required=True)
   @click.option("--limit", type=int, default=None)
   @click.option("--system", "systems", multiple=True)
   @click.option("--document-type", "document_types", multiple=True)
   @click.option("--seed", type=int, default=None)
   @click.option("--dry-run", is_flag=True, default=False)
   @click.option("--force", is_flag=True, default=False)
   @click.option("--include-deleted", is_flag=True, default=False)
   def generate_command(...) -> None: ...
   ```

   Command body:
   - Validate exactly-one-of (`--rvabrep-csv` xor
     `--rvabrep-as400`); when AS400, `--config` required.
   - `pdf_min_b = parse_size(pdf_min); pdf_max_b = parse_size(pdf_max)`. Validate `pdf_min_b ≤ pdf_max_b`. Same for img.
   - Load config when present; derive
     `IndexingColumnsModel`. When no config, use
     `IndexingColumnsModel()` defaults.
   - Build source: CSV path → `TabularDataSource(csv_path)`;
     AS400 → `As400DataSource(**cfg.indexing.as400…)`. Wrap
     in `try / finally: src.close()`.
   - Build `PlannerFilters` + `SizeBounds`.
   - For `--dry-run`: iterate `plan_files(...)`, print one
     `[plan] <rel_path>/<file>  kind=<k>  pages=<n>
     size=<min>..<max>` line per yielded plan, exit 0.
   - Else: `writer = MockContentWriter(seed=seed)`.
     Counters `created`, `skipped`, `total_bytes`. For each
     plan, call `writer.write(plan, root / plan.dir_path,
     force=force)`; if empty list → `skipped += 1`; else
     `created += 1`, `total_bytes += sum(p.stat().st_size
     for p in written)`. Print
     `wrote <created> files (<skipped> skipped, <bytes>
     total)`.
   - Errors: `(ConfigurationError, ValueError,
     FileNotFoundError)` → `click.echo(f"{type.__name__}:
     {exc}", err=True); sys.exit(2)`. Unexpected →
     `sys.exit(3)` after `_log.exception`.

2. Edit `cmcourier/cli/app.py`:
   - Add import `from cmcourier.cli.commands.mock import
     mock_group` next to the other command imports
     (around line 31).
   - Add `main.add_command(mock_group)` after
     `main.add_command(analyze_group)` (around line 65).

3. Ensure `tests/integration/cli/__init__.py` exists
   (already does — same pattern as `test_multi_batch.py`).

4. Create
   `tests/integration/cli/test_mock_generate.py` (REQ-034):
   - Fixture: write a 3-row CSV to `tmp_path` with one PDF
     row (`ABABUN=2`), one TIFF row (`ABABST=B, ABABUN=3`),
     one JPEG row (`ABABST=C, ABABUN=1`), each with a
     distinct `ABAICD`.
   - `test_happy_path_creates_decodable_files`:
     `CliRunner.invoke(main, ["mock", "generate",
     "--rvabrep-csv", str(csv), "--root", str(root),
     "--pdf-min", "10kb", "--pdf-max", "100kb",
     "--img-min", "5kb", "--img-max", "50kb",
     "--seed", "42"])`. Assert `result.exit_code == 0`.
     For each expected path: assert it exists; open PDF via
     `PdfReader` (pages match), open `.001`s via PIL (format
     matches).
   - `test_dry_run_writes_nothing`: same invocation with
     `--dry-run`. Assert `root` empty (or non-existent)
     after.
   - `test_seed_deterministic_across_runs`: two invocations
     with `--seed 42` to different roots; assert SHA-256 of
     every file matches across the two roots.
   - `test_validation_error_pdf_band_inverted`: invoke with
     `--pdf-min 200kb --pdf-max 100kb`. Assert
     `result.exit_code == 2`, stderr contains
     `ConfigurationError` and both numeric byte values.

5. Update `CHANGELOG.md`:
   - Under `## [Unreleased]`, add a sub-section if it
     doesn't already exist for 031:
     ```
     ### Tooling
     - **031** — `cmcourier mock generate`: synthesize a
       valid RVABREP file tree (PDFs, TIFF LZW, JPEG) for
       dry runs / perf tests. See
       `specs/031-mock-file-generator/spec.md`.
     ```
     (The archive step will move this into a versioned
     section.)

**Risk**: Click does not have first-class mutually-
exclusive options. Implement via post-validation in the
command body — simplest, no callback dance. If we later add
`--rvabrep-xlsx`, refactor to a Click-native group.

**Done when**: full `pytest` suite green (baseline +
≥23 new); `mypy src/cmcourier/` clean; `ruff check`
+ `ruff format --check` clean; `pre-commit run --all-files`
clean; manual smoke:
```
cmcourier mock generate \
  --rvabrep-csv tests/fixtures/services/<existing>.csv \
  --root /tmp/m031 \
  --pdf-min 20kb --pdf-max 200kb \
  --img-min 5kb --img-max 50kb \
  --seed 1
```
prints a summary line, `/tmp/m031` contains decodable files.

---

## Architecture decisions

1. **`FilePlan` in `services/mock/types.py`, not
   `planner.py`.** Decouples planner from content writer;
   both import `FilePlan` from a neutral module. Avoids a
   circular import when either one grows. Same pattern used
   in `cmcourier/domain/models.py` for shared frozen
   dataclasses.
2. **Pure planner, I/O-only writer.** Planner is a
   generator yielding `FilePlan` with zero side effects;
   writer is the only module that touches the filesystem.
   Mirrors the existing `services/indexing.py` (pure
   resolution) vs `adapters/assembly/pdf_assembler.py`
   (I/O) split.
3. **No new `IDataSource` adapter.** Reuse
   `TabularDataSource` and `As400DataSource` as-is via the
   existing port. The mock generator is a CONSUMER of the
   same RVABREP shape the pipeline consumes; using the same
   adapters guarantees the column-override semantics
   (`IndexingColumnsModel`) match end-to-end.
4. **Size targeting via iteration, not formula.**
   `img2pdf` JPEG quality × noise density × page count is
   non-linear; a closed-form is more code than just trying
   5 parameter tuples and picking the closest. Documented
   tradeoff (Phase 2 Risk).
5. **`mock` group at top level, not under `inspect`.**
   `inspect` is read-only; `mock` writes files. Avoid
   implying that `mock` is harmless.
6. **No `--output-format json`.** Operator use case is
   "run, look at the filesystem". JSON output adds surface
   without a current consumer. Reconsider if CI starts
   parsing the summary line.
7. **`--seed None` for default randomness, not `0`.**
   Matches `random.Random(None)` semantics; `seed=0` is a
   valid deterministic seed and should not double as
   "use entropy".

---

## Module dependency graph

```
cli/commands/mock.py
    ├── services/mock/planner.py
    │     ├── services/mock/types.py
    │     ├── config/schema.py:IndexingColumnsModel
    │     ├── domain/exceptions.py:ConfigurationError
    │     └── domain/models.py:is_pdf_filename
    ├── services/mock/content.py
    │     └── services/mock/types.py
    ├── services/mock/sizing.py            (pure)
    ├── adapters/sources/tabular.py:TabularDataSource
    ├── adapters/sources/as400.py:As400DataSource
    └── config/loader.py:load_config
```

No cycles. `services/mock/types.py` is the only shared
dependency between `planner.py` and `content.py`.

---

## Total estimate

| Phase | Time | Difficulty |
|-------|------|------------|
| 1 — Sizing parser | ~30min | warm-up |
| 2 — Content writer | ~1.5h | heaviest (size targeting + img2pdf) |
| 3 — Planner | ~1h | most logic-dense (filters + dedup + path norm) |
| 4 — CLI + integration | ~1.5h | wiring + smoke |
| **Total** | **~4–5h** | |

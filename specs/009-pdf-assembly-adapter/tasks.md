# Tasks — 009-pdf-assembly-adapter

**Status**: Draft
**Spec**: `specs/009-pdf-assembly-adapter/spec.md`
**Plan**: `specs/009-pdf-assembly-adapter/plan.md`

---

## Phase 1 — Fixtures + tests RED

- [ ] **1.1 (R)** Create `tests/integration/adapters/conftest.py` with a
  session-scoped autouse fixture `_generate_assembly_fixtures` that
  materializes binary fixtures via Pillow:
  - `tests/fixtures/assembly/native_pdf/PROD/2025/11/17/0AAAUI0K.PDF` — 1-page PDF.
  - `tests/fixtures/assembly/paged_tiff/PROD/2025/11/17/DAAAH9X4.001..003` — 3 TIFFs.
  - `tests/fixtures/assembly/paged_jpeg/PROD/2025/11/17/DBBBI0L5.001..002` — 2 JPEGs.
  - `tests/fixtures/assembly/variable_padding/PROD/2025/01/01/DCCCH9X4.1`, `.2`, `.10` — sort test.
  - `tests/fixtures/assembly/paged_mismatch/PROD/2025/11/17/DEEEH9X4.001..003` — only 3 pages on disk.
  - `tests/fixtures/assembly/with_unrelated_pdf/PROD/2025/11/17/DFFFH9X4.001..002` + `OTHER.PDF`.
  All idempotent (skip if files exist).
- [ ] **1.2 (R)** Update `.gitignore`: ignore
  `tests/fixtures/assembly/**/*.{pdf,tif,tiff,jpg,jpeg}`. Confirm
  `.PDF` (uppercase) pattern matches via case-insensitive `find`.
- [ ] **1.3 (R)** Create `tests/integration/adapters/test_pdf_assembler.py`:
  - Module docstring, `pytestmark = pytest.mark.integration`.
  - Imports from `cmcourier.adapters.assembly` (yet-to-exist
    `PdfAssembler`, `AssemblerConfig`).
  - `_FIXTURES`, helper `_make_doc(file_name, image_path, total_pages, **overrides)`.
  - Module-level `pytestmark` for `pytest.mark.integration`.
- [ ] **1.4 (R)** Write 9 test groups per plan §5.2 (~18 tests):
  - `TestConstruction` (3): construction succeeds, OneDrive trap diverts, image_type_map default.
  - `TestNativePdfPassthrough` (3): copy succeeds + StagedFile shape, missing source raises, page_count from doc.
  - `TestPagedAssembly` (4): TIFF happy path, JPEG happy path, variable padding sort, glob excludes unrelated `.PDF`.
  - `TestPageCountMismatch` (1): WARNING emitted, assembly succeeds with discovered count.
  - `TestSourceFilesMissing` (1): empty glob raises `SourceFileMissingError`.
  - `TestFallbackPath` (2): monkey-patched img2pdf failure routes to fallback; fallback PDF is valid.
  - `TestBothPathsFail` (1): both img2pdf and Pillow fail → `PDFAssemblyFailedError`.
  - `TestOutputValidation` (2): output begins with `b'%PDF-'`, PyPDF2 reader counts pages.
  - `TestLoggingDiscipline` (1): mismatch WARNING contains `txn_num`+counts, never image bytes.
- [ ] **1.5 (R)** Run `pytest tests/integration/adapters/test_pdf_assembler.py -v`. Confirm collection ImportError.

---

## Phase 2 — Implementation GREEN

- [ ] **2.1 (G)** Create `src/cmcourier/adapters/assembly/pdf_assembler.py`:
  module docstring, `__all__`, imports (including `img2pdf`, `PIL.Image`,
  `PyPDF2.PdfMerger`), logger, `_ONEDRIVE_TRAP_VARIANTS`,
  `_DIVERTED_DIR_NAME`.
- [ ] **2.2 (G)** Implement `AssemblerConfig` dataclass per plan §3.1.
- [ ] **2.3 (G)** Implement `PdfAssembler.__init__(config)` with the
  OneDrive diversion per plan §4.1 and `mkdir(parents=True, exist_ok=True)`.
- [ ] **2.4 (G)** Implement `_passthrough_native_pdf` per plan §4.2.
- [ ] **2.5 (G)** Implement `_discover_pages` + `_is_numeric_ext` helper per plan §4.3.
- [ ] **2.6 (G)** Implement `_try_img2pdf` per plan §4.4.
- [ ] **2.7 (G)** Implement `_fallback_pillow_pypdf2` per plan §4.5.
- [ ] **2.8 (G)** Implement `_assemble_paged` orchestration per plan §4.6.
- [ ] **2.9 (G)** Implement public `assemble(doc)` dispatching on `doc.is_pdf`.
- [ ] **2.10 (G)** Update `src/cmcourier/adapters/assembly/__init__.py` to
  re-export `PdfAssembler` and `AssemblerConfig`.
- [ ] **2.11 (G)** Run `pytest tests/integration/adapters/test_pdf_assembler.py -v`. Iterate until all green.
- [ ] **2.12 (Rf)** Refactor for clarity. Verify every method ≤ 50 lines.

---

## Phase 3 — Verification

- [ ] **3.1** `ruff check src/ tests/` — clean.
- [ ] **3.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **3.3** `mypy src/cmcourier/` — clean.
- [ ] **3.4** `pytest --cov=src/cmcourier --cov-report=term-missing` —
  coverage on `adapters/assembly/pdf_assembler.py` ≥ 90%, total ≥ 80%.
- [ ] **3.5** `pre-commit run --all-files` — clean.

---

## Phase 4 — Docs + commit + merge FF

- [ ] **4.1** Update `CHANGELOG.md`:
  - "Planned for next release" → "S5 (CMIS upload) adapter, OR MVP orchestrator wiring S0..S6 (with S5 stub if upload not yet shipped)".
  - Add `[0.11.0] — 2026-05-10` entry: Added / Changed / Verification / Rationale.
- [ ] **4.2** Update `README.md` Status checklist: tick "Ninth change: PdfAssembler (S4)".
- [ ] **4.3** PII grep on new files. Synthetic identities only.
- [ ] **4.4** Stage all files. Expected status:
  ```
  modified: .gitignore
  modified: CHANGELOG.md
  modified: README.md
  modified: src/cmcourier/adapters/assembly/__init__.py
  added:    src/cmcourier/adapters/assembly/pdf_assembler.py
  added:    tests/integration/adapters/conftest.py
  added:    tests/integration/adapters/test_pdf_assembler.py
  added:    specs/009-pdf-assembly-adapter/{spec,plan,tasks}.md
  ```
- [ ] **4.5** Commit `feat(adapters): add PdfAssembler for stage S4` (full body per template below).
- [ ] **4.6** `git checkout main && git merge --ff-only feat/009-pdf-assembly-adapter && git branch -d feat/009-pdf-assembly-adapter`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..004 (construction + diversion) | 2.2, 2.3 + TestConstruction (1.4) |
| REQ-005..007 (native PDF) | 2.4 + TestNativePdfPassthrough |
| REQ-008..012 (page discovery) | 2.5 + TestPagedAssembly + TestPageCountMismatch + TestSourceFilesMissing |
| REQ-013..014 (img2pdf path) | 2.6 + TestPagedAssembly + TestOutputValidation |
| REQ-015..017 (fallback) | 2.7 + TestFallbackPath + TestBothPathsFail |
| REQ-018 (StagedFile shape) | 2.4, 2.8 + every test |
| REQ-019 (logging) | 2.5 + TestLoggingDiscipline |
| NFR-002 (coverage) | 3.4 |
| NFR-003 (50-line cap) | 2.12 |

---

## Estimated effort

- Phase 1 (fixtures + RED): 90 min
- Phase 2 (GREEN): 75 min
- Phase 3 (verification): 15 min
- Phase 4 (docs + commit + merge): 15 min
- **Total**: ~3 h 15 min

---

## Notes for the implementor

- Constitution Principle I: pdf_assembler.py imports `img2pdf`, `PIL`,
  `PyPDF2` (already in pyproject). Domain models are still pure stdlib.
- The OneDrive diversion list (`_ONEDRIVE_TRAP_VARIANTS`) is a `tuple`
  of normalized string variants (`"tmp"`, `"./tmp"`, `"tmp/"`, `".\\tmp"`).
  Normalize the input via `str(path).strip()` before comparing.
- `Image.save(buf, format='PDF')` requires the image mode be `RGB`,
  `RGBA`, `L`, or `P`. Mode `1` (1-bit B/W TIFF) may need explicit
  `convert('L')` or `convert('RGB')` first. The fallback handles this.
- `PyPDF2.PdfMerger` emits a `DeprecationWarning` on PyPDF2>=3.0. If
  the warning breaks `pytest -W error::DeprecationWarning` configured
  in some future change, switch to `PyPDF2.PdfWriter` + `add_page` per
  page. Today the warning is harmless.
- The autouse conftest generator must be FAST (the test suite already
  runs in ~25s). Generate fixtures in parallel where possible, and
  cache via existence check.

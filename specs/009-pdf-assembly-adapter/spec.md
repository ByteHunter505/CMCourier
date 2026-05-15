# Spec — 009-pdf-assembly-adapter

**Status**: Draft
**Stage**: S4 — File Verification & Assembly (the spec)
**Constitution alignment**: Principle I (hexagonal — concrete `IAssembler`),
III (single-responsibility), IV (streaming — single-pass disk write), VI
(real test pyramid — no img2pdf mocking, real binary fixtures).

---

## 1. Intent

Implement `PdfAssembler` — the concrete `IAssembler` that turns a
`RVABREPDocument` into a single staged PDF on disk. Native PDFs pass
through unchanged; paged documents are merged from their numbered page
files into one multi-page PDF.

This adapter is the engine of Stage S4 and a precondition for
Stage S5 (Upload). Combined with the service triangle and the tracking
store, it leaves only S5 + the orchestrator before the MVP pipeline runs.

---

## 2. Scope

### In scope

- `adapters/assembly/pdf_assembler.py` exporting `PdfAssembler` and
  `AssemblerConfig`.
- Native PDF passthrough: copy the source file to the temp directory under
  a canonical name and return a `StagedFile`.
- Paged-document assembly: discover `FILECODE.*` page files on disk, filter
  to numeric extensions, sort by `int(extension)`, build one multi-page PDF.
- **Primary path**: `img2pdf.convert` over the sorted page list.
- **Fallback path**: Pillow `Image.save(..., format='PDF')` per page +
  PyPDF2 `PdfMerger` to combine — used when img2pdf raises (mixed image +
  embedded-PDF pages per the spec).
- OneDrive temp-dir trap: if the configured `temp_dir` is
  any variant of `./tmp`, divert to `tempfile.gettempdir() / "cmcourier_tmp"`.
- Page-count consistency check: emit a `WARNING` if the discovered page
  count differs from `doc.total_pages`; do NOT raise.
- Typed error raising: `SourceFileMissingError`, `PDFAssemblyFailedError`.
- Integration tests over real binary fixtures (Pillow-generated TIFF /
  JPEG / multi-page PDF). Fixtures are session-scoped autouse generated;
  binaries are gitignored.

### Out of scope

- AS400 source file fetch (the file server is mounted locally; we read it
  directly). Configuring how it's mounted is the operator's job; the
  adapter accepts a `source_root` path.
- Page-by-page validation (e.g., readable image, non-zero size). The
  adapter trusts the file system. Corrupted images surface as PDFAssemblyFailedError.
- Cleanup of staged files. the spec's Stage S7 owns cleanup.
- Adaptive heavy/light lane awareness (post-MVP, the spec).

---

## 3. Functional requirements (RFC 2119)

### Construction

- **REQ-001** The constructor MUST accept an `AssemblerConfig` object with
  `source_root: Path` (where RVABREP files live) and `temp_dir: Path`
  (where staged PDFs are written).
- **REQ-002** `AssemblerConfig` MUST be a `frozen=True, slots=True`
  dataclass also exposing `image_type_map: Mapping[str, str]` with the
  default `{"B": "image/tiff", "O": "application/pdf", "C": "image/jpeg"}`
.
- **REQ-003** If `temp_dir` is any of `Path('tmp')`, `Path('./tmp')`,
  `Path('.\\tmp')`, or `Path('tmp/')`, the assembler MUST divert to
  `Path(tempfile.gettempdir()) / "cmcourier_tmp"`. The diversion path
  MUST be created (`mkdir(parents=True, exist_ok=True)`) at construction
  time.
- **REQ-004** The constructor MUST create `temp_dir` (or the diverted
  path) if it does not exist; existing non-empty dirs are accepted.

### Native PDF passthrough

- **REQ-005** `assemble(doc)` where `doc.is_pdf` is True MUST copy the
  source PDF (`source_root / doc.image_path / doc.file_name`) to
  `temp_dir / f"{doc.txn_num}.pdf"` via `shutil.copy2` (preserves mtime).
- **REQ-006** The returned `StagedFile.page_count` for a native PDF MUST
  equal `doc.total_pages` (trust the RVABREP value; do not parse the PDF).
- **REQ-007** If the source PDF is missing, the assembler MUST raise
  `SourceFileMissingError(file_path=...)` with the full absolute path.

### Paged-document assembly — page discovery

- **REQ-008** For non-PDF documents, the assembler MUST glob
  `source_root / doc.image_path / "<FILECODE>.*"` where `FILECODE` is
  `doc.file_name.split('.')[0]`.
- **REQ-009** The glob result MUST be filtered to entries whose extension
  is purely numeric (`ext.lstrip('0').isdigit() or ext == '0'`). The
  native PDF extension (`.PDF`) MUST be excluded.
- **REQ-010** The filtered pages MUST be sorted by `int(extension)`
  ascending. Variable padding (`.1`, `.01`, `.001`) is normalized by the
  integer sort.
- **REQ-011** If zero numeric pages are discovered, the assembler MUST
  raise `SourceFileMissingError(file_path=...)` with the glob pattern.
- **REQ-012** If the discovered page count differs from `doc.total_pages`,
  the assembler MUST emit a `WARNING` log naming `txn_num`,
  `expected=doc.total_pages`, `discovered=N`. Assembly continues — the
  filesystem is the source of truth.

### Paged-document assembly — img2pdf fast path

- **REQ-013** The assembler MUST attempt `img2pdf.convert(page_paths)`
  first, write the resulting bytes to `temp_dir / f"{doc.txn_num}.pdf"`,
  and return the corresponding `StagedFile`.
- **REQ-014** If `img2pdf.convert` raises ANY exception, the assembler
  MUST catch it, emit an `INFO` log "img2pdf fast path failed, falling
  back", and proceed to the fallback path. The original exception MUST
  be available via `__cause__` if both paths fail.

### Paged-document assembly — Pillow + PyPDF2 fallback

- **REQ-015** The fallback path MUST iterate each page file, open it
  with `PIL.Image.open`, convert to RGB if not already (PDF cannot
  embed alpha), and save to an in-memory `BytesIO` as a single-page PDF
  via `Image.save(..., format='PDF')`.
- **REQ-016** All per-page PDFs MUST be merged into one multi-page PDF
  with `PyPDF2.PdfMerger`. The merged result MUST be written to
  `temp_dir / f"{doc.txn_num}.pdf"`.
- **REQ-017** If the fallback path also raises, the assembler MUST
  raise `PDFAssemblyFailedError(txn_num=..., reason=...)` wrapping the
  fallback's exception via `from`. The img2pdf exception (if any) is
  the `__cause__`'s `__context__`.

### Return value

- **REQ-018** The returned `StagedFile` MUST have:
  - `path = temp_dir / f"{doc.txn_num}.pdf"`
  - `size_bytes = path.stat().st_size`
  - `page_count = len(discovered_pages)` for paged docs, or
    `doc.total_pages` for native PDFs.

### Logging discipline

- **REQ-019** Logs MUST identify operational keys (`txn_num`,
  `file_path`, `page_count`) but MUST NOT log document content,
  metadata values, or CIF.

---

## 4. Acceptance scenarios

### 4.1 Native PDF passthrough
- Given a `RVABREPDocument(file_name='0AAAUI0K.PDF', total_pages=1, ...)`
  and a real PDF at `source_root / image_path / '0AAAUI0K.PDF'`.
- When `assemble(doc)` is called.
- Then a copy lands at `temp_dir / 'TXN0000001.pdf'`, the returned
  `StagedFile.page_count == 1` and `size_bytes > 0`.

### 4.2 Native PDF missing
- Given a doc whose source PDF does not exist on disk.
- When `assemble(doc)` is called.
- Then `SourceFileMissingError` is raised with the full source path.

### 4.3 Paged TIFF assembly via img2pdf
- Given a paged doc with 3 TIFF page files `FILECODE.001`, `.002`, `.003`.
- When `assemble(doc)` is called.
- Then `temp_dir / '{txn}.pdf'` exists, is a valid PDF (header `b'%PDF-'`),
  and contains 3 pages (parseable by PyPDF2).
- And the returned `StagedFile.page_count == 3`.

### 4.4 Paged JPEG assembly
- Same as 4.3 but with JPEG pages. img2pdf supports both natively.

### 4.5 Variable-padded extensions sorted correctly
- Given pages `FILECODE.1`, `FILECODE.10`, `FILECODE.2` on disk.
- When assembled.
- Then the merged PDF's page order matches `[1, 2, 10]` (lexical sort
  would produce `[1, 10, 2]` and fail this test).

### 4.6 Page-count mismatch emits WARNING
- Given a doc with `total_pages=5` but only 3 page files on disk.
- When `assemble(doc)` is called.
- Then a `WARNING` log line names `expected=5`, `discovered=3`. Assembly
  succeeds with `StagedFile.page_count == 3`.

### 4.7 Zero pages raises SourceFileMissingError
- Given a doc whose `file_name='NONEXIST.001'` and no `NONEXIST.*` files
  exist in the source directory.
- When `assemble(doc)` is called.
- Then `SourceFileMissingError` is raised.

### 4.8 img2pdf failure falls back to Pillow/PyPDF2
- Given a paged doc whose img2pdf path raises (simulated by monkey-
  patching `img2pdf.convert` in the test).
- When `assemble(doc)` is called.
- Then the fallback path runs, the resulting PDF is valid and the
  expected page count, and an `INFO` log records the fallback.

### 4.9 Both paths fail raise PDFAssemblyFailedError
- Given a paged doc whose img2pdf AND Pillow paths both raise
  (corrupt image file).
- When `assemble(doc)` is called.
- Then `PDFAssemblyFailedError(txn_num=..., reason=...)` is raised.

### 4.10 OneDrive temp-dir diversion
- Given `AssemblerConfig(temp_dir=Path('./tmp'))`.
- When the assembler is constructed.
- Then the actual temp dir is `Path(tempfile.gettempdir()) / 'cmcourier_tmp'`
  and the dir exists.

### 4.11 Glob excludes the source PDF when paged-doc lookup
- Given a paged document whose source directory ALSO contains an
  unrelated `OTHER.PDF` file.
- When `assemble(doc)` is called for the paged doc.
- Then the `.PDF` file is NOT included in the merged output.

### 4.12 image_type_map default matches the spec
- Given an `AssemblerConfig()` (no override).
- Then `image_type_map == {"B": "image/tiff", "O": "application/pdf",
  "C": "image/jpeg"}`.

---

## 5. Non-functional requirements

- **NFR-001** Single-pass disk write per document (Constitution IV): one
  `.pdf` file per document, written once. No staging intermediates left
  behind on success.
- **NFR-002** Branch coverage on `adapters/assembly/pdf_assembler.py`
  MUST be ≥ 90%.
- **NFR-003** Function length cap (Constitution III): every method ≤ 50
  lines.
- **NFR-004** No third-party imports in the test file other than
  `pytest`, `PIL` (for fixture generation), and `PyPDF2` (for output
  validation).

---

## 6. Tooling expectations

- `ruff check src/ tests/`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.adapters.assembly.*`: clean (note: `img2pdf`
  and `PyPDF2` are typed as `ignore_missing_imports` in `pyproject.toml`).
- `pre-commit run --all-files`: clean.
- `pytest`: full suite passes; net positive test count.

---

## 7. Open questions / risks

- **Risk**: `img2pdf` rejects images larger than the `Image.MAX_IMAGE_PIXELS`
  Pillow safety threshold. Mitigation: out of scope for MVP; if it surfaces,
  bump the threshold in a follow-up.
- **Risk**: Pillow on linux may default to PIL_TIFF and miss some
  uncommon TIFF compressions. Mitigation: tests use synthetic
  uncompressed TIFFs; production TIFFs from AS400 are CCITT/G4 which
  Pillow handles via libtiff.
- **Risk**: PyPDF2 v3.0 deprecated `PdfMerger` in favor of `PdfWriter`.
  Mitigation: we pin `PyPDF2>=3.0,<4.0` and use whichever API works on
  the resolved version; if the deprecation becomes hard, switch to
  `pypdf` (the rebranded library) in a domain-amendment change.
- **Open question**: should the assembler also produce a sidecar
  manifest (page list, hash)? **Resolved**: no — the StagedFile is the
  contract; manifesting is a tracking-store concern if ever needed.

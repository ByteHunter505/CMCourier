# Plan — 009-pdf-assembly-adapter

**Status**: Draft
**Spec**: `specs/009-pdf-assembly-adapter/spec.md`

---

## 1. Architecture in one paragraph

A single class `PdfAssembler` implementing `IAssembler`, constructed with
an `AssemblerConfig` (source root + temp dir + image-type hint map). The
constructor handles the OneDrive temp-dir diversion (REBIRTH §7.4) and
ensures the temp dir exists. `assemble(doc)` dispatches on `doc.is_pdf`:
native PDFs pass through via `shutil.copy2`; paged documents are routed
through `_discover_pages` → `_img2pdf_fast_path` → `_pillow_pypdf2_fallback`.
The module lives at `src/cmcourier/adapters/assembly/pdf_assembler.py` and
is re-exported from `adapters/assembly/__init__.py`.

---

## 2. Module layout

```
src/cmcourier/adapters/assembly/pdf_assembler.py
├── AssemblerConfig                    # frozen+slots dataclass
├── _ONEDRIVE_TRAP_VARIANTS            # tuple[str, ...] for the OneDrive avoidance
├── _DIVERTED_DIR_NAME                 # "cmcourier_tmp"
├── PdfAssembler                       # the IAssembler implementation
│   ├── __init__(config)
│   ├── assemble(doc) -> StagedFile
│   ├── _passthrough_native_pdf(doc) -> StagedFile
│   ├── _assemble_paged(doc) -> StagedFile
│   ├── _discover_pages(doc) -> list[Path]
│   ├── _try_img2pdf(pages, output_path) -> None
│   └── _fallback_pillow_pypdf2(pages, output_path) -> None
```

Every method ≤ 50 lines.

---

## 3. Public API contracts

### 3.1 `AssemblerConfig`

```python
@dataclass(frozen=True, slots=True)
class AssemblerConfig:
    source_root: Path
    temp_dir: Path
    image_type_map: Mapping[str, str] = field(
        default_factory=lambda: {
            "B": "image/tiff",
            "O": "application/pdf",
            "C": "image/jpeg",
        }
    )
```

Note: `Mapping` (not `dict`) for read-only contract; `field(default_factory=...)`
because dataclasses reject mutable defaults.

### 3.2 `PdfAssembler.assemble`

```python
def assemble(self, document: RVABREPDocument) -> StagedFile:
    """Stage S4: turn a RVABREPDocument into a single staged PDF.

    Raises:
        SourceFileMissingError: source PDF or every page file missing.
        PDFAssemblyFailedError: img2pdf AND Pillow/PyPDF2 both failed.
    """
```

Implements `IAssembler.assemble` exactly.

---

## 4. Algorithm sketches

### 4.1 OneDrive diversion (constructor)

```python
TRAP = {Path("tmp"), Path("./tmp"), Path(".\\tmp"), Path("tmp/")}

def _resolve_temp_dir(configured: Path) -> Path:
    # Normalize: anything that resolves to "./tmp" relative gets diverted.
    if configured in TRAP or str(configured).lower() in {"tmp", "./tmp", "tmp/", ".\\tmp"}:
        return Path(tempfile.gettempdir()) / "cmcourier_tmp"
    return configured
```

Always `mkdir(parents=True, exist_ok=True)` after resolution.

### 4.2 Native PDF passthrough

```python
def _passthrough_native_pdf(self, doc):
    src = self._cfg.source_root / doc.image_path / doc.file_name
    if not src.is_file():
        raise SourceFileMissingError(file_path=str(src))
    dst = self._temp_dir / f"{doc.txn_num}.pdf"
    shutil.copy2(src, dst)
    return StagedFile(
        path=dst,
        size_bytes=dst.stat().st_size,
        page_count=doc.total_pages,
    )
```

### 4.3 Page discovery

```python
def _discover_pages(self, doc):
    source_dir = self._cfg.source_root / doc.image_path
    file_code = doc.file_name.split(".")[0]
    pattern = f"{file_code}.*"
    candidates = sorted(
        (p for p in source_dir.glob(pattern) if _is_numeric_ext(p.suffix.lstrip("."))),
        key=lambda p: int(p.suffix.lstrip(".")),
    )
    if not candidates:
        raise SourceFileMissingError(
            file_path=str(source_dir / pattern),
        )
    if len(candidates) != doc.total_pages:
        _log.warning(
            "assembler: page count mismatch",
            extra={
                "txn_num": doc.txn_num,
                "expected": doc.total_pages,
                "discovered": len(candidates),
            },
        )
    return candidates


def _is_numeric_ext(text: str) -> bool:
    return bool(text) and text.isdigit()
```

### 4.4 img2pdf fast path

```python
def _try_img2pdf(self, pages, output_path):
    # img2pdf.convert raises on mixed content or unsupported image types.
    pdf_bytes = img2pdf.convert([str(p) for p in pages])
    if pdf_bytes is None:
        raise PDFAssemblyFailedError(
            txn_num=...,  # caller wraps
            reason="img2pdf returned None",
        )
    output_path.write_bytes(pdf_bytes)
```

### 4.5 Pillow + PyPDF2 fallback

```python
def _fallback_pillow_pypdf2(self, pages, output_path):
    merger = PdfMerger()
    try:
        for page in pages:
            with Image.open(page) as img:
                rgb = img.convert("RGB") if img.mode != "RGB" else img
                buf = BytesIO()
                rgb.save(buf, format="PDF")
                buf.seek(0)
                merger.append(buf)
        with output_path.open("wb") as out:
            merger.write(out)
    finally:
        merger.close()
```

Note: `PdfMerger` exists in PyPDF2 v3 (deprecated alias of `PdfWriter`).
Imports use it without warnings filter; if a future PyPDF2 / pypdf bump
removes it, swap to `PdfWriter`.

### 4.6 Orchestration: `_assemble_paged`

```python
def _assemble_paged(self, doc):
    pages = self._discover_pages(doc)
    output_path = self._temp_dir / f"{doc.txn_num}.pdf"
    try:
        self._try_img2pdf(pages, output_path)
    except Exception as primary:  # noqa: BLE001 — img2pdf raises wide
        _log.info(
            "assembler: img2pdf fast path failed, falling back",
            extra={"txn_num": doc.txn_num, "reason": str(primary)},
        )
        try:
            self._fallback_pillow_pypdf2(pages, output_path)
        except Exception as secondary:
            raise PDFAssemblyFailedError(
                txn_num=doc.txn_num,
                reason=f"img2pdf and fallback both failed: {secondary!r}",
            ) from secondary
    return StagedFile(
        path=output_path,
        size_bytes=output_path.stat().st_size,
        page_count=len(pages),
    )
```

The `except Exception` is intentional — img2pdf raises a variety of types
(ValueError, `img2pdf.ImageOpenError`, etc.) and the contract is "any
exception → fallback".

---

## 5. Test plan

### 5.1 Fixture generation strategy

Following the precedent set in change 003 / change 005:
- Commit only text/structural fixtures.
- Generate binary fixtures (`.pdf`, `.tif`, `.jpg`) at session start via a
  `tests/integration/adapters/conftest.py` autouse fixture using Pillow.
- `.gitignore` the generated binaries.

Generated fixtures under `tests/fixtures/assembly/`:
- `native_pdf/PROD/2025/11/17/0AAAUI0K.PDF` — 1-page synthetic PDF.
- `paged_tiff/PROD/2025/11/17/DAAAH9X4.001..003` — 3-page synthetic TIFFs.
- `paged_jpeg/PROD/2025/11/17/DBBBI0L5.001..002` — 2-page synthetic JPEGs.
- `variable_padding/PROD/2025/01/01/DCCCH9X4.1`, `.2`, `.10` — pages
  with mixed padding for the sort test.
- `paged_mismatch/PROD/2025/11/17/DEEEH9X4.001..003` — 3 pages but the
  test's `RVABREPDocument` claims `total_pages=5` (WARN test).
- `with_unrelated_pdf/PROD/2025/11/17/DFFFH9X4.001..002` PLUS
  `OTHER.PDF` for the "glob excludes PDF" test.

The conftest generator is idempotent (skips creation if files exist).

### 5.2 Tests in `tests/integration/adapters/test_pdf_assembler.py`

Grouped tests with counts:

| Group | Tests | Acceptance scenarios |
|-------|-------|----------------------|
| Construction & temp dir | 3 | 4.10, 4.12 + defaults |
| Native PDF passthrough | 3 | 4.1, 4.2 + page_count from doc |
| Paged assembly happy path | 4 | 4.3, 4.4, 4.5, 4.11 |
| Page-count mismatch | 1 | 4.6 |
| Source-files missing | 1 | 4.7 |
| Fallback path (img2pdf monkey-patched) | 2 | 4.8 + fallback succeeds |
| Both paths fail | 1 | 4.9 |
| Output validation (PyPDF2 reader) | 2 | output is valid PDF / correct page count |
| Logging discipline | 1 | mismatch WARNING shape |

Total: ~18 tests.

### 5.3 Output validation strategy

Tests open the generated PDF with `PyPDF2.PdfReader` and assert
`len(reader.pages) == expected`. The first bytes are checked for `b"%PDF-"`.

### 5.4 Monkey-patching img2pdf

For tests 4.8 and 4.9, the test monkey-patches `img2pdf.convert` in the
`cmcourier.adapters.assembly.pdf_assembler` module's namespace via
`monkeypatch.setattr`. This is a localized, well-scoped intervention — not
a wholesale mock of the module.

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..004 (construction) | §3.1, §4.1 | Construction & temp dir |
| REQ-005..007 (native PDF) | §4.2 | Native PDF passthrough |
| REQ-008..012 (page discovery) | §4.3 | Paged happy path + mismatch + missing |
| REQ-013..014 (img2pdf path) | §4.4, §4.6 | Paged happy path |
| REQ-015..017 (fallback) | §4.5, §4.6 | Fallback tests |
| REQ-018 (StagedFile shape) | §4.2, §4.6 | All tests assert StagedFile fields |
| REQ-019 (logging) | §4.3 | Logging discipline |
| NFR-001 (single-pass) | §4.5, §4.6 | Implicit — single `output_path.write` per call |
| NFR-002 (coverage ≥90%) | — | `pytest --cov` |
| NFR-003 (50-line cap) | — | Visual review |

---

## 7. Files touched

```
NEW   src/cmcourier/adapters/assembly/pdf_assembler.py
EDIT  src/cmcourier/adapters/assembly/__init__.py   # re-export
NEW   tests/integration/adapters/test_pdf_assembler.py
NEW   tests/integration/adapters/conftest.py        # binary fixture generator
EDIT  .gitignore                                    # ignore tests/fixtures/assembly/**/*.{pdf,tif,jpg}
EDIT  CHANGELOG.md                                  # [0.11.0]
EDIT  README.md                                     # Status checklist
NEW   specs/009-pdf-assembly-adapter/{spec,plan,tasks}.md
```

No domain changes. No new dependencies (img2pdf, Pillow, PyPDF2 already
in `pyproject.toml`).

---

## 8. Risks

- **Risk**: PyPDF2 `PdfMerger` deprecation warning may surface in test
  output. **Mitigation**: silence via `warnings.filterwarnings` inside the
  test's caplog block OR migrate to `PdfWriter`. Prefer the latter if
  trivial.
- **Risk**: Pillow's `Image.save(format='PDF')` produces fixed-DPI output;
  not page-size-faithful for production scans. **Mitigation**: not a
  correctness issue for MVP — img2pdf is the primary path; fallback is
  for the rare mixed-content case.
- **Risk**: synthetic TIFFs may exercise different Pillow code paths than
  production TIFFs (CCITT-G4). **Mitigation**: acceptable for MVP;
  production validation is the operator's smoke test, not the unit suite.

---

## 9. Estimated effort

- Spec / plan / tasks (this commit): done
- Phase 1 (tests RED + fixtures): ~90 min
- Phase 2 (impl GREEN): ~75 min
- Phase 3 (verification): ~15 min
- Phase 4 (docs + commit + merge): ~15 min
- **Total**: ~3h 15min

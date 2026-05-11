# Plan — 019-port-hygiene

**Status**: Draft
**Spec**: `specs/019-port-hygiene/spec.md`

---

## 1. Architecture in one paragraph

Two-line code change per adapter: import the port + add it to the
class bases. Two new tests assert `isinstance` returns `True`. mypy
validates signature alignment automatically. Zero behavioral
changes. The Python ABC machinery guards against any future drift
by raising `TypeError` at instantiation if a required method goes
missing.

---

## 2. Module layout

```
src/cmcourier/adapters/assembly/pdf_assembler.py   # +1 import, +inheritance
src/cmcourier/adapters/upload/cmis_uploader.py     # +1 import, +inheritance
tests/integration/adapters/test_pdf_assembler.py   # +1 test
tests/integration/adapters/test_cmis_uploader.py   # +1 test (or wherever it lives)
```

No new modules. No new fixtures.

---

## 3. Code diffs

### 3.1 `pdf_assembler.py`

```python
# import block
from cmcourier.domain.ports import IAssembler

# class declaration
class PdfAssembler(IAssembler):  # was: class PdfAssembler:
    ...
```

### 3.2 `cmis_uploader.py`

```python
# import block
from cmcourier.domain.ports import IUploader

# class declaration
class CmisUploader(IUploader):  # was: class CmisUploader:
    ...
```

---

## 4. Test plan

### 4.1 PdfAssembler conformance

In `tests/integration/adapters/test_pdf_assembler.py` (or
equivalent), add:

```python
def test_pdf_assembler_is_iassembler(tmp_path: Path) -> None:
    from cmcourier.adapters.assembly.pdf_assembler import (
        AssemblerConfig, PdfAssembler,
    )
    from cmcourier.domain.ports import IAssembler

    cfg = AssemblerConfig(source_root=tmp_path, temp_dir=tmp_path / "stg")
    pa = PdfAssembler(cfg)
    assert isinstance(pa, IAssembler)
```

### 4.2 CmisUploader conformance

Symmetric test in `tests/integration/adapters/test_cmis_uploader.py`
(or the file that exists):

```python
def test_cmis_uploader_is_iuploader() -> None:
    from cmcourier.adapters.upload.cmis_uploader import (
        CmisConfig, CmisUploader,
    )
    from cmcourier.domain.ports import IUploader

    cfg = CmisConfig(
        base_url="http://x:9080/cmis",
        repo_id="$x!t",
        username="u",
        password="p",
    )
    cu = CmisUploader(cfg)
    assert isinstance(cu, IUploader)
```

### 4.3 Existing tests

The full suite (465 currently) MUST pass with no modifications.

---

## 5. Verification matrix

| Spec REQ | Implementation | Test(s) |
|----------|---------------|---------|
| REQ-001 (PdfAssembler inherits) | §3.1 | test_pdf_assembler_is_iassembler |
| REQ-002 (CmisUploader inherits) | §3.2 | test_cmis_uploader_is_iuploader |
| REQ-003 (imports) | §3.1, §3.2 | mypy run |
| REQ-004 (assemble matches port) | §3.1 | mypy run |
| REQ-005 (4 uploader methods match port) | §3.2 | mypy run + ABC instantiation check |
| REQ-006..007 (no behavior change) | §3.1, §3.2 | existing tests pass |
| REQ-008..009 (isinstance tests) | §4.1, §4.2 | new tests |
| REQ-010 (suite green) | — | pytest |
| REQ-011 (mypy clean) | — | mypy |
| REQ-012 (≥467 tests) | §4 | pytest |

---

## 6. Files touched

```
EDIT  src/cmcourier/adapters/assembly/pdf_assembler.py
EDIT  src/cmcourier/adapters/upload/cmis_uploader.py
EDIT  tests/integration/adapters/test_pdf_assembler.py  (or matching file)
EDIT  tests/integration/adapters/test_cmis_uploader.py  (or matching file)
EDIT  CHANGELOG.md
EDIT  README.md
NEW   specs/019-port-hygiene/{spec,plan,tasks}.md
```

No new dependencies. No new fixtures.

---

## 7. Risks

- **R1**: A missing port method on the adapter would surface as a
  `TypeError` at instantiation time (Python ABC). Today both
  adapters implement every port method, so this is theoretical —
  but if it bites, the fix is to either add the method or remove
  it from the port. Mitigation: the new isinstance tests trigger
  instantiation, so the guard fires in CI.
- **R2**: Type-annotation mismatches between adapter and port (e.g.,
  `Mapping[str, str]` vs `dict[str, str]`) MAY surface as mypy
  errors after inheritance. Mitigation: run mypy locally before
  committing; align signatures to the port if needed.
- **R3**: Multiple inheritance with `ABC`-based ports MAY interact
  oddly if either adapter has another base class. Mitigation:
  neither currently has any other base — single inheritance.
  Confirmed by `rg "^class (PdfAssembler|CmisUploader)"`.

---

## 8. Estimated effort

- Spec / plan / tasks: 20 min (done)
- Phase 1 (PdfAssembler + test): 15 min
- Phase 2 (CmisUploader + test): 15 min
- Phase 3 (verification + docs + commit + merge): 20 min
- **Total**: ~70 min

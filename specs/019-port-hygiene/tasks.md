# Tasks — 019-port-hygiene

**Status**: Draft
**Spec**: `specs/019-port-hygiene/spec.md`
**Plan**: `specs/019-port-hygiene/plan.md`

---

## Phase 1 — PdfAssembler inherits IAssembler

- [ ] **1.1 (R)** Add `test_pdf_assembler_is_iassembler` to the
  PdfAssembler test file (or create a small new file if no
  existing one fits).
- [ ] **1.2 (G)** Edit `src/cmcourier/adapters/assembly/pdf_assembler.py`:
  - Add `from cmcourier.domain.ports import IAssembler`.
  - Change `class PdfAssembler:` to `class PdfAssembler(IAssembler):`.
- [ ] **1.3** Run targeted tests. Green.

---

## Phase 2 — CmisUploader inherits IUploader

- [ ] **2.1 (R)** Add `test_cmis_uploader_is_iuploader` to the
  CmisUploader test file.
- [ ] **2.2 (G)** Edit `src/cmcourier/adapters/upload/cmis_uploader.py`:
  - Add `from cmcourier.domain.ports import IUploader`.
  - Change `class CmisUploader:` to `class CmisUploader(IUploader):`.
- [ ] **2.3** Run targeted tests. Green.

---

## Phase 3 — Verification + docs + commit + merge FF

- [ ] **3.1** `ruff check src/ tests/` — clean.
- [ ] **3.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **3.3** `mypy src/cmcourier/` — clean. Investigate any new
  errors as port/adapter alignment issues.
- [ ] **3.4** `pytest --cov=src/cmcourier --cov-report=term` —
  ≥467 pass, total coverage ≥80%.
- [ ] **3.5** `pre-commit run --all-files` — clean.
- [ ] **3.6** Update `CHANGELOG.md`:
  - Remove "Adapter port-hygiene cleanup" from Planned section.
  - Add `[0.21.0] — 2026-05-10` entry.
- [ ] **3.7** Update `README.md` Status checklist: tick
  "Nineteenth change: adapter port-hygiene cleanup".
- [ ] **3.8** PII grep on new content.
- [ ] **3.9** Stage. Commit:
  `refactor(adapters): declare IAssembler/IUploader conformance on adapters`.
- [ ] **3.10** `git checkout main && git merge --ff-only feat/019-port-hygiene && git branch -d feat/019-port-hygiene`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001 (PdfAssembler inherits) | 1.2 |
| REQ-002 (CmisUploader inherits) | 2.2 |
| REQ-003 (imports) | 1.2, 2.2 |
| REQ-004..005 (sig conformance) | 3.3 |
| REQ-006..007 (no behavior change) | 3.4 |
| REQ-008..009 (isinstance tests) | 1.1, 2.1 |
| REQ-010..012 (verification) | 3.1..3.5 |

---

## Estimated effort

- Phase 1: 15 min
- Phase 2: 15 min
- Phase 3: 20 min
- **Total**: ~50 min

---

## Notes for the implementor

- Both adapters already implement every port method with matching
  signatures. The change is purely declarative.
- Python's ABC machinery raises `TypeError` at instantiation if
  any abstract method is missing — this is the runtime guard.
- mypy's override-check is the static guard against future drift.
- Test file locations: check whether `tests/integration/adapters/`
  has files for assembler/uploader. If not, create
  `test_pdf_assembler.py` and `test_cmis_uploader.py` with a
  single conformance test each. Don't duplicate existing behavioral
  tests.

# Spec — 019-port-hygiene

**Status**: Draft
**Owner**: bitBreaker
**Date**: 2026-05-10
**Predecessors**: 008 (PdfAssembler), 009 (CmisUploader)
**Successors**: TBD

---

## 1. Problem

Constitution Principle I (hexagonal architecture) commits to a
strict port/adapter split: every adapter MUST declare conformance to
its port via formal inheritance. Today the project is 60% there:

| Port | Adapter | Inherits? |
|------|---------|-----------|
| `IDataSource` | `TabularDataSource` | ✅ |
| `IDataSource` | `As400DataSource` | ✅ |
| `ITrackingStore` | `SQLiteTrackingStore` | ✅ |
| `IAssembler` | `PdfAssembler` | ❌ |
| `IUploader` | `CmisUploader` | ❌ |
| `S0Strategy` | 5 strategies (csv / rvabrep / as400 / local_scan / single_doc) | ✅ |

`PdfAssembler` and `CmisUploader` implement the port methods
structurally (duck typing works) but never declare the inheritance.
This leaves two cracks:

1. **mypy drift**: if a port method's signature changes, mypy does
   not flag the adapter. Today the signatures happen to match, but
   nothing enforces alignment going forward.
2. **`isinstance` checks fail**: doctor / test code that wants to
   assert "this is a real IUploader" has to fall back to structural
   checks or skip the assertion entirely.

the spec (assembler) and §8 (uploader) both explicitly reference
the ports as the contract surface. This change closes the gap with
zero behavioral changes — pure declarative cleanup.

---

## 2. Goals

- **G1**: `PdfAssembler` formally inherits from `IAssembler`.
- **G2**: `CmisUploader` formally inherits from `IUploader`.
- **G3**: `isinstance(adapter, port)` returns `True` at runtime for
  both.
- **G4**: mypy validates the override signatures against each port's
  abstract methods.
- **G5**: Zero behavioral changes. No method body, signature, or
  call-site changes.

## 3. Non-goals

- **NG1**: Changing the port surface itself (add/remove/rename
  methods). The ports are stable — this change is pure conformance.
- **NG2**: Migrating from `ABC` to `Protocol`. The existing
  inheritance pattern works; switching would be a larger refactor.
- **NG3**: Adding new ports (e.g., for the orchestrator or services).
  Out of scope.
- **NG4**: Touching any of the already-conforming adapters
  (`TabularDataSource`, `As400DataSource`, `SQLiteTrackingStore`,
  the 5 S0 strategies).

---

## 4. Requirements (RFC 2119)

### Inheritance declarations

- **REQ-001**: `cmcourier.adapters.assembly.pdf_assembler.PdfAssembler`
  MUST declare `class PdfAssembler(IAssembler):`.
- **REQ-002**: `cmcourier.adapters.upload.cmis_uploader.CmisUploader`
  MUST declare `class CmisUploader(IUploader):`.
- **REQ-003**: Both adapters MUST import their respective port from
  `cmcourier.domain.ports`.

### Method conformance

- **REQ-004**: After inheritance, `PdfAssembler.assemble` MUST match
  the `IAssembler.assemble` abstract signature (verified by mypy on
  the override).
- **REQ-005**: After inheritance, all four `IUploader` abstract
  methods (`ensure_folder`, `upload`, `test_connection`,
  `get_type_definition`) MUST be present on `CmisUploader` with
  matching signatures (verified by mypy + by Python's ABC
  instantiation check at runtime — instantiating an abstract class
  with missing methods raises `TypeError`).

### Behavior

- **REQ-006**: No method bodies are modified. The existing
  implementation is the truth.
- **REQ-007**: No call sites are modified. Existing usages of
  `PdfAssembler` and `CmisUploader` keep working unchanged.

### Tests

- **REQ-008**: ≥1 new test verifies `isinstance(pdf_assembler,
  IAssembler)` returns `True`.
- **REQ-009**: ≥1 new test verifies `isinstance(cmis_uploader,
  IUploader)` returns `True`.
- **REQ-010**: The full existing test suite MUST keep passing
  without modification. Behavioral coverage is unchanged.

### Verification

- **REQ-011**: `mypy src/cmcourier/` MUST report zero errors. Any
  drift between adapter and port surfaces SHALL be caught here.
- **REQ-012**: `pytest` MUST report ≥465 tests passing (current
  baseline + 2 new).

---

## 5. Acceptance scenarios

1. **Inheritance declared (assembler)**: `PdfAssembler.__mro__`
   contains `IAssembler` after the change.
2. **Inheritance declared (uploader)**: `CmisUploader.__mro__`
   contains `IUploader`.
3. **Runtime isinstance check passes**: a unit test instantiates
   each adapter and asserts `isinstance(instance, port)` is `True`.
4. **ABC instantiation guard**: if a future change accidentally
   removes one of the `IUploader` methods from `CmisUploader`,
   `CmisUploader(...)` raises `TypeError: Can't instantiate
   abstract class CmisUploader with abstract method
   <missing-method>`. (This guard is automatic from Python's ABC;
   no test needed.)
5. **mypy override check**: any future drift in port signatures
   (e.g., adding a new required positional parameter) surfaces as
   a mypy error on the adapter override.
6. **No call-site changes**: `git diff` on `orchestrators/`,
   `cli/`, `config/wiring.py` shows no edits.
7. **No test failures**: full suite passes including the 465
   existing tests.

---

## 6. Out of scope (explicit)

- Migrating ports to `Protocol` style.
- Adding new ports (e.g., for orchestrators).
- Refactoring adapter internals.
- Renaming methods or constants.
- Touching the doctor pre-flight surface.

---

## 7. References

- 008 — PdfAssembler shipped
- 009 — CmisUploader shipped
- the spec (assembler), §8 (uploader)
- Constitution Principle I (hexagonal architecture / ports & adapters)

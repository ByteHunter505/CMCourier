# 046 — Polymorphic Trigger model

## Why

The current ``TriggerRecord`` is a fixed 3-tuple ``(shortname, cif,
system_id)`` that every S0 strategy is forced to produce. Every S1
pass then re-queries RVABREP by ``(shortname, system_id)`` to
expand the trigger into a list of documents. That model is the
natural fit for **only one** pipeline kind (csv-trigger, where the
CSV literally is a client roster). For every other pipeline it's
the wrong granularity and creates real semantic bugs:

### local-scan: wrong upload set

Today's flow (``services/triggers/local_scan.py``):

1. ``iterdir(scan_path)`` finds 1 file: ``foo.001``.
2. ``rvabrep.get_by_fields({file_name: 'foo.001'})`` returns the
   matching RVABREP row — **the full row**, with txn_num,
   file_name, page_count, everything.
3. The strategy throws all of that away and yields
   ``TriggerRecord(shortname=X, cif=Y, system_id=Z)``.
4. S1 ``find_documents(trigger)`` re-queries RVABREP by
   ``(X, Z)`` and returns **every doc of client X**.
5. The pipeline uploads all docs of client X to CMIS, not just
   ``foo.001``.

This is what §E.4 of the validation checklist surfaced: a scan
pool of 100 files produced 1860 uploaded docs. I misdiagnosed it
as a "missing dedup bug" in 046's predecessor analysis. The real
issue is **the trigger shape doesn't match what local-scan
semantically means**. An operator who drops a file into a scan
directory expects that one file to be migrated, not all
documents belonging to that file's owning client.

### rvabrep-direct: double work + over-broad dedup

Today's flow (``services/triggers/direct_rvabrep.py:44-89``):

1. Scan the RVABREP source (CSV or AS400).
2. **Dedup by ``(shortname, system_id)``** — collapse N rows of a
   client into one trigger.
3. Yield ``TriggerRecord(shortname, cif, system_id)``.
4. S1 re-queries the same RVABREP source by the same
   ``(shortname, system_id)`` to re-expand to those same N rows.

The whole dedup-then-re-expand round-trip is wasted work. Worse:
when an operator wants to migrate a specific RVABREP slice (e.g.
by document_type filter), the current model first collapses,
then re-expands without the filter context.

### Conceptual mismatch

A trigger is **whatever disparates a doc through the pipeline**.
Its natural shape depends on what the disparador IS:

| Pipeline | Natural trigger | Semantic meaning |
|---|---|---|
| csv-trigger | row of the trigger CSV | "process every doc of this client" |
| rvabrep-direct | row of RVABREP | "process THIS doc" |
| local-scan | a file on disk | "process the doc backing this file" |
| as400-trigger | row from operator SQL (typically NIARVILOG) | "process THIS work-item" |
| single-doc | CLI args | "process docs matching this (sn, sys[, cif])" |

S1's job is **enrichment**, not universal re-expansion. The
enrichment a trigger needs depends on what the trigger already
carries.

## What

### 1. New ``Trigger`` hierarchy

``domain/models.py`` introduces an abstract ``Trigger`` base + four
concrete subtypes:

```python
class Trigger:
    """ABC for everything that can disparar one or more docs."""
    def audit_row(self) -> dict[str, str | None]: ...  # for migration_log

@dataclass(frozen=True, slots=True)
class ClientTrigger(Trigger):
    """csv-trigger + single-doc: a client tuple expanded by S1."""
    shortname: str
    cif: str | None
    system_id: str

@dataclass(frozen=True, slots=True)
class RvabrepRowTrigger(Trigger):
    """rvabrep-direct + as400-trigger: one RVABREP row is one doc.
    Carries the full row so S1 skips the re-query.
    """
    row: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class LocalScanTrigger(Trigger):
    """local-scan: a file on disk + the RVABREP row that describes
    it. S1 produces exactly one RVABREPDocument for this file.
    """
    file_path: Path
    row: Mapping[str, Any]
```

``TriggerRecord`` becomes a backward-compat alias for
``ClientTrigger`` so existing code (csv-trigger, single-doc,
tests) keeps compiling.

### 2. S1 ``IndexingService`` becomes polymorphic

The new contract: S1 **enriches** a trigger into a list of
``RVABREPDocument`` instances. Dispatch by trigger type:

```python
def enrich(self, trigger: Trigger) -> list[RVABREPDocument]:
    match trigger:
        case ClientTrigger():
            return self._expand_client(trigger)          # today's find_documents
        case RvabrepRowTrigger(row=row):
            return [self._row_to_document(row)]          # one doc, no query
        case LocalScanTrigger(row=row):
            return [self._row_to_document(row)]          # one doc, no query
```

``find_documents`` and ``find_documents_batch`` stay for the
``ClientTrigger`` path (csv-trigger uses the batched IN-list query
to amortize 50 lookups). The other subtypes don't need batching
because their row is already known.

### 3. S0 strategies emit the right subtype

- ``CsvTriggerStrategy`` → ``ClientTrigger`` (no change in shape).
- ``DirectRvabrepTriggerStrategy`` → ``RvabrepRowTrigger`` per
  matched row. **Dedup by ``(shortname, system_id)`` is dropped**.
  Operators who want one trigger per client should use
  csv-trigger; rvabrep-direct now means literal "one trigger per
  RVABREP row".
- ``LocalScanTriggerStrategy`` → ``LocalScanTrigger`` per scanned
  file. When the file matches multiple RVABREP rows (rare —
  filename collision across systems), emit one
  ``LocalScanTrigger`` per matched row.
- ``As400TriggerStrategy`` → ``RvabrepRowTrigger`` per SQL row
  (same semantic as rvabrep-direct: one work-item = one doc).
- ``SingleDocTriggerStrategy`` → ``ClientTrigger`` (no change).

### 4. Downstream code

- **S2 (mapping)**, **S3 (metadata)**, **S4 (assembly)**: read
  ``RVABREPDocument`` fields exclusively, NOT trigger fields —
  with one exception (S3 CIF self-healing).
- **S3 CIF self-healing**: today reads ``trigger.cif`` to
  short-circuit when the CSV has a blank CIF. The new code reads
  CIF from whichever trigger surfaces it:
  - ``ClientTrigger.cif`` (existing).
  - ``RvabrepRowTrigger.row[col_cif]``.
  - ``LocalScanTrigger.row[col_cif]``.

  A helper ``_trigger_cif(trigger) -> str | None`` centralizes
  this lookup so the resolver doesn't grow a match statement.
- **``_build_record``** in the orchestrator (which builds a
  ``MigrationRecord`` for tracking) calls
  ``trigger.audit_row()`` to fill ``trigger_shortname /
  trigger_cif / trigger_system_id``. Each subtype produces
  best-effort values from whatever it carries; rows that don't
  have all three leave the missing field None.

### 5. migration_log schema

**No schema change**. The existing columns
(``trigger_shortname``, ``trigger_cif``, ``trigger_system_id``)
stay as nullable text — same as today, just populated through the
``audit_row()`` accessor. The canonical per-doc identity remains
``rvabrep_txn_num`` (unchanged). The audit trail keeps the same
shape; only the source of those three columns shifts from "always
the literal trigger fields" to "best-effort projection of
whatever the trigger carries".

## Out of scope

- Renaming or restructuring the migration_log SQLite tables.
- Adding new CLI flags (e.g. ``single-doc --txn-num``). Future
  spec — single-doc stays as ``ClientTrigger`` for now.
- Changing csv-trigger semantics. The CSV-row → client → N docs
  model is intentional and unchanged.
- Removing the ``find_documents_batch`` IN-list batching. It still
  matters for csv-trigger and single-doc.
- Refactoring S2/S3/S4 to be trigger-agnostic. They already mostly
  are; only S3's CIF self-healing reads from the trigger and that
  one path gets a small abstraction.
- as400-trigger end-to-end staging verification — we don't have an
  AS400 reachable; unit tests cover the strategy shape change.

## Acceptance criteria

- Existing csv-trigger tests pass unchanged (``TriggerRecord ==
  ClientTrigger`` alias preserved).
- New unit test: ``RvabrepRowTrigger`` flows through S1 without
  hitting ``IDataSource`` (assertion via a mock that fails the
  test if a query is made).
- New unit test: ``LocalScanTrigger`` flows through S1 producing
  exactly one ``RVABREPDocument`` per trigger, even when the
  underlying client has 50+ docs.
- Live re-verify of §E.4 against staging:
  - Same pool of 100 files in ``sample/local-scan-pool``.
  - Pre-046 we saw 1860 docs uploaded (over-broad expansion).
  - Post-046 must upload **exactly 100 docs** (one per file).
- ``migration_log`` rows from a rvabrep-direct run still have
  ``trigger_shortname / trigger_cif / trigger_system_id``
  populated (best-effort from the row).
- ``CHANGELOG.md [0.49.0]`` entry.
- mypy + ruff clean. Full unit + integration suite green.

## Notes on test strategy

The polymorphic dispatch needs three test surfaces:

1. **Per-subtype unit tests** at the ``IndexingService`` level —
   verify the right code path fires for each subtype. The
   ``RvabrepRowTrigger`` and ``LocalScanTrigger`` cases pass a
   ``MagicMock`` IDataSource that raises if ``get_*`` is called.
2. **End-to-end staged-pipeline tests** with each strategy
   plugged in. The existing test fixtures already cover the csv
   path; we add two new fixtures for rvabrep-direct (one row
   selected → exactly that doc uploaded) and local-scan (one file
   in pool → exactly that doc uploaded).
3. **Live re-run of §E.4** against staging Alfresco as the
   integration acceptance gate.

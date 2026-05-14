# 048 — Pluggable RVABREP source (CSV ↔ AS400)

## Why

The user corrected a conflation baked into the trigger model: the
``rvabrep`` pipeline and the ``as400`` pipeline are **the same
pipeline**. The only thing that differs is where the RVABREP table
lives:

- **csv** — a CSV file simulating the RVABREP table (testing,
  staging dry-runs, small banks that export RVABREP to a file).
- **as400** — the live RVABREP table on DB2/AS400, reached by a
  ``SELECT`` that returns an RVABREP-shaped result set. The
  operator's SQL may carry JOINs / filters, but the **output
  columns are RVABREP-shaped** — same contract either way.

The current architecture (pre-048) gets this wrong in two places:

1. ``IndexingSourceConfig`` (``schema.py:173``) hard-wires the
   RVABREP source to a CSV: ``csv_path: FilePath`` is the only
   option. ``wiring.py:78`` always builds
   ``TabularDataSource(config.indexing.csv_path)``. There is no
   way to point S0 (rvabrep-direct) or S1 (indexing) at AS400.
2. ``As400TriggerConfig`` smuggled the AS400 path in as a SEPARATE
   ``trigger.kind: as400`` carrying an arbitrary ``query: str``,
   handled by a SEPARATE ``As400TriggerStrategy``. That's a
   strategy-vs-source conflation: "where the data lives" got
   modeled as "how triggers are discovered".

``DirectRvabrepTriggerStrategy`` already accepts any
``IDataSource`` — it never needed a CSV specifically. And
``As400DataSource`` already supports a ``query`` mode that wraps
the SQL as ``(query) AS T`` and exposes the full ``IDataSource``
contract (``get_all`` / ``get_by_fields`` / ``get_by_fields_in``).
The pieces to compose this cleanly already exist; 048 wires them
together.

## What

### 1. RVABREP source becomes a discriminated union

A new ``RvabrepSourceUnion`` discriminated on ``kind``:

```python
class CsvRvabrepSource(BaseModel):
    kind: Literal["csv"]
    csv_path: FilePath

class As400RvabrepSource(BaseModel):
    kind: Literal["as400"]
    connection: As400ConnectionConfig
    query: str   # SELECT returning RVABREP-shaped columns; JOINs/filters OK
```

``IndexingSourceConfig`` is renamed ``IndexingConfig`` and its
``csv_path`` field is replaced by ``source: RvabrepSourceUnion``:

```yaml
indexing:
  source:
    kind: csv
    csv_path: sample/rvabrep-50k.csv
  columns: {...}
  batch_size: 50
```

```yaml
indexing:
  source:
    kind: as400
    connection: {host, port, database, driver}
    query: "SELECT ... FROM RVILIB.RVABREP r WHERE r.ABAACD = '3'"
  columns: {...}
  batch_size: 50
```

The ``columns`` block keeps working for both — for the AS400
variant the operator aliases their SELECT output to the RVABREP
physical column names (or overrides ``columns`` to match their
aliases).

### 2. Wiring builds the source once, feeds S0 + S1

``wiring.py`` gains ``_build_rvabrep_source(indexing_cfg, secrets)
-> IDataSource``:

- ``CsvRvabrepSource`` → ``TabularDataSource(csv_path)``.
- ``As400RvabrepSource`` → ``As400DataSource(connection..., query=...)``
  — credentials come from ``secrets`` (``AS400_USERNAME`` /
  ``AS400_PASSWORD`` env vars), same as the pre-048 ``as400``
  trigger path.

The resulting ``IDataSource`` is the single ``rvabrep_src`` passed
to BOTH:
- ``IndexingService`` (S1 — doc lookup for csv-trigger + single-doc).
- ``DirectRvabrepTriggerStrategy`` (S0 — trigger discovery for
  rvabrep-direct).

Bonus: the csv-trigger and local-scan pipelines also gain the
AS400 RVABREP source for free — a CSV trigger list can now drive
S1 lookups against the live AS400 table.

### 3. ``trigger.kind: as400`` is removed

- ``As400TriggerConfig`` is deleted from ``TriggerConfigUnion``.
- ``As400TriggerStrategy`` (``services/triggers/as400.py``) is
  deleted — it was redundant. The "operator SQL with JOINs/filters"
  use case is fully covered by ``As400RvabrepSource.query``:
  ``DirectRvabrepTriggerStrategy`` over an ``As400DataSource``
  built from that query does exactly the same job, and now S1
  enrichment runs against the same source instead of re-querying
  a CSV.
- To run "the rvabrep pipeline against AS400" post-048:
  ``trigger.kind: rvabrep`` + ``indexing.source.kind: as400``.

After 048 the trigger kinds are: ``csv``, ``rvabrep``,
``local_scan``, ``single_doc``. Four, not five.

### 4. NIARVILOG is untouched

``As400NiarvilogStore`` (spec 034) is the AS400-level distributed
**idempotency tracking store** — a completely separate concern from
the RVABREP data source. 048 does not touch it. ``As400ConnectionConfig``
stays a shared config type (used by both ``As400RvabrepSource`` and
the NIARVILOG sync config).

## Out of scope

- A config-format migration shim. The project is pre-production —
  every config lives in-repo (``sample/*.yaml`` + test fixtures).
  048 migrates them all in Phase 2; there are no field configs to
  preserve. Clean break, consistent with 040-047.
- Pushing ``RvabrepFilters`` (systems / document_types) down into
  the AS400 ``WHERE`` clause. The filters stay applied in Python
  by ``DirectRvabrepTriggerStrategy`` as today — the operator who
  wants server-side filtering bakes it into their ``query``.
- ``metadata.sources`` AS400 support — that path already exists
  (``wiring.py`` already builds ``As400DataSource`` for metadata
  source aliases). 048 only touches the RVABREP source.
- Connection pooling / retry tuning for the AS400 RVABREP source.
  ``As400DataSource`` already has its retry behavior; 048 reuses
  it unchanged.

## Acceptance criteria

- ``indexing.source.kind: csv`` builds a ``TabularDataSource`` and
  the rvabrep + csv-trigger pipelines behave byte-identically to
  pre-048 (same staging smoke output).
- ``indexing.source.kind: as400`` builds an ``As400DataSource`` in
  query mode; a unit/integration test confirms
  ``DirectRvabrepTriggerStrategy`` and ``IndexingService`` both
  receive that source.
- ``trigger.kind: as400`` is rejected by the config loader with a
  clear error pointing at ``indexing.source.kind: as400``.
- ``services/triggers/as400.py`` is deleted; no import of
  ``As400TriggerStrategy`` survives anywhere.
- All 6 ``sample/config-staging*.yaml`` configs migrated to
  ``indexing.source``.
- All test fixtures / inline YAML migrated; full unit + integration
  suite green.
- Live re-verify: a staging run with the migrated
  ``config-staging-rvabrep.yaml`` (``--total 5``) produces the same
  result as pre-048.
- ``CHANGELOG.md [0.51.0]`` entry.
- mypy + ruff clean.

## Notes on test strategy

The AS400 RVABREP source can't be exercised against a live AS400
in CI (Constitution VI — AS400 never mocked, but the ``pyodbc``
cursor IS faked at the driver level, mirroring ``As400DataSource``'s
existing test approach). Phase 2 adds:

- A wiring unit test asserting ``_build_rvabrep_source`` returns an
  ``As400DataSource`` for the ``as400`` variant and a
  ``TabularDataSource`` for ``csv``.
- A config-loader test asserting the ``RvabrepSourceUnion``
  discriminator works and ``trigger.kind: as400`` is rejected.
- The existing ``test_as400.py`` driver-level fake covers the
  ``As400DataSource`` query-mode contract — no new AS400 plumbing
  tests needed.

The live re-verify uses the CSV variant (the AS400 variant has no
reachable server); the CSV path is the regression gate.

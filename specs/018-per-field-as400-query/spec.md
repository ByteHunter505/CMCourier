# Spec — 018-per-field-as400-query

**Status**: Draft
**Owner**: bitBreaker
**Date**: 2026-05-10
**Predecessors**: 014 (AS400 adapter), 015 (AS400 metadata source)
**Successors**: TBD

---

## 1. Problem

015 enabled AS400 metadata sources end-to-end via `SELECT * FROM
<table>` prefetch. Production AS400 tables can be huge: customer
master files routinely exceed millions of rows. A blind `SELECT *`
either:

1. Exhausts memory (the MetadataService caches the full dataset in
   a dict by `lookup_key_column` per Constitution I prefetch model).
2. Pulls columns the migration never uses, wasting bandwidth.
3. Pulls inactive / archived rows that shouldn't ship to CM.

Operators need a way to **scope the prefetch query** without changing
the metadata service or field-source wiring. The current escape
hatch — pre-staging the data into a CSV — defeats the point of
having native AS400 metadata sources at all.

REBIRTH §6.4 explicitly notes that "prefetch queries SHOULD allow
filtering and projection to scale to production data volumes."
014 and 015 deferred this; 018 closes the gap.

---

## 2. Goals

- **G1**: Operators can specify a custom `SELECT ...` for any
  `kind=as400` metadata source instead of (not in addition to) a
  table name.
- **G2**: The full `IDataSource` contract (`get_all`, `count`,
  `get_by_fields`, `get_by_fields_in`) keeps working when the source
  is query-backed, not table-backed. Subqueries with derived-table
  alias make this transparent to callers.
- **G3**: Existing YAML configs that use `table` keep working
  unchanged.
- **G4**: Doctor's metadata-prefetch check works for query-backed
  sources with no special-case branch.

## 3. Non-goals

- **NG1**: Per-field query overrides (orthogonal — would break the
  shared-prefetch model from 015). Rejected after explicit user
  decision: source-level only.
- **NG2**: Parameterized queries (`WHERE x = :param`). Out of scope
  for 018; if needed, future change.
- **NG3**: Changes to the AS400 *trigger* config (`As400TriggerConfig`
  already has a `query` field). Trigger and metadata paths stay
  separate.
- **NG4**: Query validation beyond non-empty string. The operator
  owns the SQL.

---

## 4. Requirements (RFC 2119)

### Schema

- **REQ-001**: `As400MetadataSourceConfig.table` MUST be optional
  (`str | None`, default `None`). Existing configs with `table` set
  MUST keep validating.
- **REQ-002**: `As400MetadataSourceConfig` MUST accept a new
  optional `query: str | None` field (default `None`, min_length 1
  when set).
- **REQ-003**: The model MUST enforce exactly-one of (`table`,
  `query`) via a `model_validator`. Both-set or neither-set MUST
  raise `ValidationError`.
- **REQ-004**: The discriminator (`kind="as400"`) MUST keep working
  unchanged.

### Adapter

- **REQ-005**: `As400DataSource.__init__` MUST accept either `table:
  str` or `query: str` (mutually exclusive), and MUST raise
  `ConfigurationError` if both or neither is supplied.
- **REQ-006**: Internally, the adapter MUST collapse the two
  constructor forms into a single `self._source_expr` string:
  `table` → `table` itself; `query` → `f"({query}) AS T"`. All
  generated SQL MUST reference `self._source_expr` (not
  `self._table`).
- **REQ-007**: `get_all`, `count`, `get_by_fields`,
  `get_by_fields_in` MUST work transparently with both forms. Query
  semantics: the query is treated as a derived table.
- **REQ-008**: Backwards-compat: callers that pass `table=...` keep
  working unchanged. No constructor signature break for existing
  call sites.

### Wiring

- **REQ-009**: `_build_metadata_sources` in `config/wiring.py` MUST
  pass `query=src_cfg.query` when the schema has a query set, and
  `table=src_cfg.table` otherwise. Both forms produce an
  `As400DataSource` registered under the same alias.

### Doctor

- **REQ-010**: Doctor's existing metadata-source prefetch check MUST
  work unchanged for query-backed sources. No new check needed.

### Tests

- **REQ-011**: ≥3 new adapter tests cover the query mode: `get_all`
  with a custom query, `count` with a custom query, and constructor
  validation (both/neither raises).
- **REQ-012**: ≥3 new schema tests cover: query-mode loads, exactly-
  one rule rejects both, exactly-one rule rejects neither.
- **REQ-013**: ≥1 new wiring integration test verifies that an
  as400 metadata source with `query` builds the pipeline correctly.

---

## 5. Acceptance scenarios

1. **Backwards-compat (table mode)**: A YAML with
   `metadata.sources[0] = {kind: as400, alias: customers,
   as400_connection: ..., table: CUSTOMERS}` validates and builds an
   `As400DataSource` whose `get_all()` issues `SELECT * FROM
   CUSTOMERS`.
2. **Query mode**: A YAML with `metadata.sources[0] = {kind: as400,
   alias: customers, as400_connection: ..., query: "SELECT CIF, NAME
   FROM CUSTOMERS WHERE ACTIVE = 'Y'"}` validates and builds an
   `As400DataSource` whose `get_all()` issues `SELECT * FROM (SELECT
   CIF, NAME FROM CUSTOMERS WHERE ACTIVE = 'Y') AS T`.
3. **Both set rejected**: A YAML with `table: X` and `query: SELECT
   ...` rejected by Pydantic at load time. Doctor / CLI surface this
   as a `ConfigurationError` (already wired in 012/013).
4. **Neither set rejected**: A YAML with neither `table` nor `query`
   rejected at load time with a clear "exactly one of `table` or
   `query` must be set" message.
5. **Per-source independence**: Multiple as400 sources can mix
   table and query forms — e.g., `customers` uses query,
   `products` uses table. They prefetch independently into the
   MetadataService source registry.
6. **MetadataService prefetch unchanged**: The prefetch loop calls
   `source.get_all()` polymorphically and indexes by
   `lookup_key_column`. No metadata-layer code needs to know
   whether the source is table- or query-backed.
7. **Doctor works**: `cmcourier doctor --config <yaml-with-as400-
   query>` runs the existing metadata-prefetch check. If the query
   succeeds, the check passes. If the query is malformed, the check
   fails with the AS400 error surfaced in the result details.
8. **count() works in query mode**: An adapter unit test verifies
   `count()` issues `SELECT COUNT(*) ... FROM (custom-query) AS T`
   and returns the row count, mocking pyodbc.
9. **`get_by_fields` works in query mode**: An adapter unit test
   verifies `get_by_fields({CIF: "123"})` issues `SELECT * FROM
   (custom-query) AS T WHERE CIF = ?` and binds the parameter.
10. **PII discipline preserved**: The adapter NEVER logs the
    `query` string body or its results. Constitution Principle
    VIII still holds — `sql_prefix` in error logs is truncated to
    80 chars (existing behavior).

---

## 6. Out of scope (explicit)

- Per-field-source query overrides.
- Parameterized queries with run-time substitution.
- Streaming prefetch (chunked load) — separate change if needed.
- Read-only enforcement (the query is whatever the operator passes;
  the AS400 user's permissions are the safety net).
- Trigger config changes (`As400TriggerConfig.query` already
  exists).

---

## 7. Definitions

- **Source expression**: an SQL fragment that can appear after
  `FROM` — either a bare identifier (`CUSTOMERS`) or a
  parenthesized derived table with alias (`(SELECT ...) AS T`).
- **Derived-table alias**: DB2/AS400 requires every parenthesized
  subquery to be aliased. The convention here is `T` (a single
  letter) to keep generated SQL minimal.

---

## 8. References

- 014 — AS400 adapter base
- 015 — AS400 metadata source (introduces `table` field)
- REBIRTH §3.1 (AS400 ODBC), §6.4 (metadata prefetch)
- Constitution Principles I (hexagonal), V (config validated at
  startup), VIII (PII discipline)

# Tasks — 018-per-field-as400-query

**Status**: Draft
**Spec**: `specs/018-per-field-as400-query/spec.md`
**Plan**: `specs/018-per-field-as400-query/plan.md`

---

## Phase 1 — As400DataSource source_expr refactor

- [ ] **1.1 (R)** Add adapter constructor tests to
  `tests/unit/adapters/sources/test_as400.py`:
  - `TestAs400DataSourceConstructor`: table-only OK, query-only OK,
    both-set raises, neither (both falsy) is allowed in raw mode
    (deferred initialization for callers that only use `query`/
    `query_stream`).
- [ ] **1.2 (R)** Add query-mode behavior tests to
  `tests/unit/adapters/sources/test_as400.py`:
  - `test_get_all_with_query_uses_subquery_alias`
  - `test_count_with_query`
  - `test_get_by_fields_with_query`
- [ ] **1.3 (G)** Edit `src/cmcourier/adapters/sources/as400.py`:
  - Constructor accepts `query: str | None = None` keyword arg.
  - Validate exactly-one OR neither (raw mode), reject both-set.
  - Compute `self._source_expr = f"({query}) AS T" if query else table`.
  - Replace `self._table` with `self._source_expr` in `get_all`,
    `count`, `get_by_fields`, `get_by_fields_in`.
  - Keep `self._table` attribute for backwards-compat / observability
    if needed (or drop it entirely).
- [ ] **1.4** Run adapter tests, iterate to green.

---

## Phase 2 — Schema + wiring

- [ ] **2.1 (R)** Add 3 schema tests to
  `tests/unit/config/test_schema.py`:
  - `test_as400_metadata_source_with_query_loads`
  - `test_as400_metadata_source_both_table_and_query_rejected`
  - `test_as400_metadata_source_neither_table_nor_query_rejected`
- [ ] **2.2 (G)** Edit `src/cmcourier/config/schema.py`:
  - `As400MetadataSourceConfig.table` → `str | None = Field(default=None, min_length=1)`.
  - Add `query: str | None = Field(default=None, min_length=1)`.
  - Add `@model_validator(mode="after")` enforcing exactly-one of
    `table` / `query`.
- [ ] **2.3 (R)** Add 1 wiring integration test to
  `tests/integration/config/test_wiring.py`:
  - `test_as400_metadata_source_with_query_builds`
- [ ] **2.4 (G)** Edit `src/cmcourier/config/wiring.py`:
  - Pass `query=src_cfg.query` to `As400DataSource` constructor in
    `_build_metadata_sources`.
  - Pass `table=src_cfg.table or ""` (existing behavior compatible).
- [ ] **2.5** Run full suite, iterate to green.

---

## Phase 3 — Verification

- [ ] **3.1** `ruff check src/ tests/` — clean.
- [ ] **3.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **3.3** `mypy src/cmcourier/` — clean.
- [ ] **3.4** `pytest --cov=src/cmcourier --cov-report=term` —
  coverage on `adapters/sources/as400.py` ≥ 85%, total ≥ 80%.
- [ ] **3.5** `pre-commit run --all-files` — clean.
- [ ] **3.6** Smoke: any existing config still loads;
  `cmcourier doctor --config <fixture-yaml>` still passes for the
  table mode.

---

## Phase 4 — Docs + commit + merge FF

- [ ] **4.1** Update `CHANGELOG.md`:
  - Remove "Per-field `as400_query` (follow-up to 015)" from the
    Planned section.
  - Add `[0.20.0] — 2026-05-10` entry: Added / Changed /
    Verification / Rationale.
- [ ] **4.2** Update `README.md` Status checklist: tick
  "Eighteenth change: per-source AS400 query override".
- [ ] **4.3** PII grep on new content. Synthetic only.
- [ ] **4.4** Stage. Commit:
  `feat(adapters,config): allow per-source AS400 query override`.
- [ ] **4.5** `git checkout main && git merge --ff-only feat/018-per-field-as400-query && git branch -d feat/018-per-field-as400-query`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..004 (schema) | 2.1, 2.2 |
| REQ-005..008 (adapter) | 1.1, 1.2, 1.3 |
| REQ-009 (wiring) | 2.3, 2.4 |
| REQ-010 (doctor) | 3.4 (existing tests still pass) |
| REQ-011..013 (tests) | 1.1, 1.2, 2.1, 2.3 |

---

## Estimated effort

- Phase 1: 50 min
- Phase 2: 40 min
- Phase 3: 15 min
- Phase 4: 15 min
- **Total**: ~2 h

---

## Notes for the implementor

- The phrase "per-field" in the original roadmap was a misnomer —
  the actual scope is **per-source** query override. Per-field would
  break the shared-prefetch model from 015. Decision recorded in
  spec §3 (NG1).
- The derived-table alias must be `AS T` (not just `T`) for DB2/AS400
  compatibility. Some SQL dialects allow alias without `AS`; DB2
  prefers explicit.
- `_table` attribute removal is OK if no tests reference it. Grep
  first.
- The trigger path (`As400TriggerStrategy`) does NOT use this
  adapter's `get_all`/`count` — it calls `query_stream` with its own
  SQL. So passing `table=""` to the constructor remains valid (raw
  mode).

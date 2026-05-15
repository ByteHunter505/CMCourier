# Tasks — 021-cli-tree-essentials

**Status**: Draft
**Spec**: `specs/021-cli-tree-essentials/spec.md`
**Plan**: `specs/021-cli-tree-essentials/plan.md`

---

## Phase 1 — Port + models + SQLite impl

- [ ] **1.1 (R)** Add 4 SQLite unit tests to
  `tests/unit/adapters/tracking/test_sqlite.py` (or equivalent).
- [ ] **1.2 (G)** Edit `src/cmcourier/domain/models.py`:
  - Add `BatchInfo`, `FailedRecord`, `BatchDetails` frozen
    dataclasses.
- [ ] **1.3 (G)** Edit `src/cmcourier/domain/ports.py`:
  - Add 3 abstract methods to `ITrackingStore`:
    `list_batches`, `get_batch_details`, `retry_failed`.
- [ ] **1.4 (G)** Edit `src/cmcourier/adapters/tracking/sqlite.py`:
  - Implement the 3 methods per plan §5.
  - Add `_pivot_status_counts` helper that always fills S0..S5.
- [ ] **1.5** Run phase-1 tests + full suite. Update any test
  stubs of `ITrackingStore` if present.

---

## Phase 2 — batch CLI

- [ ] **2.1 (G)** Create
  `src/cmcourier/cli/commands/_formatting.py` with
  `render_table` and `truncate` helpers.
- [ ] **2.2 (R)** Create `tests/integration/cli/test_batch.py`
  with `TestBatchList`, `TestBatchShow`,
  `TestBatchRetryFailed`. Each: help + happy path + error path.
- [ ] **2.3 (G)** Create `src/cmcourier/cli/commands/batch.py`:
  - `batch_group` + `batch_list_command` + `batch_show_command`
    + `batch_retry_failed_command` per plan §6.1.
  - Each command: load config, configure observability, open
    tracking store, call port method, render output.
- [ ] **2.4 (G)** Edit `src/cmcourier/cli/app.py` to register
  the batch group:
  - `from cmcourier.cli.commands.batch import batch_group`
  - `main.add_command(batch_group)`.
- [ ] **2.5** Run phase-2 tests. Iterate to green.

---

## Phase 3 — inspect + as400-query

- [ ] **3.1 (R)** Create `tests/integration/cli/test_inspect.py`
  with `TestInspectRvabrep` + `TestInspectMapping`.
- [ ] **3.2 (G)** Create `src/cmcourier/cli/commands/inspect.py`:
  - `inspect_group` + `inspect_rvabrep_command` +
    `inspect_mapping_command`.
- [ ] **3.3 (R)** Create
  `tests/integration/cli/test_as400_query.py` with help + happy
  (mocked pyodbc) + missing creds + SQL error.
- [ ] **3.4 (G)** Create
  `src/cmcourier/cli/commands/as400_query.py`:
  - `as400_query_command` top-level command.
  - Builds `As400DataSource` directly from config.cmis /
    indexing AS400 connection.
  - Calls `source.query(sql, [])` and renders the result table.
  - Refuses to run when AS400 creds absent (exit 2).
- [ ] **3.5 (R+G)** Create
  `tests/integration/cli/test_operator_flow.py` — 1 e2e:
  run pipeline → list → show → retry-failed.
- [ ] **3.6 (G)** Register `inspect_group` and
  `as400_query_command` in `cli/app.py`.
- [ ] **3.7** Run phase-3 tests. Iterate to green.

---

## Phase 4 — Verification + docs + commit + merge FF

- [ ] **4.1** `ruff check src/ tests/` — clean.
- [ ] **4.2** `ruff format --check src/ tests/` — clean (or apply).
- [ ] **4.3** `mypy src/cmcourier/` — clean.
- [ ] **4.4** `pytest --cov=src/cmcourier --cov-report=term` —
  ≥520 pass, coverage on `cli/commands/` ≥85%, total ≥80%.
- [ ] **4.5** `pre-commit run --all-files` — clean.
- [ ] **4.6** Smoke: `cmcourier --help` lists all 8+ commands;
  `cmcourier batch --help`, `cmcourier inspect --help`,
  `cmcourier as400-query --help` show their sub-commands /
  args.
- [ ] **4.7** Update `CHANGELOG.md`:
  - Remove "the spec CLI tree" from Planned.
  - Add `[0.23.0] — 2026-05-10` entry: Added / Changed /
    Verification / Rationale.
- [ ] **4.8** Update `README.md` Status checklist: tick
  "Twenty-first change: operator CLI essentials".
- [ ] **4.9** PII grep on new content.
- [ ] **4.10** Stage. Commit:
  `feat(cli): add operator essentials (batch/inspect/as400-query)`.
- [ ] **4.11** `git checkout main && git merge --ff-only feat/021-cli-tree-essentials && git branch -d feat/021-cli-tree-essentials`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..005 (port + models + SQLite) | 1.1..1.5 |
| REQ-006..008 (Click groups) | 2.3, 2.4, 3.2, 3.4, 3.6 |
| REQ-009..014 (output format) | 2.1, 2.3, 3.2, 3.4 |
| REQ-015..020 (errors) | 2.2, 2.3, 3.1..3.4 |
| REQ-021 (observability) | every command |
| REQ-022..024 (test counts) | covered across phases |
| REQ-025..027 (verification) | 4.1..4.6 |

---

## Estimated effort

- Phase 1: 70 min
- Phase 2: 60 min
- Phase 3: 70 min
- Phase 4: 30 min
- **Total**: ~3 h 50 min

---

## Notes for the implementor

- `_pivot_status_counts` should ALWAYS return a dict containing
  S0..S5 keys with `{DONE, FAILED, PENDING}` inner dicts (zeros
  for missing combos). Operators read these tables top-to-bottom;
  consistent shape matters.
- For `inspect rvabrep`, the easiest path is to build a
  `TabularDataSource` + `IndexingService` directly from
  `config.indexing`. No need for the full pipeline.
- For `inspect mapping`, build `TabularDataSource` +
  `MappingService` from `config.mapping`.
- For `as400-query`, the AS400 connection config lives in any
  AS400-using block (trigger.as400_connection or indexing if
  applicable). 021 reads from
  `config.trigger.as400_connection` when present, falling back
  to the first as400 metadata source. If none exist, exit 2
  with a "no AS400 connection configured" error.
- The `--config / -c` short flag is already idiomatic Click —
  use `click.option("--config", "-c", ...)`.
- Truncate error messages and cells to 80 chars in tables to
  keep terminal output readable.
- Test helpers can reuse the YAML builder + CMIS stub patterns
  from `tests/integration/cli/test_cli.py` and
  `test_pipeline_kinds.py`.
- `ITrackingStore` is implemented only by `SQLiteTrackingStore`
  in production — any test stubs of the port will need the 3
  new method stubs. Grep before editing.

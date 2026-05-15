# Tasks — 023-complete-cli-menus

**Status**: Draft
**Spec**: `specs/023-complete-cli-menus/spec.md`
**Plan**: `specs/023-complete-cli-menus/plan.md`

---

## Phase 1 — inspect trigger + descriptor parser

- [ ] **1.1 (R)** Create
  `tests/unit/cli/commands/test_source_descriptor.py` with 5
  tests (csv, single_doc no-cif, single_doc with cif,
  rvabrep rejected, unknown scheme rejected).
- [ ] **1.2 (G)** Create
  `src/cmcourier/cli/commands/_source_descriptor.py` with
  `_ParsedDescriptor` + `parse_source_descriptor` per plan §3.1.
- [ ] **1.3 (R)** Add `TestInspectTrigger` to
  `tests/integration/cli/test_inspect.py` (~6 tests).
- [ ] **1.4 (G)** Edit `src/cmcourier/cli/commands/inspect.py`:
  - Add `inspect_trigger_command` per plan §3.2.
  - When `--source` is None, build trigger strategy from
    `config.trigger`.
  - When `--source` is `csv:<path>`, build CsvTriggerStrategy.
  - When `--source` is `single_doc:<...>`, build
    SingleDocTriggerStrategy.
  - Other schemes → exit 2 with recommend-YAML message.
- [ ] **1.5** Run phase-1 tests. Iterate to green.

---

## Phase 2 — inspect mapping-stats

- [ ] **2.1 (R)** Add `TestInspectMappingStats` to
  `tests/integration/cli/test_inspect.py` (~3 tests).
- [ ] **2.2 (G)** Add `inspect_mapping_stats_command` to
  `inspect.py` per plan §3.3 + §4.2:
  - Build `TabularDataSource` + `MappingService` from
    `config.mapping`.
  - Iterate `get_all()`, aggregate, render summary +
    top-5 classes table.
- [ ] **2.3** Run phase-2 tests. Iterate to green.

---

## Phase 3 — batch export-report

- [ ] **3.1 (R)** Add `TestBatchExportReport` to
  `tests/integration/cli/test_batch.py` (~5 tests).
- [ ] **3.2 (G)** Add `batch_export_report_command` to
  `batch.py` per plan §3.4:
  - Open tracking store; call `get_batch_details(batch_id)`.
  - Unknown batch → exit 1 with stderr message.
  - CSV: writerow per stage (S0..S5) with batch metadata
    columns repeated.
  - JSON: full BatchDetails payload per plan §4.4.
  - `--output` → write to file + confirmation; else stream
    to stdout.
- [ ] **3.3** Run phase-3 tests. Iterate to green.

---

## Phase 4 — Verification + docs + commit + merge FF

- [ ] **4.1** `ruff check src/ tests/` clean.
- [ ] **4.2** `ruff format --check src/ tests/` clean.
- [ ] **4.3** `mypy src/cmcourier/` clean.
- [ ] **4.4** `pytest --cov` ≥560 pass; coverage on
  `cli/commands/inspect.py` + `cli/commands/batch.py` +
  `cli/commands/_source_descriptor.py` ≥85%.
- [ ] **4.5** `pre-commit run --all-files` clean.
- [ ] **4.6** Smoke:
  - `cmcourier inspect --help` lists `trigger`,
    `mapping-stats`, plus existing `rvabrep`, `mapping`.
  - `cmcourier batch --help` lists `export-report`.
- [ ] **4.7** Update `CHANGELOG.md`:
  - Remove the three commands from Planned.
  - Add `[0.25.0] — 2026-05-10` entry.
- [ ] **4.8** Update `README.md` Status checklist: tick
  "Twenty-third change: complete the spec menus".
- [ ] **4.9** PII grep on new content.
- [ ] **4.10** Stage. Commit:
  `feat(cli): inspect trigger + inspect mapping-stats + batch export-report`.
- [ ] **4.11** `git checkout main && git merge --ff-only feat/023-complete-cli-menus && git branch -d feat/023-complete-cli-menus`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..007 (inspect trigger) | 1.1, 1.2, 1.3, 1.4 |
| REQ-008..009 (mapping-stats) | 2.1, 2.2 |
| REQ-010..015 (export-report) | 3.1, 3.2 |
| REQ-016..018 (observability) | every command body |
| REQ-019..021 (test counts) | covered across phases |
| REQ-022..024 (verification) | 4.1..4.4 |

---

## Estimated effort

- Phase 1: 80 min
- Phase 2: 40 min
- Phase 3: 60 min
- Phase 4: 30 min
- **Total**: ~3 h 30 min

---

## Notes for the implementor

- For `inspect trigger` without `--source`, the cleanest path
  is to reuse `wiring._build_trigger_strategy(config, secrets,
  rvabrep_src, indexing_service)`. That helper is private
  but used by both `wiring.build_pipeline` and ourselves; OK
  since both live in the `cmcourier` package.
- For `--source csv:<path>` the strategy doesn't need any
  RVABREP / indexing collaborators. Wire `TabularDataSource`
  → `CsvTriggerStrategy` and call it a day.
- Strip the descriptor parser's path with `Path(value).expanduser()`
  so `~/migration/triggers.csv` works.
- The CSV writer should use `csv.writer(fh, lineterminator="\n")`
  to keep line endings predictable across platforms.
- For `export-report` JSON, use `indent=2` for human
  readability. Future consumers can `json.loads` regardless.
- The mapping-stats top-5 table should show columns
  `CLASS | COUNT` and tie-break alphabetically when counts
  match.

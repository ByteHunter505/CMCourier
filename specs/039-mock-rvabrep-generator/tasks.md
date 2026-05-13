# 039 — Tasks

## Phase 1: generator service + CLI subcommand

- [ ] 1.1 `RvabrepGenSpec` frozen dataclass in
      `src/cmcourier/services/mock/rvabrep_generator.py` —
      rows / seed / output / idrvi_pool / image_mix /
      date_from / date_to / clients / delete_rate / cif_rate.
- [ ] 1.2 `generate_rvabrep(spec, out_path) -> int` streaming
      writer using `csv.writer`. Returns rows written.
- [ ] 1.3 Helpers: `_pick_idrvi`, `_pick_image_type`,
      `_pick_creation_date`, `_pick_last_view_date`,
      `_pick_total_pages`, `_pick_file_name`, `_pick_image_path`,
      `_pick_txn_num`, `_pick_client`, `_pick_cif`.
- [ ] 1.4 Per-row `_validate_row` raising `ConfigurationError`
      with the row index. Runs before each write.
- [ ] 1.5 `cmcourier mock rvabrep` Click subcommand wired into
      the existing `mock` group with the spec's flags.
- [ ] 1.6 CLI loads the IDRVI source CSV via
      `TabularDataSource`, dedupes IDRVIs, takes top-N
      lexicographically, and builds the `RvabrepGenSpec`.
- [ ] 1.7 Unit tests (10 cases per Phase 1 plan): determinism,
      row count, txn_num uniqueness, image mix tolerance,
      IDRVI pool respect, PDF invariants, paged extensions,
      date range, last_view, invariant failure.
- [ ] 1.8 Full unit suite + mypy + ruff clean.
- [ ] 1.9 Commit
      `feat(services,cli): cmcourier mock rvabrep — synthetic RVABREP CSV generator (039 Phase 1)`.

## Phase 2: integration test + chained mock generate

- [ ] 2.1 `tests/integration/cli/test_mock_rvabrep.py` with the
      end-to-end scenario (CliRunner, 100 rows, IndexingService
      + MappingService consume the output).
- [ ] 2.2 Chained `mock generate` integration with small size
      bounds asserts 100 physical files materialize.
- [ ] 2.3 Full suite + mypy + ruff clean.
- [ ] 2.4 Commit
      `test(integration): rvabrep generator end-to-end + chained mock generate (039 Phase 2)`.

## Phase 3: docs + CHANGELOG 0.42.0 + version bump + FF

- [ ] 3.1 `docs/how-to/mock-rvabrep-generator.md` operator
      runbook — flags, examples (1k / 50k / 1M),
      chained `mock generate` flow, determinism, IDRVI
      source caveat.
- [ ] 3.2 `scripts/staging/README.md` — add a §X linking the
      new how-to.
- [ ] 3.3 `CHANGELOG.md [0.42.0]` — Added section only.
- [ ] 3.4 `README.md` feature row tick.
- [ ] 3.5 `pyproject.toml` version → `0.42.0`.
- [ ] 3.6 Smoke at 50k: command completes in < 5s, output
      parseable.
- [ ] 3.7 Full suite + mypy + ruff clean.
- [ ] 3.8 Commit
      `docs(039): mock-rvabrep how-to + CHANGELOG 0.42.0 + version bump (039 Phase 3)`.
- [ ] 3.9 FF merge to main.

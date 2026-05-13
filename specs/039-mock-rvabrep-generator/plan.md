# 039 — Plan

Three phases, ~4-5h total. RED→GREEN per phase, commit per phase,
FF on the last commit.

## Phase 1 — Generator service + CLI subcommand (~2.5h)

### Files

- `src/cmcourier/services/mock/rvabrep_generator.py` (new)
  - `RvabrepGenSpec` frozen dataclass — rows / seed / output /
    idrvi_pool / image_mix / date range / clients /
    delete_rate / cif_rate. All scalar; the IDRVI pool is a tuple
    of strings already drawn from the source CSV by the caller.
  - `generate_rvabrep(spec, out_path)` function — opens the output
    path for write, streams rows via `csv.writer` so memory stays
    bounded even for `rows=1_000_000`. Returns row count written.
  - Internal helpers: `_pick_idrvi`, `_pick_image_type`,
    `_pick_creation_date`, `_pick_last_view_date`,
    `_pick_total_pages`, `_pick_file_name`, `_pick_image_path`,
    `_pick_txn_num`, `_pick_client`, `_pick_cif`. Each takes the
    shared `random.Random` instance.
  - `_validate_row(row, spec, idx)` raises
    `ConfigurationError` with the row index when an invariant
    fails. Runs every row before write.
- `src/cmcourier/cli/commands/mock.py` (edit)
  - Add `rvabrep` subcommand to the existing `mock` group.
  - Click options match the spec's CLI surface.
  - The command builds an `RvabrepGenSpec` from flags, reads the
    `--idrvi-source` CSV (defaults to
    `docs/samples/csv/MapeoRVI_CM.csv`) via `TabularDataSource`,
    drops blanks + dedupes IDRVIs, takes the top `--idrvi-top`
    by lexicographic order (deterministic), and calls
    `generate_rvabrep`.
  - On success, prints a one-line summary
    `Wrote {rows} rows to {output} (image_mix={...}, idrvis={N}, seed={S}).`

### Tests

- `tests/unit/services/mock/test_rvabrep_generator.py` (new)
  - `test_deterministic_with_same_seed`: two runs same seed →
    same bytes. Different seed → different bytes.
  - `test_row_count_matches_spec`: spec.rows = N → output has N
    data rows + 1 header.
  - `test_txn_num_unique`: 5000-row run, all `txn_num` distinct.
  - `test_image_mix_within_tolerance`: 5000-row run, observed
    proportions within ±2% of configured mix.
  - `test_idrvi_pool_respected`: every output `index7` is in the
    given pool.
  - `test_pdf_rows_have_pdf_extension_and_one_page`: every
    `image_type=O` row has `file_name.endswith(".PDF")` and
    `total_pages == 1`.
  - `test_paged_rows_have_numeric_extension`: every `B` or `C`
    row has `file_name` ending in a numeric extension.
  - `test_creation_date_in_range`: every CYYMMDD is parseable
    and falls in `[date_from, date_to]`.
  - `test_last_view_zero_or_after_creation`: when `last_view_date
    != "0"`, it parses and is ≥ creation_date.
  - `test_invariant_failure_raises`: forcing a row to violate
    (via monkeypatch) raises `ConfigurationError` before write.

### Commit

```
feat(services,cli): cmcourier mock rvabrep — synthetic RVABREP CSV generator (039 Phase 1)
```

## Phase 2 — Integration test + smoke against existing mock generate (~1h)

### Files

- `tests/integration/cli/test_mock_rvabrep.py` (new)
  - End-to-end CliRunner test: `mock rvabrep --rows 100
    --output {tmp}/r.csv --seed 100 --idrvi-source
    tests/fixtures/services/modelo_documental.csv`.
  - Reads the CSV back through `TabularDataSource` +
    `IndexingService` and asserts 100 documents materialize as
    `RVABREPDocument` instances.
  - Cross-references against the consolidated mapping fixture:
    each `index7` joins against at least one row of the modelo
    documental.
  - Chains into `cmcourier mock generate --rvabrep-csv {tmp}/r.csv
    --output-root {tmp}/files` with small size bounds and asserts
    100 physical files materialize.

### Tests

- Run the full suite. Existing mock tests stay untouched.

### Commit

```
test(integration): rvabrep generator end-to-end + chained mock generate (039 Phase 2)
```

## Phase 3 — Docs + CHANGELOG 0.42.0 + version bump + FF (~30min)

### Files

- `docs/how-to/mock-rvabrep-generator.md` (new) — operator runbook:
  - When to use this command.
  - The flags, with examples for 1k / 50k / 1M scale runs.
  - How to chain into `mock generate`.
  - The implicit dependency on `--idrvi-source` and what happens
    when the source has fewer than `--idrvi-top` distinct values.
  - Determinism guarantee and how seeds interact with the
    materialized-files generator (different seeds for the two
    commands are independent — the file content is keyed on
    `txn_num` + page index, not the row order).
- `scripts/staging/README.md` — add a §X "Generating a synthetic
  RVABREP" pointing at the new how-to.
- `CHANGELOG.md` — `[0.42.0]` entry. Single Added section.
- `README.md` — tick the feature row.
- `pyproject.toml` version bump to `0.42.0`.

### Tests

- Full suite green.
- `mypy --strict src/cmcourier/{domain,services,orchestrators}` clean.
- `ruff check` + `ruff format --check` clean.
- Smoke at 50k: `cmcourier mock rvabrep --rows 50000 --output
  /tmp/r50k.csv --seed 50000` completes in < 5s and the output
  passes a quick CSV linter (column count, header match,
  per-row parseable).

### Commit

```
docs(039): mock-rvabrep how-to + CHANGELOG 0.42.0 + version bump (039 Phase 3)
```

### FF merge to main. Branch stays (operator deletes when ready).

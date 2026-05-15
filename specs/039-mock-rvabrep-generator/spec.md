# 039 — Mock RVABREP CSV generator

## Why

Staging dry-runs and stress tests need an RVABREP CSV at realistic
scale (tens of thousands of rows). The existing `cmcourier mock
generate` (031) materializes **on-disk files** from an RVABREP CSV
but does not generate the CSV itself — the operator has to bring
their own. Today the largest fixture in the repo is ~10 rows
(`tests/fixtures/pipeline/rvabrep.csv`), curated by hand for unit
tests, not representative of a real batch.

Without a generator the operator either:
- Crafts CSVs by hand (slow, error-prone, no determinism), or
- Snapshots data from the bank (not allowed for PII reasons, plus
  cross-environment pollution), or
- Writes one-off Python scripts that disappear after the test
  (no reproducibility, no shared distribution semantics).

039 closes that gap with a small additive CLI surface:
`cmcourier mock rvabrep` writes a CSV honoring the column shape
documented in `the spec`, with seed-deterministic distributions
that match observed bank patterns.

## What

### CLI

New subcommand under the existing `mock` group:

```
cmcourier mock rvabrep \
  --rows 50000 \
  --output sample/rvabrep-50k.csv \
  --seed 50000 \
  [--idrvi-source <csv_path>] \
  [--idrvi-top 20] \
  [--image-mix tiff:60,pdf:20,jpeg:20] \
  [--date-from 2024-01-01] [--date-to 2025-12-31] \
  [--clients 5000] \
  [--delete-rate 0.05] \
  [--cif-rate 0.95]
```

All flags have defaults; `--rows` and `--output` are the only
required positions (output as a positional is also acceptable).

### Output shape

Header (friendly names — matches `IndexingService.IndexingColumnsConfig`
defaults and what the existing `mock generate` subcommand reads):

```
shortname,system_id,txn_num,delete_code,index2,index3,index4,index5,index6,index7,image_type,image_path,file_name,creation_date,last_view_date,total_pages
```

### Per-column generation rules

| Column | Rule |
| --- | --- |
| `shortname` | One of `--clients` (default 5000) distinct identifiers, format `<NAME><NN>` where NAME is 6-10 uppercase ASCII letters from a small lexicon (`JUAN`, `MARIA`, `PEDRO`, `EMPRESA`, …) and NN is 2 digits. Uniform draw across clients — average ≈ `--rows / --clients` documents per client. |
| `system_id` | 70% `"1"`, 15% `"5"`, 10% `"2"`, 5% `"3"`. Matches the observed mix in `RVILIB_RVABREP.xlsx`. Configurable in a future change if needed. |
| `txn_num` | Globally unique. 7-character base32 (`A-Z` + `2-7`) deterministic from the row index + seed, prefixed with `T`. Format: `T<6 base32 chars>` → 32^6 = 1 073 741 824 distinct values (room for batches up to ~1G rows). |
| `delete_code` | `"D"` with probability `--delete-rate` (default 0.05), `""` otherwise. |
| `index2` (CIF) | `""` with probability `1 - --cif-rate` (default 0.95). Otherwise a 6-digit numeric. One CIF per client (each client has a stable CIF chosen at client-creation time, then reused for every document of that client). |
| `index3` / `index4` / `index5` / `index6` | Always `""` (matches every sample we have). |
| `index7` (ID RVI) | Drawn from a small set (`--idrvi-top`, default 20) sampled from `--idrvi-source` (default `docs/samples/csv/MapeoRVI_CM.csv`, IDRVI column). Distribution follows Zipf — most popular IDRVI captures ~30% of rows, second ~15%, etc. (Pareto 80/20 with α=1.07). |
| `image_type` | Drawn from `--image-mix`. Default `tiff:60,pdf:20,jpeg:20`. Maps to `B` / `O` / `C` respectively. |
| `image_path` | `PROD/<YYYY>/<MM>/<DD>` derived from the row's `creation_date`. |
| `file_name` | Prefix letter aligned with `image_type` (`D`/`M` for B/TIFF, `C` for JPEG, `0` for PDF). Body: 7-character random alphanumeric. Extension: `.001` for paged (TIFF/JPEG), `.PDF` for PDF. |
| `creation_date` | CYYMMDD format. Uniform draw in the range `[--date-from, --date-to]`. Default range 2024-01-01 to 2025-12-31. |
| `last_view_date` | `"0"` with probability 0.9. Otherwise CYYMMDD between creation_date and `--date-to`. |
| `total_pages` | `1` for PDF rows. Paged rows: 70% in `[1, 5]`, 25% in `[6, 50]`, 5% in `[51, 540]`. |

### Determinism

A single `random.Random(seed)` instance drives every choice. The
same `--seed` always produces byte-identical output (modulo OS
newline handling). This matches the existing `mock generate`
behavior and is required by Constitution §VII (Spec Before Code —
specs only get verified end-to-end if the generator is reproducible).

### Validation invariants

The generator verifies before writing:
- All `txn_num` values are unique.
- All `shortname` values appear in at least one row.
- All `index7` values are members of the `--idrvi-source` set.
- Image-type / file-name extension are consistent
  (`O` → `.PDF`, `B`/`C` → numeric extension).
- `total_pages == 1` for PDF rows.
- Date strings are valid CYYMMDD (parseable by
  `domain.models.parse_cymmdd`).

Any invariant failure raises a `ConfigurationError` with a row index
in `context`. Generator exits non-zero before writing partial CSV.

## Out of scope

- Generating physical files on disk — already covered by
  `cmcourier mock generate`. Operators chain the two:
  `mock rvabrep` produces the CSV, then `mock generate
  --rvabrep-csv <path>` materializes the files.
- Trigger CSV generation. Triggers can be derived from the RVABREP
  output if needed; deferred to a future spec.
- AS400 NIARVILOG seeding. The mock RVABREP is filesystem-only.
- Realistic OCR / content. Files materialized by `mock generate`
  remain blank-page fillers — out of scope per 031.
- The doctor cm-targets pre-flight against the generated IDRVI set.
  If the operator points the doctor at the staging Alfresco with
  20 IDRVIs but only one CMIS type registered, the doctor will FAIL
  for 19 of them. That is the operator's responsibility to configure
  (either register more types or override `--idrvi-top 1`).

## Acceptance criteria

- `cmcourier mock rvabrep --rows 50000 --output /tmp/r.csv --seed 50000`
  runs in < 5 seconds on a laptop and produces a 50000-row CSV.
- The generated CSV passes `cmcourier inspect rvabrep
  --config <stub.yaml>` for every row.
- Re-running with the same seed produces a byte-identical file
  (modulo `\r\n` on Windows).
- Re-running with a different seed produces a different file.
- The generated CSV can be fed to the existing `cmcourier mock
  generate --rvabrep-csv <path>` and 50000 physical files
  materialize without error.
- `parse_cymmdd` accepts every `creation_date` and
  `last_view_date != "0"` value in the output.
- Unit tests cover each generator function in isolation.
- One integration test runs the full CLI with `--rows 100` and
  asserts the CSV passes `MappingService` resolution end-to-end
  (joinable against `docs/samples/csv/MapeoRVI_CM.csv`).
- mypy --strict clean on the new service module.
- ruff clean.
- CHANGELOG `[0.42.0]` entry.

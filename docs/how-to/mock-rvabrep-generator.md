# How-to: Generate a synthetic RVABREP CSV (039)

> Status: `[0.42.0]` and later. Operator runbook for the
> `cmcourier mock rvabrep` subcommand.

The pipeline test surface needed something between the 10-row
hand-curated fixtures shipped with the repo and the bank's real
RVABREP exports (which are PII-laden and out of bounds for
external work). `cmcourier mock rvabrep` fills the gap: produces a
seed-deterministic CSV at any scale — 100, 50 000, 1 000 000 — that
the existing `cmcourier mock generate` (031) consumes directly to
materialize the on-disk file tree.

## TL;DR

```bash
# 1. Generate 50k rows in <5s
cmcourier mock rvabrep \
  --rows 50000 \
  --output sample/rvabrep-50k.csv \
  --seed 50000

# 2. Materialize 50k physical files from that CSV
cmcourier mock generate \
  --rvabrep-csv sample/rvabrep-50k.csv \
  --root sample/files \
  --pdf-min 100kb --pdf-max 2mb \
  --img-min 20kb --img-max 200kb \
  --seed 1
```

The CSV header uses **ABA codes** (`ABABCD`, `ABAANB`, `ABAHCD`, ...)
— the same column names `IndexingColumnsModel` defaults to. No
config override is needed at any downstream stage (mock generate,
the pipeline runners, `doctor`).

## §1 — What gets generated

Per the REBIRTH §3.2 column shape:

| ABA code | Friendly meaning | Generation rule |
| --- | --- | --- |
| `ABABCD` | shortname | Pool of `--clients` (default 5000) distinct identifiers from a small banking lexicon + 2-digit suffix |
| `ABAACD` | system_id | 70% `"1"` / 15% `"5"` / 10% `"2"` / 5% `"3"` |
| `ABAANB` | txn_num | `T` + 6-char base32 deterministic from row index — globally unique |
| `ABACST` | delete_code | `"D"` with probability `--delete-rate` (default 5%), `""` otherwise |
| `ABACCD` | index2 / CIF | One stable 6-digit CIF per client; present with probability `--cif-rate` (default 95%) |
| `ABADCD`..`ABAGCD` | index3..6 | Always blank (matches every observed sample) |
| `ABAHCD` | index7 / IDRVI | Zipf-weighted draw from the top `--idrvi-top` (default 20) IDRVIs in `--idrvi-source` (default `docs/samples/csv/MapeoRVI_CM.csv`). Most popular IDRVI gets ~30% of the volume, second ~15%, etc. |
| `ABABST` | image_type | `--image-mix` (default `tiff:60,pdf:20,jpeg:20`) → `B` / `O` / `C` |
| `ABAICD` | image_path | `PROD/YYYY/MM/DD` derived from creation_date |
| `ABAJCD` | file_name | Prefix letter aligned with image_type (`D`/`M` for B, `C` for C, `0` for O) + 7-char random body + correct extension (`.001` for paged, `.PDF` for native) |
| `ABAADT` | creation_date | Uniform CYYMMDD in `[--date-from, --date-to]` (default 2024-01-01..2025-12-31) |
| `ABABDT` | last_view_date | `"0"` with probability 0.9, else CYYMMDD ≥ creation_date |
| `ABABUN` | total_pages | `1` for PDF rows; for paged: 70% in `[1,5]`, 25% in `[6,50]`, 5% in `[51,540]` |

Every row is validated before write (correct extension, integer
`ABABUN`, parseable CYYMMDD, etc.). Any invariant failure raises
`ConfigurationError` with the row index — the generator never
writes a partial CSV.

## §2 — Reproducibility

A single `--seed` drives every choice. Same seed = byte-identical
output, every time, on every host. This holds across:

- Multiple invocations on the same machine.
- Different hosts (modulo line-ending policy — the writer uses
  `csv.writer` defaults, so `\r\n` on Windows and `\n` on POSIX).
- Different Python minor versions (3.11, 3.12).

The seed for `mock rvabrep` is **independent** of the seed for
`mock generate` — the former determines the row distribution, the
latter determines the file content within those rows.

## §3 — Scales

| Scale | Wall clock | Output size |
| --- | --- | --- |
| 100 rows | < 0.5 s | ~12 KB |
| 1 000 rows | < 0.5 s | ~120 KB |
| 50 000 rows | ~3 s | ~6 MB |
| 1 000 000 rows | ~50 s | ~120 MB |

Memory stays bounded — the generator streams row-by-row via
`csv.writer`, never accumulating the full dataset.

## §4 — Chaining into `mock generate`

```bash
cmcourier mock rvabrep --rows 50000 --output /tmp/r.csv --seed 50000
cmcourier mock generate --rvabrep-csv /tmp/r.csv --root /tmp/files \
  --pdf-min 100kb --pdf-max 2mb \
  --img-min 20kb --img-max 200kb \
  --seed 1
```

The two seeds are **independent**:
- `--seed 50000` (rvabrep): controls which row gets which shortname,
  txn_num, file_name, etc.
- `--seed 1` (generate): controls the bytes inside each file
  (blank-page filler PDFs/TIFFs/JPEGs sized between the configured
  bounds).

Re-generating with the same RVABREP seed but a different file-content
seed gives you the **same** CSV with **different** file bytes —
useful for stressing the assembler with new content while keeping
the trigger / RVABREP shape stable.

## §5 — `--idrvi-source` caveats

The default source is `docs/samples/csv/MapeoRVI_CM.csv` — the
bank's mapping table shipped with the repo, 282 distinct IDRVIs.
The generator picks the top `--idrvi-top` by **lexicographic
order** (deterministic and source-agnostic). Defaults to `20`.

If you point `--idrvi-source` at a CSV with fewer than
`--idrvi-top` distinct IDRVIs, the generator raises a
`ConfigurationError` — there is no silent fallback. Either drop
`--idrvi-top` or expand the source.

### Aligning with the CMIS target

If you intend to run the generated batch end-to-end against a CMIS
target (staging Alfresco, the bank's CM staging), be aware that
**every distinct IDRVI in the output will demand a matching CMIS
type registration**. With `--idrvi-top 20` you have 20 distinct
IDRVIs in the batch — the pre-flight `doctor --check cm-targets`
will issue 20 `getTypeDefinition` requests. Make sure the target
has those types registered, or:
- Drop to `--idrvi-top 1` for a single-type smoke run.
- Override `CMISType` for every IDRVI in your MapeoRVI_CM to
  point at one staging type (e.g. `D:cmcourier:bacDoc`) so the
  20 IDRVIs share one CMIS type.

## §6 — When NOT to use this

- **Production runs.** The generator emits synthetic data with
  meaningless CIFs and shortnames. Real migration uses the bank's
  actual RVABREP export.
- **Reproducing a bug from real data.** If a specific real row is
  triggering a failure, you want the actual row, not a synthetic
  approximation.
- **Per-document-type validation.** The Zipf distribution biases
  toward a few IDRVIs. If you need to test a long-tail type, pin
  `--idrvi-top 1` with a curated `--idrvi-source` containing only
  that type.

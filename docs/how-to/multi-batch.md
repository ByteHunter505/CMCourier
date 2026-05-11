# How to: run multiple batches in flight (`processing.batches_in_flight`)

> Available since change **028** (2026-05-11). Lets a long
> migration chunk its triggers into batches and run the prep
> (S0-S4) of one batch overlapped with the upload (S5) of
> another.

---

## TL;DR

```yaml
# config.yaml
processing:
  batches_in_flight: 2     # default — one preparing, one uploading
batch_size: 1000           # size of each chunk
```

```bash
# Use the YAML default (N=2)
cmcourier csv-trigger-pipeline run --config prod.yaml

# Override at the CLI to force single-batch (legacy behavior)
cmcourier csv-trigger-pipeline run --config prod.yaml --batches-in-flight 1

# --resume always forces N=1 — resuming a specific batch is a single-shot.
```

---

## What changed

Before 028, `pipeline.run()` was a one-shot:

```
[acquire 20 000 triggers] → S0 → S1 → S2 → S3 → S4 → S5
                                                       ↑
                                                idle while
                                                S0-S4 ran
```

After 028 with `batches_in_flight=2` and `batch_size=1000`:

```
                  ┌────────────────┐
trigger source ──►│   chunker      │  20 chunks of 1 000
                  └────────────────┘
                          │
                          ▼
                  ┌────────────────┐
                  │ prep thread    │  S0–S4 of chunk N+1
                  └────────────────┘
                          │
                          ▼   (queue, capacity 1)
                  ┌────────────────┐
                  │ upload thread  │  S5 of chunk N
                  └────────────────┘
```

While the network is busy uploading chunk N, the CPU + the
trigger source + RVABREP + the metadata services prepare chunk
N+1. Each chunk gets its own `batch_id` in the tracking DB and
its own `batch_summary` log event.

## What's *not* in 028

- **N > 2** — only `1` and `2` are accepted. `3..5` (the
  original aspirational range in POST-MVP §7) needs a deeper
  refactor of the shared S5 worker pool semantics; it's
  documented as a future change.
- **TUI multi-batch view** — the TUI currently shows one
  batch at a time. When the TUI is on (`--tui`),
  `batches_in_flight` is silently forced to 1 so the operator
  sees coherent live data. Headless runs (`--no-tui` or a
  non-TTY shell like cron) use the configured value.
- **Per-batch bandwidth quota** — that's POST-MVP §8.

---

## Operator output

When `len(chunks) > 1`, the CLI prints one line per chunk plus
a TOTALS line:

```
chunk 1/20  batch_id=AAA  total_docs=1000 s5_done=998  s5_failed=2  elapsed_seconds=42.10
chunk 2/20  batch_id=BBB  total_docs=1000 s5_done=1000 s5_failed=0  elapsed_seconds=39.87
...
TOTALS batch_count=20 total_docs=20000 s5_done=19987 s5_failed=13 failed_chunks=0 elapsed_seconds=812.43
```

When only one chunk runs (e.g. small source, or `N=1`), the
output is the legacy single-line summary — byte-identical to
pre-028 behavior.

## Failure isolation

If a chunk crashes during prep or upload, the orchestrator
catches the exception, logs it at ERROR, adds the chunk to
`failed_chunks`, and continues with the remaining chunks.
Exit code:

- `0` — every chunk succeeded.
- `1` — at least one chunk had `s5_failed > 0` OR ended up in
  `failed_chunks`.

## Memory budgeting

Each in-flight prepared chunk holds staged file paths +
metadata in memory and PDFs on disk in
`assembly.temp_dir/<batch_id>/`. With `batch_size=1000` and
~10 MB average per staged file:

- N=1: ~10 GB peak disk, single-digit MB RAM.
- N=2: ~20 GB peak disk while two chunks are in flight,
  roughly 2× metadata RAM.

The peak is brief — the upload thread consumes prepared
chunks as fast as it can.

## Cross-references

- POST-MVP roadmap §7: `docs/roadmap/POST-MVP.md`.
- Spec: `specs/028-multi-batch-orchestrator/`.
- Sister change 025 (S5 worker pool + AIMD) — the shared
  resource that all chunks compete for.

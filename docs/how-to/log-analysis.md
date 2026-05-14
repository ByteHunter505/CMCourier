# How to: analyze a batch's logs offline (`cmcourier analyze`)

> Available since change **027** (2026-05-11). Reads the five
> observability tiers (REBIRTH §17.4) and produces a
> per-batch report, pairwise compare, or trend series.

---

## TL;DR

```bash
# Full report for one batch
cmcourier analyze batch <batch_id> --config prod.yaml

# Side-by-side delta
cmcourier analyze compare <batch_a> <batch_b> --config prod.yaml

# Last 10 batches throughput + S5 p95 trend
cmcourier analyze trends --config prod.yaml --last 10

# JSON output instead of human-readable
cmcourier analyze batch <batch_id> --config prod.yaml --format json
```

If you don't want to point at a YAML, swap `--config` for
`--log-dir <path>` and the analyzer reads raw JSONL files
without consulting the pipeline config. Two consequences:

1. The classifier loses the `cmis_max_bandwidth_mbps` ceiling, so the
   system-metrics `network-bound` *reason* can't fire — but an upload
   bottleneck still surfaces as `upload-bound` via the stage breakdown.
2. The classifier loses `pool_capacity`, so the `worker-saturated`
   *reason* never fires. Neither loss affects the primary, stage-led
   verdict.

---

## What gets read

The analyzer scans the configured `log_dir` and pulls four file
families:

| File pattern | Tier | Filter |
|---|---|---|
| `metrics-{date}.jsonl` | 2 — pipeline | records where `batch_id` matches |
| `network-{date}.jsonl` | 3 — network | records inside the batch's **time window** (no `batch_id` on these records) |
| `system-{date}.jsonl` | 5 — system (026) | records inside the batch's **time window** (no `batch_id` on these records) |
| `slow-ops-{batch_id}.jsonl` | 4 — slow ops | file-per-batch, picked by name |

The `network-*` and `system-*` records carry **no `batch_id`** — only
a timestamp. The reader derives the batch window
`[ts − elapsed_s, ts]` from the `batch_summary` record (which *is*
batch-tagged) and keeps records whose timestamp (`ts` for network,
`ts_iso` for system) falls inside it. For a single-batch run this is
exact; for **overlapped (N=2)** runs the two batches' windows overlap
and a record in the overlap may land in either batch — a known
limitation (the per-stage breakdown below is batch-tagged and exact,
and it is the primary signal). When a batch has no `batch_summary`
record the window can't be derived and the network/system tiers come
back empty rather than guessing.

Cross-midnight runs are handled by the glob — both
`metrics-2026-05-10.jsonl` and `metrics-2026-05-11.jsonl`
are scanned if the batch straddled them.

Malformed JSONL lines are logged WARNING and skipped; the
report still produces.

---

## Bottleneck classifier

The classifier answers two questions: *which stage ate the time*, and
*is the bottleneck inside the program (ours to optimise) or outside it
(the CMIS server + network — we can only push more concurrency)*.

### The per-stage breakdown is the PRIMARY signal

The `batch_summary` record carries a per-stage timing breakdown
(`sum_ms` = total time across every doc in that stage). It is
batch-tagged, always present, and the most direct bottleneck signal —
so the classifier leads with it. When one stage holds **≥ 45%** of
total stage time, that stage **is** the bottleneck:

| Dominant stage | Class | Locus |
|---|---|---|
| `S5` (upload) | `upload-bound` | **OUTSIDE** the program — the CMIS server + network. The client can only push more concurrency. |
| `S4` (assembly) | `assembly-bound` | INSIDE — PDF/TIFF assembly CPU. Ours. |
| `S3` (metadata) | `metadata-bound` | INSIDE — metadata resolution. |
| `S2` (mapping) | `mapping-bound` | INSIDE. |
| `S1` (indexing) | `indexing-bound` | INSIDE. |
| `S0` (trigger) | `trigger-bound` | INSIDE. |

`confidence` is the dominant stage's share of total stage time, and
the `reasons` line names the stage, its share, its p50/p95, and
whether it is **INSIDE** or **OUTSIDE** the program — so the operator
gets the answer to their question, not just a label.

### System metrics REFINE, they don't gate

When system samples are present, these signals are appended as
**corroborating reasons** to the stage verdict — they no longer gate
it:

| Signal | Rule |
|---|---|
| `cpu-bound` | `process_cpu_pct > 80%` in **≥50%** of samples |
| `memory-bound` | `ram_used / ram_total > 0.85` in **≥50%** of samples |
| `disk-bound` | `disk_read + disk_write > 100 Mbps` **and** `cpu_pct < 50%` in **≥50%** of samples |
| `network-bound` | `(net_in + net_out) > 80% × cmis.max_bandwidth_mbps` in **≥50%** of samples |
| `worker-saturated` | `active_workers == pool_capacity` in **≥80%** of samples — a **symptom** of a slow downstream, not a cause |

These become the *classification* **only when no stage dominates**.
In that fallback a real resource cause (cpu / mem / disk / network)
always outranks `worker-saturated` — saturation is a symptom, so it is
the verdict only when it is the sole signal that fired.

`under-utilized` is returned only when **no** stage dominates **and**
no system signal fires — a genuinely idle run.

### Reading confidence

For a stage-led verdict, `confidence` is the dominant stage's fraction
of total stage time — `upload-bound` at `0.93` means S5 ate 93% of the
per-doc time. For a system-led fallback verdict it is the fraction of
samples that voted for the winning class. Anything ≥ 0.75 is
high-signal; 0.45–0.74 is suggestive.

### Known limitations

- **Overlapped (N=2) runs** — network/system records are associated by
  time window, and the two batches' windows overlap. The stage
  breakdown stays exact (batch-tagged); the system/network *reasons*
  may be slightly cross-contaminated.
- **Small batches (< 60 s)** with the default 5 s sampler interval
  produce <12 system samples — the corroborating reasons can be noisy.
  Lower `observability.system_metrics.sample_interval_s` to 1.0 for
  higher resolution on short diagnostic runs.
- **Sampler disabled** (`system_metrics.enabled: false`) → no
  corroborating reasons, but the stage-led verdict is unaffected.
- **No `cmis.max_bandwidth_mbps`** configured → the system-metrics
  `network-bound` reason is skipped, but an upload bottleneck still
  surfaces as `upload-bound` via the stage breakdown.
- The analyzer reports **what** is saturated, not **why**. An
  `upload-bound` verdict means S5 dominated — it could be the CMIS
  server overloaded, your NIC at capacity, or WAN contention; that's
  for the operator to triage.

---

## Sample output (terminal)

```
BATCH B1
============================================================
  pipeline                 csv-trigger
  total_docs               10
  elapsed_s                12.34
  throughput               0.810 docs/s

STAGES
------------------------------------------------------------
  stage    count    p50_ms    p95_ms    p99_ms
  S5          10    100.00    500.00    800.00

NETWORK
------------------------------------------------------------
  kind            count    p50_ms    p95_ms    p99_ms          bytes
  cmis_upload         1    200.00    200.00    200.00           1024

SYSTEM
------------------------------------------------------------
  samples                  1
  cpu_pct_avg/max          30.0 / 30.0
  process_cpu_avg/max      25.0 / 25.0
  ram_pct_avg/max          25.0% / 25.0%
  disk_mbps_avg/max        8.0 / 8.0
  net_mbps_avg/max         60.0 / 60.0
  worker_saturation        0.0%

TOP SLOW OPS
------------------------------------------------------------
  cmis_upload          6000 ms  txn=TXN_001  worker=w1

Bottleneck: upload-bound (confidence 1.00)
  • S5 dominates — 100% of total stage time (p50 100 ms, p95 500 ms); bottleneck is OUTSIDE the program
```

---

## Operator playbook

**"Batch X took N minutes. Was it CPU-bound or network-bound?"**

```bash
cmcourier analyze batch X --config prod.yaml
```

Look at the `Bottleneck:` line at the bottom.

**"Tuning run yesterday: did doubling `cmis.workers` actually
help?"**

```bash
cmcourier analyze compare yesterday-batch today-batch \
  --config prod.yaml
```

Compare `throughput_delta`, `elapsed_delta`, and the per-stage
p95 deltas. If `S5 p95` dropped and throughput rose, the
change worked. If S5 p95 dropped but throughput stayed flat,
you may have hit a different bottleneck (read the new
batch's `Bottleneck:` verdict).

**"Are we drifting over time?"**

```bash
cmcourier analyze trends --last 20 --pipeline rvabrep \
  --config prod.yaml
```

Watch the throughput column and the S5 p95 column over time.

---

## JSON output

`--format json` emits a deterministic, machine-readable
document with the same data as the terminal report. Use it
for piping into other tools:

```bash
cmcourier analyze batch <id> --config prod.yaml --format json \
  | jq '.bottleneck'
```

Determinism guarantee: identical input JSONL → identical JSON
output (sorted keys, no embedded timestamps, no random IDs).

---

## CI / PR integration (033)

The analyzer's `--format json` + deterministic output makes it a
natural fit for a CI guardrail: every PR (or scheduled job) runs
a small validation batch, then checks the bottleneck verdict +
S5 p95 against a baseline. If a regression appears, the CI job
fails and a comment is posted on the PR.

### Minimum viable check

For a migration tool, `upload-bound` is the *expected* steady state —
S5 (the CMIS upload) dominating means the program is doing its job and
the bottleneck is OUTSIDE our control. The regression to catch is an
**INSIDE**-the-program stage suddenly dominating
(`assembly-bound`, `metadata-bound`, `mapping-bound`, …) — that means
*our* code got slow. So the CI gate is "assert the verdict stayed
outside the program":

```bash
# In CI — run a tiny migration (the --total flag from 033 caps it):
cmcourier csv-trigger-pipeline run \
    --config staging.yaml \
    --no-tui --skip-doctor \
    --total 10 --batches-in-flight 1

# Inspect the most recent batch's verdict:
VERDICT=$(cmcourier analyze trends --last 1 --config staging.yaml --format json \
          | jq -r '.[0].batch_id' \
          | xargs -I {} cmcourier analyze batch {} --config staging.yaml --format json \
          | jq -r '.bottleneck.classification')

# Fail the build if an INSIDE-the-program stage regressed:
case "$VERDICT" in
  "upload-bound"|"under-utilized"|"network-bound")
    echo "::notice::CI batch verdict: $VERDICT (bottleneck outside the program)"
    ;;
  *)
    echo "::error::CI batch verdict regressed to '$VERDICT' — an INSIDE-the-program stage now dominates"
    exit 1
    ;;
esac
```

### GitHub Actions

```yaml
- name: Run CMCourier validation batch
  env:
    CMIS_USERNAME: ${{ secrets.CMIS_USERNAME }}
    CMIS_PASSWORD: ${{ secrets.CMIS_PASSWORD }}
  run: |
    cmcourier csv-trigger-pipeline run \
      --config configs/staging.yaml \
      --no-tui --skip-doctor \
      --total 10 --batches-in-flight 1

- name: Analyze most recent batch
  run: |
    LAST_BATCH=$(cmcourier analyze trends --last 1 \
                  --config configs/staging.yaml --format json \
                  | jq -r '.[0].batch_id')
    cmcourier analyze batch "$LAST_BATCH" \
      --config configs/staging.yaml --format json > batch-report.json
    cat batch-report.json | jq .

- name: Upload report artifact
  uses: actions/upload-artifact@v4
  with:
    name: cmcourier-batch-report
    path: batch-report.json
```

### GitLab CI

```yaml
cmcourier-validation:
  stage: test
  script:
    - cmcourier csv-trigger-pipeline run
        --config configs/staging.yaml
        --no-tui --skip-doctor
        --total 10 --batches-in-flight 1
    - LAST_BATCH=$(cmcourier analyze trends --last 1
                    --config configs/staging.yaml --format json
                    | jq -r '.[0].batch_id')
    - cmcourier analyze batch "$LAST_BATCH"
        --config configs/staging.yaml --format json > batch-report.json
  artifacts:
    paths:
      - batch-report.json
    when: always
```

### Useful `jq` filters

```bash
# Throughput across the last 10 batches:
cmcourier analyze trends --last 10 --config c.yaml --format json \
  | jq '[.[].throughput_docs_per_s] | {min, max, avg: (add/length)}'

# All S5 p95 values that crossed 5000 ms:
cmcourier analyze trends --last 50 --config c.yaml --format json \
  | jq '[.[] | select(.s5_p95_ms > 5000)] | length'

# Verdict + confidence for a known batch:
cmcourier analyze batch "$ID" --config c.yaml --format json \
  | jq '.bottleneck | {classification, confidence}'

# Top-3 slow ops by duration:
cmcourier analyze batch "$ID" --config c.yaml --format json \
  | jq '.slow_ops | sort_by(-.duration_ms) | .[:3]'
```

### Exit-code contract (regression gate)

For CI usage, the analyzer's exit codes:

* `0` — report produced successfully (regardless of the
  classification).
* `2` — config / CLI error (bad path, missing batch, malformed
  flag).
* `3` — unhandled exception inside the analyzer.

**Classification is NOT in the exit code** — the analyzer
reports facts; the CI job decides what counts as a regression.
This keeps the analyzer composable and lets each project pick
its own thresholds. The `case` block in the minimum-viable
example above is the recommended pattern: parse the JSON
output yourself and exit non-zero on the classes you care
about.

### Limitations in CI

* **Real CMIS not available**: most CI runners can't reach
  the bank's CMIS server. Use the `single-doc` pipeline
  against a CMIS-emulator container, or run only the
  pre-S5 stages and skip S5 entirely (a future change can
  add `--skip-s5`).
* **Small `--total` masks load signals**: with `--total 10`, the AIMD
  controller never warms up and `active_workers` stays low — the
  `worker-saturated` / `cpu-bound` corroborating reasons almost never
  fire in CI, and that's expected. The stage-led verdict is still
  meaningful (a tiny batch will normally still be `upload-bound`). CI
  catches config / wiring regressions, not load issues.
* **Determinism is per-input**: identical JSONL produces
  identical JSON, but two CI runs with different timing
  produce different JSONL. Don't pin against `byte-identical
  reports` across runs — pin against specific fields.

---

## Cross-references

- POST-MVP roadmap entry: `docs/roadmap/POST-MVP.md` §3.
- Tier 5 contract: `docs/domain/CMCOURIER_REBIRTH.md` §17.4
  + `specs/026-system-metrics-tier5/`.
- This change's spec: `specs/027-log-analyzer/`.

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

1. The bottleneck classifier loses the `cmis_max_bandwidth_mbps`
   ceiling, so the `network-bound` rule can only fall back to
   the "upload p95 > 5 s" heuristic.
2. The classifier loses `pool_capacity`, so the
   `worker-saturated` rule never fires.

---

## What gets read

The analyzer scans the configured `log_dir` and pulls four file
families:

| File pattern | Tier | Filter |
|---|---|---|
| `metrics-{date}.jsonl` | 2 — pipeline | records where `batch_id` matches |
| `network-{date}.jsonl` | 3 — network | records where `batch_id` matches |
| `system-{date}.jsonl` | 5 — system (026) | records where `batch_id` matches |
| `slow-ops-{batch_id}.jsonl` | 4 — slow ops | file-per-batch, picked by name |

Cross-midnight runs are handled by the glob — both
`metrics-2026-05-10.jsonl` and `metrics-2026-05-11.jsonl`
are scanned if the batch straddled them.

Malformed JSONL lines are logged WARNING and skipped; the
report still produces.

---

## Bottleneck classifier

The classifier inspects the aggregated system samples and
network metrics and outputs one of six classes:

| Class | Rule |
|---|---|
| `worker-saturated` | `active_workers == pool_capacity` in **≥80%** of system samples |
| `cpu-bound` | `process_cpu_pct > 80%` in **≥50%** of samples |
| `memory-bound` | `ram_used / ram_total > 0.85` in **≥50%** of samples |
| `disk-bound` | `disk_read + disk_write > 100 Mbps` **and** `cpu_pct < 50%` in **≥50%** of samples |
| `network-bound` | `(net_in + net_out) > 80% × cmis.max_bandwidth_mbps` in **≥50%** of samples (with system metrics) **OR** `cmis_upload p95 > 5000 ms` (fallback when no system samples) |
| `under-utilized` | none of the above crossed its threshold — the run looks healthy and the bottleneck is unclear |

**Tie-break order (highest precedence first):**
`worker-saturated > cpu-bound > memory-bound > disk-bound >
network-bound > under-utilized`.

When multiple rules fire, the one with the highest sample-vote
confidence wins; on a tie, precedence breaks it.

### Reading confidence

The `confidence` field is the fraction of samples that voted
for the winning class. A `cpu-bound` verdict with confidence
`0.62` means 62% of the system samples showed
`process_cpu_pct > 80%`. Anything ≥ 0.75 is high-signal;
0.5–0.74 is suggestive; below 0.5 should never fire (it's the
threshold).

### Known limitations

- **Small batches (< 60 s)** with the default 5 s sampler
  interval produce <12 samples — the classifier can be noisy.
  Lower `observability.system_metrics.sample_interval_s` to
  1.0 if you specifically need higher resolution for short
  diagnostic runs.
- **Sampler disabled** (`system_metrics.enabled: false`)
  → only the network-bound fallback heuristic can fire; every
  other class falls back to `under-utilized`.
- **No `cmis.max_bandwidth_mbps`** configured → the
  system-metrics network rule is skipped; only the upload-p95
  fallback can fire.
- The analyzer reports **what** is saturated, not **why**.
  A `network-bound` verdict on a CMIS-heavy run could mean
  the CMIS server is overloaded, your NIC is at capacity,
  or there's WAN contention between you and CMIS — that's
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

Bottleneck: under-utilized (confidence 1.00)
  • no bottleneck class crossed its threshold
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

## Cross-references

- POST-MVP roadmap entry: `docs/roadmap/POST-MVP.md` §3.
- Tier 5 contract: `docs/domain/CMCOURIER_REBIRTH.md` §17.4
  + `specs/026-system-metrics-tier5/`.
- This change's spec: `specs/027-log-analyzer/`.

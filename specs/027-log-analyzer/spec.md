# 027 — Offline Log Analyzer (`cmcourier analyze`)

> Status: **Proposed** — 2026-05-11
> Author: bitBreaker
> Predecessor: 020 (tiers 1–4), 026 (tier 5 system metrics)
> POST-MVP roadmap reference: `docs/roadmap/POST-MVP.md §3`

---

## 1. Summary

Add the `cmcourier analyze` subcommand suite that consumes the
log tiers (1 app log, 2 pipeline metrics, 3 network metrics, 4
slow ops, 5 system metrics) and produces **bottleneck
attribution reports** for completed batches. Three subcommands:

- `analyze batch <batch_id>` — full report for one batch.
- `analyze compare <batch_a> <batch_b>` — side-by-side delta.
- `analyze trends --last N [--pipeline <name>]` — throughput
  + p95 trend across the last N batches.

Output formats: human-readable terminal (default) and JSON
(`--format json`). HTML reports are **out of scope** for this
change (documented as a future follow-up).

This is the change §3 of POST-MVP and the immediate beneficiary
of 026 (tier 5 system metrics). Without it, the JSONL files
exist but reading them is manual — operators have no first-class
way to answer "why was batch X slow?".

---

## 2. Motivation

- **Tier 5 data is mute without a reader**. 026 shipped the
  sampler; the data is on disk but unused.
- **AIMD target validation needs correlation**. 025's auto-tune
  defaults `target_p95_ms = 5000`. Validating that value means
  reading per-stage p95 + system metrics together — exactly
  what this change provides.
- **Operator workflow**: today, debugging a slow batch means
  reading three JSONL files by eye and joining them by
  `batch_id` mentally. The analyzer makes this one command.
- **Pre-dry-run polish**: before the first real migration,
  operators need a way to quantify "did this run improve over
  yesterday's?". `analyze compare` provides that.

---

## 3. Scope

### In scope

- New CLI group `cmcourier analyze` with three subcommands.
- New `cmcourier.services.analyze` module exposing:
  - `LogReader` — reads JSONL tiers for a given batch.
  - `BatchReport` (frozen dataclass) — unified report shape.
  - `classify_bottleneck()` — pure function applying the
    documented rules.
  - `format_terminal()` / `format_json()` — render functions.
  - `compare_batches()` / `compute_trends()` — pairwise +
    trend helpers.
- Bottleneck classifier with five classes
  (`cpu-bound`, `memory-bound`, `disk-bound`,
  `network-bound`, `worker-saturated`) + a fallback
  (`under-utilized`). Documented rules + thresholds in
  `docs/how-to/log-analysis.md`.
- Determinism: identical input JSONL → identical report
  (sort orders explicit, no wall-clock leakage in output).
- ≥18 unit tests + ≥3 integration tests against fixture
  JSONL files.
- Documentation: `docs/how-to/log-analysis.md` with classifier
  rules, sample output, and operator playbook.

### Out of scope

- HTML report rendering. The acceptance criteria in POST-MVP §3
  list HTML as optional; deferred to a follow-up.
- Live/streaming analysis. The reader processes finished
  batches only — it reads files once and exits.
- Multi-host log aggregation. Single-host log dir only.
- Bottleneck explanations beyond the rule labels (e.g.
  "your CMIS server is overloaded"). The classifier reports
  *what* is saturated, not *why*.
- Tier 1 (`app-{date}.log`) parsing beyond extracting
  `stage_complete` records as a fallback when tier 2 is
  unavailable. Free-text WARNING/ERROR lines are not parsed.

---

## 4. Requirements

### Log reader

- **REQ-001**: `LogReader` accepts a `log_dir: Path` and a
  `batch_id: str`. It scans `metrics-*.jsonl`,
  `network-*.jsonl`, `system-*.jsonl`, and
  `slow-ops-{batch_id}.jsonl` and returns the records that
  carry the given `batch_id` (or the file matches it for
  slow-ops).
- **REQ-002**: For batches that span multiple dates (cross-
  midnight), the reader picks up records across rotated files
  by glob and merges them ordered by their `ts` / `ts_iso`
  field.
- **REQ-003**: Malformed JSONL lines are logged at WARNING
  and skipped; the reader never raises on partial corruption.
  Tested.
- **REQ-004**: When the system-metrics file is absent
  (sampler disabled for that run), the reader yields no
  system samples and the report's `system_summary` is `None`.
  Tested.
- **REQ-005**: Network records are split by `kind`:
  - `cmis_upload` → upload latency series.
  - `cmis_get` / `cmis_post` → support call series.
  - `as400_query` → AS400 source latency series.

### BatchReport

- **REQ-006**: `BatchReport` is a frozen dataclass with these
  fields (every field MUST be JSON-serializable):
  - `batch_id: str`
  - `pipeline: str | None` (from `batch_summary` event)
  - `total_docs: int`
  - `elapsed_s: float`
  - `throughput_docs_per_s: float`
  - `stage_summary: dict[str, dict[str, float | int]]` —
    p50/p95/p99/count per stage from `batch_summary`.
  - `slow_ops: list[dict[str, Any]]` — top-N slow ops with
    kind, duration_ms, txn_num, worker.
  - `network_summary: NetworkSummary` — aggregated counts +
    p50/p95/p99 + bytes per kind.
  - `system_summary: SystemSummary | None` — aggregated
    cpu/ram/disk/net + worker-saturation %.
  - `bottleneck: BottleneckClassification` — class, confidence,
    contributing samples.

### Bottleneck classifier

- **REQ-007**: `classify_bottleneck(system_summary,
  network_summary, stage_summary, cmis_max_bandwidth_mbps,
  pool_capacity)` is **pure** (no IO, no clock, no globals).
- **REQ-008**: Rules (documented in
  `docs/how-to/log-analysis.md`):
  - `cpu-bound`: ≥50% of system samples have
    `process_cpu_pct > 80`.
  - `memory-bound`: ≥50% of system samples have
    `ram_used / ram_total > 0.85`.
  - `disk-bound`: ≥50% of system samples have
    `disk_read_mbps + disk_write_mbps > 100` AND
    `cpu_pct < 50`.
  - `network-bound`: ≥50% of system samples have
    `(net_in_mbps + net_out_mbps) / cmis_max_bandwidth_mbps
    > 0.8` (when `cmis_max_bandwidth_mbps > 0`); fallback
    to "cmis_upload p95 > 5000 ms" when no system samples or
    no ceiling configured.
  - `worker-saturated`: ≥80% of system samples have
    `active_workers == pool_capacity` (when pool_capacity > 0).
  - `under-utilized`: none of the above; the run looks
    healthy and the bottleneck is unclear (typical for small
    batches).
- **REQ-009**: When multiple classes hit, return the one with
  the highest confidence. Ties broken by class precedence:
  worker-saturated > cpu > memory > disk > network >
  under-utilized.
- **REQ-010**: When **no** system samples exist, the
  classifier can only use stage_summary + network_summary —
  return `under-utilized` unless the network heuristic
  fires.

### Output formats

- **REQ-011**: `format_terminal(report)` returns a multi-line
  string ready to print. Sections:
  - Header (batch_id, pipeline, total_docs, throughput, elapsed).
  - Per-stage table (stage, count, p50/p95/p99).
  - Network table (kind, count, p50/p95/p99, total bytes).
  - System table (when available — cpu/ram/disk/net avg+max,
    worker-saturation %).
  - Top-5 slowest ops.
  - Bottleneck verdict line.
- **REQ-012**: `format_json(report)` returns a JSON string —
  the whole dataclass tree, deterministic key ordering, 2-space
  indented.
- **REQ-013**: Both formatters MUST be deterministic given
  the same `BatchReport` instance. No `datetime.now()`, no
  random ordering.

### Compare

- **REQ-014**: `compare_batches(a, b)` returns a
  `CompareReport` with deltas: `throughput_delta_docs_per_s`,
  `elapsed_delta_s`, per-stage `p95_delta_ms`,
  `bottleneck_a`, `bottleneck_b`.
- **REQ-015**: `format_compare_terminal(report)` renders a
  side-by-side table.

### Trends

- **REQ-016**: `compute_trends(log_dir, *, last_n,
  pipeline_filter)` reads `metrics-*.jsonl` chronologically,
  filters by pipeline if given, returns up to `last_n` most
  recent `batch_summary` events as a list (newest first).
- **REQ-017**: `format_trends_terminal(trends)` renders a
  per-batch row with throughput + S5 p95 over time.

### CLI

- **REQ-018**: `cmcourier analyze batch <batch_id>` — accepts
  `--config <path>` to locate `log_dir` from the YAML (and
  `cmis.max_bandwidth_mbps` for the classifier), or
  `--log-dir <path>` to bypass the config and read raw.
  `--format text|json` (default `text`).
- **REQ-019**: `cmcourier analyze compare <a> <b>` —
  same `--config` / `--log-dir` flags. `--format text|json`.
- **REQ-020**: `cmcourier analyze trends [--last N]
  [--pipeline <name>]` — same flag set; default `--last 10`.
- **REQ-021**: Exit codes:
  - 0 — report produced.
  - 2 — config/CLI error (bad path, missing batch).
  - 3 — unhandled exception.

### Tests

- **REQ-022**: ≥18 unit tests covering:
  - `LogReader` happy path, missing file, corrupted line,
    cross-midnight merge, system samples absent (5).
  - `classify_bottleneck` for each class + tie-break + no-
    samples fallback (8).
  - `format_terminal` / `format_json` determinism (2).
  - `compare_batches` symmetric + per-stage delta correct (2).
  - `compute_trends` ordering + filter (1).
- **REQ-023**: ≥3 CLI integration tests covering each
  subcommand against synthetic fixture JSONL files.
- **REQ-024**: A "golden file" comparison test ensures the
  terminal output is byte-identical for a known fixture batch.

### Verification

- **REQ-025**: `pytest` MUST report ≥695 passing (672 +
  the new tests).
- **REQ-026**: `mypy src/cmcourier/` clean.
- **REQ-027**: `ruff check` + `ruff format --check` clean.
- **REQ-028**: `docs/how-to/log-analysis.md` exists with
  classifier rules + sample output + operator playbook.

---

## 5. Acceptance scenarios

1. **Happy path**: A batch ran end-to-end with all five log
   tiers enabled. `cmcourier analyze batch <id> --config
   prod.yaml` prints a full report with bottleneck verdict.
2. **No tier 5**: A YAML with `system_metrics.enabled: false`
   ran. `analyze batch` still works — the system section is
   omitted and the bottleneck verdict is either
   `under-utilized` or `network-bound` (heuristic from
   network metrics).
3. **Corrupted JSONL**: A truncated line in
   `network-{date}.jsonl` is logged WARNING and skipped.
   The report still produces.
4. **Unknown batch**: `analyze batch nonexistent-id` exits
   with code 2 and a clear "batch not found" message.
5. **Compare**: Two batches with different worker counts are
   compared. Throughput delta + per-stage p95 delta are
   shown and the bottleneck class is reported for both.
6. **Trends with filter**: `analyze trends --last 5
   --pipeline csv-trigger` reads the last 5 csv-trigger
   batches and prints the throughput series.
7. **JSON format**: `analyze batch <id> --format json` emits
   a machine-readable JSON document with the same
   information as the terminal output.
8. **Deterministic**: Running `analyze batch <id>` twice in a
   row against the same JSONL files produces byte-identical
   output (no embedded timestamps, no random ordering).

---

## 6. Risks

- **JSONL file growth**: long-running runs can produce
  100 k+ network records. The reader streams line-by-line
  (never loads the whole file into memory) and aggregates as
  it goes. Memory budget: a few MB per batch report.
- **Classifier false negatives**: small batches (<60 s) may
  not have enough system samples to classify confidently.
  Doc'd in the how-to as a known limitation.
- **Cross-midnight edge cases**: a batch that crosses
  midnight straddles two `metrics-*.jsonl` files. The reader
  globs both. Tested.
- **Pipeline overload during analysis**: the analyzer is a
  separate process from the pipeline — no contention.

---

## 7. Dependencies

- **Hard**: 020 (tiers 1–4), 026 (tier 5), CLI scaffold from
  012.
- **Soft**: none. Standalone read-only tooling.

---

## 8. Estimate

~6 hours across four phases (see `tasks.md`).

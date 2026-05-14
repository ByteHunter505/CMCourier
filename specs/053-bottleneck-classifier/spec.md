# 053 — Bottleneck classifier: stage-aware + time-window log association

## Why

`cmcourier analyze batch <id>` is supposed to tell the operator
*where the time went* and *whether the bottleneck is inside the
program or outside it*. On a real 95-doc staging run — where S5
(upload) was **26× the next stage** (S5 p50 635 ms vs S4 p50 24 ms)
— it reported:

> **Bottleneck: under-utilized (confidence 1.00)** — "no bottleneck
> class crossed its threshold"

Exactly wrong. Three concrete bugs, all in `services/analyze.py`:

1. **The classifier ignores `stage_summary`.** `classify_bottleneck`
   *receives* the per-stage breakdown but it is marked
   `# noqa: ARG001 — reserved for future heuristics` — unused. The
   single clearest bottleneck signal — "which stage dominates the
   per-doc time" — is sitting right there, batch-tagged and exact.
2. **Network & system records aren't associated with the batch.**
   `LogReader._read_filtered` filters them by `rec["batch_id"] ==
   batch_id`, but those records carry **no `batch_id`** (only a
   timestamp). So `network_summary` is empty and `system_summary` is
   `None` — the classifier is blind to its two non-stage tiers.
3. **Absolute thresholds, no relative reasoning.** Even with system
   data: `network-bound` detection is dead whenever
   `cmis_max_bandwidth_mbps == 0` (the default — no configured cap);
   `worker-saturated` (rank 0) *masks* `network-bound` (rank 4) even
   though saturation is a *symptom* of slow uploads, not a cause; and
   the fallback's `cmis_upload p95 > 5000 ms` absolute gate never
   fires for a run whose S5 dominates by 26× but whose p95 is "only"
   1139 ms.

## What

### 1. Make the stage breakdown the PRIMARY signal

Rewrite `classify_bottleneck` to lead with `stage_summary` — it is
always present (the `batch_summary` record is batch-tagged) and it is
the most direct bottleneck signal.

- Sum each stage's `sum_ms` (total time across all docs in that
  stage). The **dominant stage** is the one with the largest share.
- When the dominant stage's share of total stage time crosses a
  threshold (`_STAGE_DOMINANCE = 0.45`), classify by stage:
  - **S5** → `upload-bound` — the CMIS server + network. *Outside
    the program* — the client can only push more concurrency.
  - **S4** → `assembly-bound` — PDF assembly CPU. *Inside* — ours.
  - **S3** → `metadata-bound` — metadata resolution. *Inside.*
  - **S2** → `mapping-bound`; **S1** → `indexing-bound`;
    **S0** → `trigger-bound`. *Inside.*
- `confidence` = the dominant share. `reasons` names the stage, its
  share, its p50/p95, and whether it is inside or outside the
  program — so the operator gets the *answer to their question*, not
  just a label.

### 2. System metrics REFINE, they don't gate

When `system_summary` is present (after fix #3 below), the
cpu/mem/disk signals become **corroborating reasons** appended to the
stage verdict — e.g. `assembly-bound` + "confirmed: process_cpu >
80% in 70% of samples". `worker-saturated` is reported as a
**symptom reason** alongside the verdict (typically alongside
`upload-bound`), never *instead* of it. The `network-bound`
sample-fraction signal still contributes when a bandwidth cap is
configured, but its absence no longer hides an `upload-bound`
verdict — the stage breakdown carries that.

`under-utilized` is returned only when **no** stage dominates **and**
no system signal fires — a genuinely idle run.

### 3. Associate network/system records by time window

`LogReader.read_batch` already reads the batch-tagged
`metrics-*.jsonl` first. From the `batch_summary` it derives the
batch window — `[ts − elapsed_s, ts]` — and filters
`network-*.jsonl` (timestamp field `ts`) and `system-*.jsonl`
(timestamp field `ts_iso`) to that window instead of by the absent
`batch_id`. No emitter changes — the records already carry
timestamps.

## Out of scope

- Tagging network/system records with a real `batch_id` (contextvar
  plumbing through the S5 worker pool). Time-window association is
  exact for single-batch runs; for **overlapped (N=2)** runs the
  windows overlap and a network/system record in the overlap may be
  attributed to either batch — documented as a known limitation. The
  per-stage breakdown (batch-tagged, exact) is the primary signal and
  is unaffected.
- `analyze compare` / `analyze trends` heuristics — unchanged; they
  already use the stage data directly.
- New TUI surfacing — `analyze` is the CLI tool; the TUI already has
  its own per-stage view.

## Acceptance criteria

- `classify_bottleneck` on a stage breakdown where S5's `sum_ms`
  dominates returns `upload-bound` with a reason naming S5, its
  share, and "outside the program" — a test reproduces the 95-doc
  run shape and asserts it (the regression case).
- An S4-dominant breakdown returns `assembly-bound` ("inside the
  program"); a balanced breakdown with no dominant stage returns
  `under-utilized`.
- `worker-saturated` system data no longer overrides a stage verdict
  — it appears as a reason line, not the classification.
- `network-bound` is reported for an S5-dominant run **even when
  `cmis_max_bandwidth_mbps == 0`** (via the stage signal) — a test
  asserts the old "under-utilized" regression is gone.
- `LogReader.read_batch` populates `network_summary` /
  `system_summary` from records that have no `batch_id`, filtered to
  the batch's time window — a test with windowed fixtures asserts it.
- Full unit + integration suite green; mypy + ruff clean.
- `CHANGELOG.md [0.56.0]`; `pyproject.toml` 0.55.0 → 0.56.0.

## Notes on test strategy

`classify_bottleneck` is a pure function — the tests feed it stage /
network / system summaries and assert the classification + reasons,
including the **exact 95-doc run shape** as the named regression
test. `LogReader` time-window association is tested with JSONL
fixtures whose timestamps straddle the batch window. The existing
`test_analyze*.py` suite is the regression gate.

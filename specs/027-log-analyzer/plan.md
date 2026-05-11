# 027 — Implementation Plan

> Companion to `spec.md`. Four phases, ~6h total.

---

## Phase 1 — Log reader + BatchReport + bottleneck (~2h)

1. Create `src/cmcourier/services/analyze.py` with:
   - `@dataclass(frozen=True) class NetworkSummary` — per-kind
     counts, p50/p95/p99, total bytes.
   - `@dataclass(frozen=True) class SystemSummary` —
     cpu_pct_avg / max, ram_pct_avg / max, disk_*_avg / max,
     net_*_avg / max, worker_saturation_pct, sample_count.
   - `@dataclass(frozen=True) class BottleneckClassification`
     — class (str), confidence (float 0..1), reasons (list).
   - `@dataclass(frozen=True) class BatchReport` — fields per
     REQ-006.
   - `class LogReader` with `read_batch(batch_id) -> dict[str,
     list[dict]]` that returns the four record sets keyed by
     tier name.
   - `def build_batch_report(batch_id, records, *,
     cmis_max_bandwidth_mbps, pool_capacity) -> BatchReport`.
   - `def classify_bottleneck(...) -> BottleneckClassification`
     — pure function applying the documented rules.
2. Unit tests in `tests/unit/services/test_analyze.py`:
   - LogReader: happy path, missing file, corrupted line,
     cross-midnight, system samples absent (5 tests).
   - classify_bottleneck: each class + tie-break + no samples
     (8 tests).
   - build_batch_report: aggregates correctly (3 tests).

**Risk**: percentile computation must match what
`MetricsRecorder._StageBucket.summary()` does, otherwise
`stage_summary` deltas in compare will look bogus. Reuse
the same `statistics.quantiles` call signature.

**Done when**: `pytest tests/unit/services/test_analyze.py`
passes (16+ tests).

---

## Phase 2 — `analyze batch` CLI + terminal render (~1h)

1. Create `src/cmcourier/cli/commands/analyze.py` with a
   `analyze_group` Click group + `batch_command` subcommand.
2. Add the terminal formatter `format_terminal(report)` in
   `services/analyze.py`.
3. Wire `analyze_group` into `cli/app.py::main`.
4. Integration test in
   `tests/integration/cli/test_analyze.py`:
   - Write a fixture batch's JSONL files to `tmp_path / "logs"`.
   - `cli_runner.invoke(main, ["analyze", "batch", "<id>",
     "--log-dir", str(...)])`.
   - Assert exit 0 + key strings in stdout (batch_id, "S5",
     bottleneck verdict).
5. Golden-file test in `tests/integration/cli/test_analyze.py`
   for byte-identical output.

**Risk**: terminal output formatting drift if we change the
shape later. Keep the formatter simple — column-aligned text,
no rich.

**Done when**: `analyze batch` produces a report that humans
can read at a glance.

---

## Phase 3 — `analyze compare` + `analyze trends` (~1.5h)

1. Add `compare_batches(a, b)` + `format_compare_terminal()`
   in `services/analyze.py`.
2. Add `compute_trends(log_dir, *, last_n,
   pipeline_filter)` + `format_trends_terminal()`.
3. Wire both subcommands into `analyze_group`.
4. Integration tests in `tests/integration/cli/test_analyze.py`
   for each subcommand.

**Risk**: trends needs to read every `metrics-*.jsonl` in
the log dir and sort by date. Use the filename date prefix
for ordering — don't trust file mtime.

**Done when**: 3 CLI integration tests pass + ≥4 new unit
tests.

---

## Phase 4 — JSON output + docs + verify + FF merge (~1.5h)

1. Add `--format text|json` to each subcommand.
2. `format_json(report)` / `format_compare_json()` /
   `format_trends_json()` — deterministic key ordering,
   2-space indent.
3. Create `docs/how-to/log-analysis.md` with:
   - When to use `analyze batch` / `compare` / `trends`.
   - The five bottleneck classes + threshold table.
   - Sample output (copy from a fixture run).
   - Known limitations (small batches, tier-5 disabled, …).
4. Update `CHANGELOG.md` `[0.29.0]` + `[Unreleased]`.
5. Update `README.md` status checklist (27th change).
6. Mark POST-MVP §3 as SHIPPED in `docs/roadmap/POST-MVP.md`.
7. Full gate: ruff + mypy + pytest ≥695 green.
8. Conventional commit + FF merge into `main`.

**Done when**: `git log` on `main` shows the FF commit and
the analyzer's documented in `docs/how-to/log-analysis.md`.

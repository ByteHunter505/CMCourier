# CMCourier — Post-MVP Roadmap

> **Status**: Living document. Updated as new features are deferred or completed.
> **Last updated**: 2026-05-14

This document captures every feature, optimization, and design intent that is **deferred** beyond the MVP. **Nothing here is dropped** — everything is intentional, prioritized, and will be implemented in subsequent changes after the MVP is operational. Each entry is structured to be ready-to-consume as input for a future `/sdd-new` proposal.

---

## What "MVP" Means in This Project

The **MVP** delivers end-to-end document migration to IBM Content Manager across **three production pipelines** (`csv-trigger`, `rvabrep`, `local-scan`) plus the `single-doc` diagnostic, with all eight atomic stages (`S0`–`S7`, see `docs/domain/CMCOURIER_REBIRTH.md §10.1`), a single resizable S5 upload worker pool with **AIMD auto-tune**, batch-based execution with stage-by-stage resumability, default two-tab textual TUI, structured logging at the application + pipeline + network + slow-ops tiers, idempotent SQLite tracking, the `doctor` pre-flight command, and the cron-friendly `background` runner.

> **Note (048)**: there is no separate `as400-trigger` pipeline anymore. "AS400" is a *source* choice on the `rvabrep` pipeline (`indexing.source.kind: as400`), not its own pipeline — the `rvabrep` pipeline serves both a CSV file and a live AS400 query. See `CHANGELOG.md [0.51.0]`.

The MVP explicitly **excludes**: any size-aware upload scheduling (heavy/light lanes), system-resource sampling (`psutil` tier 5), offline log analysis tooling, AS400-backed tracking, multi-batch parallelism beyond the basic producer-consumer overlap of two batches, per-batch bandwidth quotas, and a cross-batch metadata cache.

Everything excluded lives below, with enough detail to start a new change directly.

### Status snapshot

- **Done (promoted into MVP)**: §1 — adaptive heavy/light upload lanes (shipped in change 036); §2 — system metrics tier 5 via `psutil` (shipped in change 026); §3 — offline log analysis tooling `cmcourier analyze` (shipped in change 027); §4 — AS400 NIARVILOG distributed idempotency (shipped in change 034); §5 — AIMD adaptive worker auto-tuning (shipped in change 025); §6 — additional pipelines csv / as400-trigger / local-scan (shipped in changes 012 / 014 / 016 — note: 048 later folded `as400-trigger` into the `rvabrep` pipeline as a source); §7 (N=2) — two-batch producer-consumer overlap (shipped in change 028; N=3..5 deferred to a future change); §9 — cross-batch metadata cache `document_cache` (shipped in change 037).
- **Still deferred**: §7 (N>2), §8, plus the §10 watchlist.

### Shipped since this snapshot was last numbered (specs 038–049)

The §-numbered sections above are the *original* post-MVP backlog. The
following changes shipped afterward as standalone specs (each on its
own `feat/NNN-*` branch, FF'd to `main`) — operational hardening, bug
fixes, and refinements surfaced during staging shakedown. They are
**not** roadmap sections; this list keeps the snapshot honest.

| Spec | Version | Summary |
|------|---------|---------|
| 038 — cmis-target-preflight | 0.41.0 | CMIS target pre-flight checks + upload payload trace |
| 039 — mock-rvabrep-generator | 0.42.0 | `cmcourier mock rvabrep` — synthetic RVABREP CSV at any scale |
| 040 — alfresco-url-compat | 0.43.0 | Alfresco CMIS compatibility (`repo_id=""` semantics, URL shape) |
| 041 — tui-fix-and-features | 0.44.0 | TUI: clean dashboard + MB progress + CHUNKS breakdown |
| 042 — tui-metrics-bleed | 0.45.0 | TUI metrics: per-chunk isolation + live UPLOAD counters |
| 043 — aimd-multibatch-p95 | 0.46.0 | AIMD auto-tune sees real p95 in multi-batch mode |
| 044 — robust-resume | 0.47.0 | Robust resume after `kill -9` mid-S5 (stage-gap detection) |
| 045 — idempotent-409 | 0.48.0 | Idempotent S5 upload on CMIS 409 conflict |
| 046 — polymorphic-trigger | 0.49.0 | Polymorphic `Trigger` model — each pipeline emits its natural shape |
| 047 — persist-cm-object-id | 0.50.0 | Persist `cm_object_id` on `S5_DONE` in the tracking DB |
| 048 — pluggable-rvabrep-source | 0.51.0 | Pluggable RVABREP source (CSV ↔ AS400); `as400-trigger` pipeline removed |
| 049 — niarvilog-column-mapping | 0.52.0 | Configurable NIARVILOG column / identifier names per environment |

Also note: change 039 (CHANGELOG `[0.39.0]`) shipped **§10 watchlist
item 2** — CMIS connection-pool eager warm-up at process start.

---

## §1. Adaptive Heavy / Light Upload Lanes — **SHIPPED in change 036 (2026-05-11)**

> Promoted out of post-MVP and delivered as part of change 036.
> Default off; enable via `processing.heavy_light_lanes.enabled`.
> The original ≥ 30 % throughput target was aspirational; measured
> wall-clock gain on synthetic bimodal batches is ~5-10 %. The real
> operator-visible win is per-doc latency. See
> `specs/036-heavy-light-lanes/`, `docs/how-to/heavy-light-lanes.md`,
> and `CHANGELOG.md [0.37.0]`.

### Intent

Replace the single-lane upload pool of the MVP with **two adaptive worker pools** to eliminate head-of-line blocking on heterogeneous batches. The pools share a global worker budget and rebalance dynamically based on queue depth.

The mental model is two carriageways:
- **Heavy lane**: few workers, large files, slow per-document throughput.
- **Light lane**: many workers, small files, high per-document throughput.

When one lane drains, its workers migrate to the other. When one lane is empty, all workers serve the remaining lane.

### Design

**Splitting policy** (heavy vs light per batch):
- After `S4` completes for a batch, the size distribution is known.
- Default split: **top 25% of files by size → heavy**, rest → light. Both the percentile and the absolute threshold (`>= X MB → heavy`) are configurable; whichever rule produces fewer heavy items wins (avoids degenerate batches where everything looks heavy).
- A batch with too few documents (`< heavy_lane_min_batch`, default 50) skips the split and uses single-lane upload.

**Worker budget**:
- Total workers = `processing.thread_count` (single global cap, same as MVP).
- Initial allocation: heavy lane gets `ceil(total * heavy_initial_ratio)` workers (default 0.2 = 20%), light gets the rest.
- Rebalance every `rebalance_interval_s` (default 10s) based on each queue's depth and observed throughput.
- Rebalance rule: if one lane is empty for `idle_threshold_s` (default 15s), migrate all its workers to the other lane.

**Bandwidth sharing**:
- The `BandwidthLimiter` from `CMCOURIER_REBIRTH.md §8.6` becomes a **shared token bucket** between lanes.
- Heavy lane requests larger token chunks (matches its per-doc transfer size); light lane requests smaller chunks.
- No per-lane reserved quota — both compete for the same global budget.

**TUI integration**:
- The UPLOAD tab shows two sub-panels: HEAVY and LIGHT.
- Each sub-panel: active workers, queue depth, throughput (bytes/sec and docs/sec), p95 latency, current operation per worker.
- Rebalance events are logged as TUI notifications.

### MVP placeholder

Single S5 worker pool with `processing.thread_count` workers, no size awareness, no rebalancing. Configuration field `processing.heavy_light_lanes.enabled` exists in config schema with a default of `false` so adopting the post-MVP feature is a config flip, not a code change.

### Why deferred

1. **Complexity multiplier**: dual pool + adaptive rebalancer + shared bandwidth bucket + dual TUI panes = roughly 3× the upload code path. Risky for the first working migration.
2. **Validation requires real data**: tuning the split percentile, rebalance interval, and idle threshold requires real production batches. Picking values blind is guesswork.
3. **Single-lane is not bad** — it is just not optimal. MVP delivers correct results; this delivers faster results.

### Acceptance criteria for the post-MVP change

- [ ] Configuration schema includes the full `processing.heavy_light_lanes` block validated by Pydantic.
- [ ] An integration test runs a synthetic batch with bimodal size distribution against a mocked CMIS adapter and verifies that lanes are assigned correctly, workers rebalance when one queue drains, and total throughput exceeds single-lane baseline by ≥30%.
- [ ] The TUI shows both sub-panels live during heavy/light runs.
- [ ] Disabling `heavy_light_lanes.enabled` falls back to single-lane behavior verbatim (regression test).
- [ ] Bandwidth limiter is shared (no per-lane reserved quota); a property test confirms total bytes/sec never exceeds `cmis.max_bandwidth_mbps`.
- [ ] Rebalance events are logged structurally for offline analysis.

### Dependencies

- Requires MVP S5 to be cleanly isolated (it will be — Hexagonal Constitution Principle I).
- Requires the staging directory layout from MVP (full file sizes known after S4).

---

## §2. System Metrics Observability (psutil Sampling) — **SHIPPED in change 026 (2026-05-11)**

> Promoted out of post-MVP and delivered as part of change 026.
> Measured sampler cost: ~0.10% CPU at 5 s interval. See
> `specs/026-system-metrics-tier5/` and
> `CHANGELOG.md [0.28.0]`.

### Intent

Add a fifth logging tier that samples system-resource utilization (CPU, RAM, disk IO, network IO) at configurable intervals to identify bottlenecks empirically rather than by guess.

### Design

- Background thread runs `psutil` sampling at `observability.system_sample_interval_s` intervals (default 5s).
- Each sample emits a JSON line to `./logs/system-{date}.jsonl`:
  ```json
  {"ts": "2026-05-08T10:23:45Z", "cpu_pct": 73.2, "ram_used_mb": 4120, "ram_total_mb": 8192,
   "disk_read_mbps": 12.4, "disk_write_mbps": 33.1, "net_in_mbps": 8.2, "net_out_mbps": 95.3,
   "process_pid": 12345, "process_threads": 42, "active_workers": 20}
  ```
- Process-level and host-level metrics are separated (host = whole machine; process = our PID and children).
- Sampling thread terminates cleanly on pipeline shutdown.

### MVP placeholder

`observability.system_metrics: false` in config. The schema field exists; the sampling thread is not implemented. Network metrics and pipeline metrics (cheap) are still on.

### Why deferred

1. `psutil` sampling is not free — at 1Hz it costs measurable CPU. The MVP cannot afford to debate "did we slow ourselves down with our own observability?" while also debugging the migration logic.
2. Bottleneck identification requires the Offline Log Analysis tooling (§3) to be useful — without it, the JSONL file is just data nobody reads.
3. The MVP will demonstrate whether bottlenecks exist at all — if the migration is upload-bound (which is likely), system metrics tell us nothing new.

### Acceptance criteria for the post-MVP change

- [ ] Sampling thread starts/stops with the pipeline, never leaks.
- [ ] Configuration toggle works (off → no thread spawned, no file created).
- [ ] Format is JSON Lines, one sample per line, parseable by §3 tooling.
- [ ] Sampling overhead measured: less than 1% CPU at default interval; documented.
- [ ] Documented in `docs/how-to/observability.md` (created in this change) including how to read the file.

### Dependencies

- None hard. Soft dependency on §3 (the offline analyzer) for the data to be valuable.

---

## §3. Offline Log Analysis Tooling — **SHIPPED in change 027 (2026-05-11)**

> Promoted out of post-MVP and delivered as part of change 027.
> See `specs/027-log-analyzer/`, `docs/how-to/log-analysis.md`,
> and `CHANGELOG.md [0.29.0]`. HTML rendering deferred to a
> future follow-up.

### Intent

Tools that consume the log tiers (app, pipeline, network, system) and produce **bottleneck attribution reports**: was a slow batch CPU-bound, memory-bound, disk-IO-bound, or network-bound? Which stage spent the most time? Which documents took the longest?

### Design

A subcommand suite under `cmcourier analyze`:

```
cmcourier analyze batch <batch_id>
    Aggregates all log files for a batch into one report:
    - Per-stage time distribution
    - Per-stage failure rate with error grouping
    - Slowest documents with full stage-by-stage breakdown
    - Resource utilization correlated with batch timeline
    - Bottleneck classification (CPU / mem / disk / net) with confidence

cmcourier analyze compare <batch_id_a> <batch_id_b>
    Diff two batches: throughput delta, latency delta, where time was spent differently.

cmcourier analyze trends [--last N] [--pipeline <name>]
    Throughput and p95 trends across the last N batches for a pipeline.
```

Output formats: human-readable terminal, JSON, HTML report (optional).

### MVP placeholder

None. The log files exist but reading them is manual.

### Why deferred

1. The tooling has zero value until §2 ships and there are real production batches with system metrics to analyze.
2. The format of each log tier may evolve during MVP shakedown; freezing the analyzer too early creates churn.
3. This is operations-side tooling, not migration-correctness tooling. MVP correctness ships first.

### Acceptance criteria for the post-MVP change

- [ ] `cmcourier analyze batch <id>` produces a complete report from a sample batch's log files.
- [ ] Bottleneck classifier is documented (rules + thresholds in `docs/how-to/log-analysis.md`).
- [ ] Reports are deterministic given the same input log files (test fixtures).
- [ ] Compare command produces a useful side-by-side for tuning runs.

### Dependencies

- §2 (system metrics) — soft. Useful without it, much more useful with it.

---

## §4. AS400-Backed Tracking Store — **SHIPPED in change 034 (2026-05-11)**

> Refined and delivered as a **hybrid** model rather than a
> drop-in replacement. The bank's existing `RVILIB.NIARVILOG`
> table coordinates cross-batch idempotency + parallel-Java
> evaluation; SQLite stays as the per-batch state machine.
> Toggleable via `tracking.as400_sync.enabled`. See
> `specs/034-as400-niarvilog-sync/`,
> `docs/how-to/as400-sync.md`, and CHANGELOG [0.35.0].

### Intent

The `ITrackingStore` port has two implementations: `SQLiteTrackingStore` (MVP) and `AS400TrackingStore` (post-MVP). The latter routes idempotency state into a centralized `RVILIB.MIGRATION_LOG` table on AS400, satisfying environments where the bank requires tracking centralized in the legacy system rather than on a workstation file.

### Design

- Implements the same `ITrackingStore` contract as SQLite.
- Connection management via the same thread-local pyodbc pattern as `AS400DataSource`.
- The schema mirrors the SQLite schema in `CMCOURIER_REBIRTH.md §9.2` adapted for DB2 for i (column types: `CHAR`, `TIMESTAMP`, `INTEGER`, etc.).
- The async writer queue concept (`§9.4`) is preserved, but commits are batched into AS400 inserts via `executemany`.
- Configuration: `tracking.backend: "as400:default"`.

### MVP placeholder

`tracking.backend: "sqlite"` is the only supported backend in MVP. The schema field accepts `as400:<alias>` as a value but raises `NotImplementedError` at startup with a clear message pointing to this roadmap entry.

### Why deferred

1. The integration test for AS400 tracking requires real AS400 access (Constitution Principle VI: AS400 is not mocked). MVP testing happens against CSV + SQLite + Alfresco, all locally available.
2. SQLite covers all dev / staging needs and many production scenarios.
3. The migration of the old codebase's AS400 tracking implementation is moderate (~300 lines + tests) and best done after the MVP shape is settled.

### Acceptance criteria for the post-MVP change

- [ ] `AS400TrackingStore` passes the same contract test suite as `SQLiteTrackingStore`.
- [ ] Integration test against real AS400 staging environment in nightly CI.
- [ ] Schema migration script (`scripts/install_as400_tracking_schema.sql`) idempotent.
- [ ] Documented operational behavior: connection failures during tracking writes never crash the pipeline (§10.1 stage S6 says tracking is non-blocking).
- [ ] `cmcourier doctor --check tracking` validates the AS400 tracking backend if configured.

### Dependencies

- AS400 staging environment availability (operational, not technical).

---

## §5. AIMD Adaptive Worker Auto-Tuning — **SHIPPED in change 025 (2026-05-10)**

> Promoted out of post-MVP and delivered as part of change 025. The
> section is kept for historical context and to document the
> design intent that the implementation honors. See
> `specs/025-tui-workers-autotune/` and `CHANGELOG.md [0.27.0]`.

### Intent

The MVP runs S5 with a fixed worker count from config. Post-MVP, an **AIMD (Additive Increase / Multiplicative Decrease)** controller adjusts the worker count online based on observed p95 latency, mirroring TCP congestion control.

### Design

- Configuration:
  ```yaml
  processing:
    auto_tune:
      enabled: true
      min_threads: 2
      max_threads: 50
      target_p95_ms: 5000.0
      adjustment_interval_s: 30
      warmup_seconds: 60
      timeout_auto_adjust: true
      min_timeout_s: 30
      max_timeout_s: 600
  ```
- Controller monitors rolling p95 of S5 upload latency over `adjustment_interval_s`.
- If `p95 < target_p95_ms`: add 1 worker (additive increase) until `max_threads`.
- If `p95 > target_p95_ms`: cut workers in half (multiplicative decrease), bounded by `min_threads`.
- During `warmup_seconds`, no adjustments happen (let the system stabilize first).
- Integration with §1 (heavy/light lanes): the controller adjusts the **total** worker budget; lane allocation remains the responsibility of §1's rebalancer.

### MVP placeholder

`processing.auto_tune.enabled: false`. Workers are static. The schema field exists.

### Why deferred

1. AIMD requires reliable p95 measurement, which requires §2 + §3 to validate the chosen targets are sensible.
2. AIMD interacts non-trivially with §1's lane rebalancer; coupling them at MVP is premature optimization.
3. Static workers are the right thing for the first migration: predictable, debuggable, easy to reason about.

### Acceptance criteria for the post-MVP change

- [ ] AIMD controller has unit tests for the additive and multiplicative branches.
- [ ] An integration test simulates a network slowdown midway through a batch and verifies workers contract appropriately.
- [ ] Configuration toggle works as expected (off → static workers).
- [ ] Documented in `docs/how-to/auto-tuning.md`.
- [ ] Co-design with §1 reviewed: who owns total budget, who owns allocation.

### Dependencies

- §1 (heavy/light lanes) — should ship first or together. Soft.
- §2 (system metrics) — for validating the chosen target.

---

## §6. Additional Pipelines (CSV / AS400 trigger / Local Scan) — **SHIPPED in changes 012, 014, 016**

> Promoted out of post-MVP and delivered ahead of schedule.
> `csv-trigger-pipeline` shipped in change 012,
> `as400-trigger-pipeline` in change 014, `local-scan-pipeline` in
> change 016. All four production pipelines plus `single-doc` are
> in MVP. See `CHANGELOG.md` for the per-change detail.

### Intent

The MVP ships with `rvabrep-pipeline` and `single-doc`. The remaining three pipelines from `CMCOURIER_REBIRTH.md §10.2` are additive — same stages, different `S0` strategy.

### Pipelines deferred

| Pipeline | S0 strategy | Use case |
|----------|-------------|----------|
| `csv-trigger-pipeline` | Read TriggerRecords from CSV file | Controlled batches, testing, regulatory exports |
| `as400-trigger-pipeline` | Run a configurable SQL against AS400 | Production with custom discovery queries |
| `local-scan-pipeline` | Walk a folder, cross-reference RVABREP for metadata | Files already extracted to disk |

### Design

Each is a new CLI command that registers a different `S0` strategy. The remaining stages (`S1`–`S7`) and the producer-consumer batch model are unchanged.

The Strategy interface for `S0` is part of the MVP (Constitution Principle I: the abstraction must exist from day one even if only one implementation is built first).

### MVP placeholder

`rvabrep-pipeline` and `single-doc` ship in MVP. The `S0Strategy` interface is defined; only the `RVABREPDirectStrategy` and `NoOpStrategy` (for `single-doc`) are implemented. Attempting to invoke a deferred pipeline shows a clear error pointing to this roadmap entry.

### Why deferred

1. Building four pipelines simultaneously dilutes the MVP focus. One end-to-end pipeline that demonstrably works is worth more than four half-working ones.
2. Each additional pipeline adds its own integration test surface and pre-flight validation (S0 source health, etc.).
3. Two of the three (CSV, AS400) are simple variations on the trigger source; once the first is solid, the rest are short changes.

### Acceptance criteria for each pipeline change

- [ ] CLI command exists with full flag support (`--batch-size`, `--batch <id>`, `--stage`, `--from`, `--resume`, `--skip-doctor`).
- [ ] `S0` strategy implementation passes contract tests (returns `Iterable<TriggerRecord>` correctly under various inputs).
- [ ] Integration test against fixtures in `tests/fixtures/<pipeline-name>/`.
- [ ] `doctor` command validates the new pipeline's source health.
- [ ] Updated `docs/how-to/<pipeline-name>.md`.

### Dependencies

- MVP `rvabrep-pipeline` shipped and stable.

---

## §7. Multi-Batch Pipeline Parallelism (>2 Batches in Flight) — **N=2 SHIPPED in change 028 (2026-05-11)**

> The two-batch producer-consumer overlap (the canonical
> "siempre dos lotes en vuelo" model) shipped in change 028.
> Raising the cap above 2 (the original `1..5` range) requires
> a per-chunk shared-pool refactor that's deferred to a future
> change. See `specs/028-multi-batch-orchestrator/`,
> `docs/how-to/multi-batch.md`, and
> `CHANGELOG.md [0.30.0]`.

### Intent

The MVP overlap is **two batches in flight**: one preparing (S0–S4), one uploading (S5). A natural extension is **N batches in flight** where N > 2 — multiple batches in different stages simultaneously, bounded by available memory and configured concurrency.

### Design

- Configuration: `processing.batches_in_flight` (default 2).
- A scheduler dispatches batches to a pool of "batch workers", each running a batch's S0–S5 sequence independently.
- Resource contention managed by:
  - Shared S5 worker pool (so total upload concurrency is unchanged)
  - Separate temp directories per batch
  - Tracking store transactions per batch isolate state
- TUI gains a "BATCHES" tab listing all in-flight batches and their current stage.

### MVP placeholder

`batches_in_flight = 2` (the producer-consumer overlap). Configuration field exists but values > 2 raise validation error pointing to this roadmap entry.

### Why deferred

1. Multi-batch parallelism shines only at scale (many small batches), but the MVP target is correctness on a single large batch.
2. Memory usage scales with batches in flight × largest staged file in each batch. Without §2 metrics, sizing this is dangerous.
3. Failure semantics get messier (one batch failing while others succeed — what does "exit code" mean?).

### Acceptance criteria

- [ ] Configurable `batches_in_flight`.
- [ ] Stress test with 5 batches in flight on synthetic data.
- [ ] TUI BATCHES tab shows all in-flight batches with current stage.
- [ ] Failure of one batch does not block others.
- [ ] Documented memory budgeting formula in `docs/how-to/scaling.md`.

### Dependencies

- §2 (system metrics) for memory-budget tuning.

---

## §8. Per-Batch Bandwidth Quota

### Intent

The current `cmis.max_bandwidth_mbps` is a global cap shared by all in-flight uploads. Post-MVP, allow per-batch quotas so high-priority batches get more bandwidth and low-priority batches get less.

### Design

- New config: `processing.bandwidth_policy: global | per_batch | priority_weighted`.
- `per_batch`: each batch reserves `cmis.max_bandwidth_mbps / batches_in_flight`.
- `priority_weighted`: batches carry a priority value; bandwidth allocated proportionally.
- TUI shows current per-batch bandwidth allocation.

### MVP placeholder

Global bandwidth policy only. The other policies error with a roadmap pointer.

### Why deferred

1. Requires §7 (multi-batch parallelism) to be meaningful.
2. Bandwidth policy interacts with §1's shared token bucket; design is co-dependent.
3. Solo-batch operation has no use for it.

### Acceptance criteria

- [ ] All three policies configurable and tested against real bandwidth limits in integration.
- [ ] Bandwidth limiter remains correct under all policies (total never exceeds global cap).
- [ ] Documented in `docs/how-to/bandwidth.md`.

### Dependencies

- §1 (lanes), §7 (multi-batch). Soft.

---

## §9. Cross-Batch Metadata Cache (`document_cache` Table) — **SHIPPED in change 037 (2026-05-11)**

> Promoted out of post-MVP and delivered as part of change 037.
> Default off; enable via `metadata.cache.enabled`. SQLite-backed,
> TTL via `metadata.cache.ttl_minutes` (default 60). CLI:
> `cmcourier cache stats|clear`. Structured
> `document_cache_hit` / `_miss` events fed to `cmcourier analyze`.
> See `specs/037-document-cache/`, `docs/how-to/document-cache.md`,
> and `CHANGELOG.md [0.38.0]`.

### Intent

The old codebase has a `document_cache` table (see `CMCOURIER_REBIRTH.md §9.2`) that stores resolved metadata per `txn_num` so a re-run in a different mode reuses prior resolution work. Post-MVP, formalize this as a cross-mode cache so the same document does not pay AS400 query costs twice.

### Design

- After S3 (Metadata Resolution) succeeds for a document, the resolved metadata is upserted into `document_cache`.
- Before S3 begins, the cache is consulted; on hit (and TTL valid), S3 is skipped and the cached metadata is used.
- Cache invalidation: TTL (`metadata_cache_ttl_minutes` from `CMCOURIER_REBIRTH.md §6.6`, default 60) plus manual `cmcourier cache clear --txn <num>`.
- Persists across pipeline invocations via SQLite (or AS400 in §4 environments).

### MVP placeholder

S3 always queries fresh. The `document_cache` table is created in the schema with a comment stating it is reserved for §9. The in-memory metadata pre-fetch from `CMCOURIER_REBIRTH.md §6.6` is MVP — that is per-process, not cross-batch.

### Why deferred

1. Adds a cache layer with its own correctness story (TTL, invalidation, what counts as "stale"). Too much risk for MVP.
2. The pre-fetch in `§6.6` already gives most of the benefit during a single run. Cross-batch re-use is a smaller delta.
3. Without observability (§2/§3) we cannot quantify the win.

### Acceptance criteria

- [ ] `document_cache` table populated after every successful S3.
- [ ] S3 short-circuits on cache hit (within TTL).
- [ ] Cache hit/miss metrics logged.
- [ ] `cmcourier cache clear` and `cmcourier cache stats` commands exist.
- [ ] TTL expiry tested with synthetic clock.

### Dependencies

- None hard.

---

## §10. Things That Might Become Features (Watchlist)

These are not promises — they are observations from the original codebase or the design that may grow into features if real operations demand them:

1. **Concurrent CMIS uploads against the same folder** — IBM CM has been observed to throttle when too many uploads target one folder. May need per-folder concurrency limits if it bites in production.
2. **Connection pool warm-up at process start** — currently each thread warms up its own JSESSIONID lazily; warming all up front could shave first-request latency.
3. **Resume after total host crash mid-S5** — the tracking idempotency handles process-kill mid-batch, but a subtle bug class is "S5 partial: file uploaded to CMIS but tracking write didn't land". Currently mitigated by CMIS idempotency on `cmis:objectId` + retry, but should be characterized empirically.
4. **Configurable retry budgets per pipeline** — MVP uses one global retry policy. Different pipelines may want different budgets.
5. **Periodic state snapshot for very long batches** — for a batch that takes hours, midway snapshots accelerate post-mortem analysis.
6. **CLI auto-completion** — Click supports it; not free but cheap. Worth doing once command surface stabilizes.

These items will not get their own roadmap section until a real operational pain pushes them to implementation.

---

## How This Document Evolves

- **Promotion to MVP**: if a deferred item turns out to be required for the first migration, move it out of this file into a `/sdd-new` change. Note the move in `CHANGELOG.md`.
- **Demotion / removal**: if an item turns out to be a bad idea after MVP shakedown, remove it and explain why in a brief note here. Do not silently drop.
- **New deferrals**: when MVP work surfaces a feature that should be deferred, add it as a new numbered section here. Numbering is append-only — never reuse a number.
- **Version**: this document is unversioned (it is a roadmap, not a contract). Major reorganizations are noted in `CHANGELOG.md`.

---

## Cross-References

- Constitution: `.specify/memory/constitution.md`
- Domain ground truth: `docs/domain/CMCOURIER_REBIRTH.md`
- Stage architecture: `docs/domain/CMCOURIER_REBIRTH.md §10`
- Observability tiers: `docs/domain/CMCOURIER_REBIRTH.md §17.4`
- Tracking schema: `docs/domain/CMCOURIER_REBIRTH.md §9`
- Changelog: `CHANGELOG.md`

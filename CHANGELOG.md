# Changelog

All notable changes to CMCourier are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once code begins shipping.

> **Pre-implementation phase**: while no code has shipped yet, releases are tagged at meaningful documentation milestones (constitution ratification, architectural decisions, roadmap consolidation). Once the first MVP change merges, the project moves to standard SemVer.

---

## [Unreleased]

### Tooling

- **031** — `cmcourier mock generate`: synthetic RVABREP file-tree
  generator for dry runs and integration tests. Reads RVABREP rows from
  CSV or AS400, materializes valid PDFs (`img2pdf` multi-page), TIFFs
  (Pillow LZW), and JPEGs (Pillow) under a configurable root mirroring
  `<source_root>/<ABAICD>/<ABAJCD>`. Suffix-parsed size bounds
  (`--pdf-min 10kb`, `--pdf-max 2mb`, …), `--seed`, `--dry-run`,
  `--force`, `--include-deleted`, `--limit`, `--system`,
  `--document-type`. Pure-additive surface; see
  `specs/031-mock-file-generator/spec.md`.

### Planned for next releases

Post-MVP roadmap (`docs/roadmap/POST-MVP.md`) — still pending:

- **§1** — Adaptive heavy / light upload lanes (REBIRTH §10.7).
- **§7 (N > 2)** — Raise `batches_in_flight` cap above 2 (the
  N=2 producer-consumer overlap shipped in 028; N=3..5 requires
  a deeper refactor — deferred).
- **§8** — Per-batch bandwidth quota.
- **§9** — Cross-batch `document_cache` table.
- **§10** — Watchlist items (per-folder CMIS concurrency, pool
  warm-up, retry budgets per pipeline, CLI auto-completion, …).

Operational milestones outside the roadmap doc:

- Real-data dry run against staging.
- First production migration.

### Removed (no longer pending)

- ~~§2 System metrics tier 5 (`psutil` sampling)~~ — shipped in 026.
- ~~§3 Offline log analysis (`cmcourier analyze`)~~ — shipped in 027.
- ~~§4 AS400 NIARVILOG distributed idempotency~~ — shipped in 034.
- ~~§5 AIMD adaptive worker auto-tuning~~ — shipped in 025.
- ~~§6 Additional pipelines (csv / as400 / local-scan)~~ —
  shipped in 012 / 014 / 016.
- ~~§7 (N=2)~~ — producer-consumer overlap of two batches in
  flight, shipped in 028.

---

## [0.36.0] — 2026-05-11 — **mapping CSV split (MapeoRVI_CM + MetadatosCM) + CMISType column**

Aligns CMCourier with the bank's **production** Modelo Documental
format. `MappingConfig` now accepts either the legacy consolidated
CSV (`csv_path`) or the production split pair
(`rvi_cm_csv_path` + `metadatos_csv_path`). When operating in split
mode, the service joins `MapeoRVI_CM.csv` and `MetadatosCM.csv` by
`IDCM ↔ IDCorto` and populates `CMMapping.cmis_type` from the new
`CMISType` column. This unblocks the AS400 `NIARVILOG.TIPIDN` field
introduced in 034 (no longer always empty in production).

### Added

- `MappingConfig.rvi_cm_csv_path` + `metadatos_csv_path` +
  `model_validator` enforcing exactly-one-of with `csv_path`.
- `MappingConfig.cmis_type_column` exposed in the pydantic schema
  (gap left by 034).
- `MappingColumnsConfig` split-mode column-name fields with
  defaults matching the real bank headers (`IDRVI`, `IDCM`,
  `IDClaseDocumental`, `CMISType`, `IDCorto`, `Metadato`,
  `Requerido`) plus `required_marker = "Yes"`.
- `MappingService(source, columns, metadata_source=...)`: when
  `metadata_source` is set, the service runs the split-mode loader
  (join by `IDCM ↔ IDCorto`, filter `Requerido` truthy values
  case-insensitively, set `clase_name = clase_id`).
- `cmcourier.config.wiring.build_mapping_service(MappingConfig)` —
  single factory dispatching on mode and managing source
  open/close. Consumed by `wire_services_from_config`,
  `cli.doctor._check_mapping_completeness`,
  `cli.doctor._check_cm_type_alignment`,
  `cli.commands.inspect.inspect_mapping`,
  `cli.commands.inspect.inspect_mapping_stats`.
- `docs/samples/csv/MapeoRVI_CM.csv` gains the `CMISType` column
  (empty placeholder values — the bank fills these at deployment).

### Changed

- `MappingConfig.csv_path` becomes `FilePath | None` (was
  required) to allow the alternative split mode.
- `MappingService` no longer takes ownership of its sources'
  lifecycle in production paths — `build_mapping_service` closes
  them after the cache loads.
- `docs/how-to/as400-sync.md` `TIPIDN` row updated; the
  known-limitation note ("empty until 035 ships") removed.

### Backwards compatibility

All 857 pre-035 tests keep passing. The legacy consolidated test
fixture `tests/fixtures/services/modelo_documental.csv` continues
to drive `MappingConfig(csv_path=...)`. The Java parallel
migrator's append-only read of `MapeoRVI_CM.csv` is preserved
(`CMISType` is added as a trailing column).

### Out of scope

- Reading the production `MapeoRVI_CM.csv` with `CMISType` values
  populated — the bank owns that file.
- Migrating test fixtures to split format. They stay consolidated
  to exercise the legacy mode.
- Changing `clase_name` representation in CLI output or logs —
  split mode uses `clase_id` (production CSV has no name column,
  confirmed by the bank).

### Spec

- `specs/035-mapping-csv-split/`: spec.md, plan.md, tasks.md.

---

## [0.35.0] — 2026-05-11 — **AS400 NIARVILOG distributed idempotency (POST-MVP §4)**

Adds a toggleable distributed-idempotency layer on top of the
existing `SQLiteTrackingStore`. When
`tracking.as400_sync.enabled=true`, the pipeline coordinates
cross-batch idempotency with the bank's centralized
`RVILIB.NIARVILOG` table — enabling parallel-Java evaluation
and multi-workstation operation without double-upload risk.
When disabled (the default), behavior is byte-identical to
pre-034.

### Added

- **`tracking.as400_sync`** Pydantic block with the toggle +
  connection + retry policy. Cross-field validator: enabling
  the toggle without a connection raises `ValidationError`.
- **`As400NiarvilogStore`** (`adapters/tracking/as400_niarvilog.py`):
  atomic `try_claim` (UPDATE STSCOD='I' WHERE STSCOD='N' with
  INSERT fallback for first-time rows), `mark_uploaded`,
  `mark_failed`, `read_state` (full PK lookup),
  `read_state_by_txn` (TRNNUM-only for pre-flight + CLI),
  `mark_uploaded_by_txn` (for `--prefer-local` workflow),
  `cleanup_stale_in_progress`.
- **`IdempotencyCoordinator`** (`services/idempotency.py`):
  composes `SQLiteTrackingStore` (always) with
  `As400NiarvilogStore` (optional). Dispatches read/write
  per the documented rules:
  - `is_uploaded`: AS400 when active (`STSCOD='O'`), else
    SQLite.
  - `try_claim`: always `True` when AS400 disabled; atomic
    claim when active.
  - `mark_uploaded` / `mark_failed`: SQLite first (in-process
    resume anchor), then AS400 (operator-visible state).
  - `preflight_sync`: cleanup stale + reconcile each
    txn_num. Returns `SyncReport` with
    `imported_from_as400`, `conflicts`, `stale_cleaned`.
    Optionally raises `IdempotencyConflictError`.
- **`cmcourier sync` CLI** with two subcommands:
  - `cmcourier sync status` — read-only stale cleanup +
    connectivity check.
  - `cmcourier sync resolve <txn>
    --prefer-as400 | --prefer-local --cm-object-id <id>` —
    operator-driven resolution.
- **Doctor check** `as400_sync`: SKIPs when disabled,
  validates connection + table existence when enabled.
- **Retry / backoff** (`As400UnreachableError`): transient
  `pyodbc.OperationalError` triggers exponential backoff
  (`base, base*2, base*4, …` capped at 300s) for
  `retry_attempts` total. `IntegrityError` is never retried
  (race detection signal for `try_claim`).
- **Field mapping** (locked, documented in
  `docs/how-to/as400-sync.md`):
  - `SISCOD ← trigger.system_id`,
    `TRNNUM ← document.txn_num`,
    `DOCFRM ← document.index7` (= RVABREP ABAHCD),
    `IMGARC ← document.file_name` (first-page),
    `IMGTIP ← document.image_type`,
    `CTECIF ← trigger.shortname`,
    `CTENUM ← int(trigger.cif or 0)`,
    `STSCOD ← N/I/O/F` (state-machine derived),
    `IDNBAC ← mapping.id_corto` (= IDCM),
    `TIPIDN ← mapping.cmis_type` (populated from
    `MapeoRVI_CM.CMISType` in split mode — 035),
    `OBJIDN ← record.cm_object_id`,
    `NUMREI ← record.retry_count`,
    `EERRMSG ← record.error_message`.

### Changed

- **`CMMapping`** gains `cmis_type: str = ""` field. The
  mapping service reads `CMISType` column when present,
  defaults to empty string when not. Backwards-compatible
  with the consolidated test fixture.
- **`StagedPipeline.__init__`** accepts an optional
  `coordinator: IdempotencyCoordinator | None = None`
  parameter. When `None`, the pipeline runs the legacy
  SQLite-only path — byte-identical to pre-034. When set,
  `_upload_one` routes through the coordinator's
  `try_claim` / `mark_uploaded` / `mark_failed`.
- **`build_pipeline`** constructs the coordinator from the
  YAML's `tracking.as400_sync.enabled`.

### Tests

- 6 new schema tests covering defaults, ranges,
  cross-field validator, integration with `TrackingConfig`.
- 18 store tests including:
  - try_claim N-row update / INSERT fallback / race losing.
  - mark_uploaded ok + zero-rows warning.
  - mark_failed numrei increment + 1024 truncation.
  - read_state + read_state_by_txn present / absent.
  - cleanup_stale rowcount semantics.
  - Error wrapping (Coordination vs Unreachable).
  - 4 retry tests: transient retry succeeds, exhausted →
    Unreachable, IntegrityError not retried, backoff
    sequence respects base.
- 15 coordinator tests (disabled path, enabled path,
  preflight_sync three branches).
- 7 CLI sync tests (help, status, prefer-as400 happy +
  not-found, prefer-local happy + missing cm-object-id
  guard, mutually-exclusive flags).
- 1 doctor SKIP test for `as400_sync`.
- 1 CMMapping test for `cmis_type` default.
- **857 total green** (up from 829), mypy + ruff + format
  clean across the six phases.

### Documentation

- New `docs/how-to/as400-sync.md` with the full picture:
  when to enable, YAML snippet, field mapping table, status
  transition diagram, concurrency model, pre-flight
  reconciliation, conflict resolution playbook, retry
  semantics, known limitations.

### Notes

- **One row per txn**: per the bank's operational convention,
  NIARVILOG has at most one row per `TRNNUM` (the first
  page's `IMGARC`). Multi-page docs share a single row.
  Confirmed with the operator during spec.
- **`sync resolve --prefer-as400` doesn't write SQLite
  directly**. It prints the AS400 state; operator re-runs
  the pipeline with `--resume` so the in-process resume
  logic picks up `STSCOD='O'` and skips. Avoids extending
  `ITrackingStore` with a write-by-txn surface.
- **`sync resolve --prefer-local` requires
  `--cm-object-id`** explicit. Operator gets it from
  `cmcourier batch show`.

---

## [0.34.0] — 2026-05-11 — **Tier 1 polish: `--total` flag + CI integration docs**

Two small operational ergonomics wins bundled into one change.
Closes the Tier 1 polish queue.

### Added

- **`--total <N>` flag** on every pipeline run command
  (`csv-trigger`, `rvabrep`, `as400-trigger`, `local-scan`,
  `single-doc`). Caps the number of triggers processed after
  the S0 acquire. Useful for validating a config + environment
  by running a tiny subset before the full migration.
  - Threaded through `StagedPipeline.run(..., total=N)` and
    `MultiBatchOrchestrator.run(..., total=N)`. Both N=1 and
    N=2 paths respect it uniformly.
  - `--total 0` rejected by Click's `IntRange(min=1)`.
  - `--total <larger-than-source>` is a no-op (no truncation).
- **CI / PR integration section** in
  `docs/how-to/log-analysis.md`. Covers minimum-viable
  regression check (bash `case` on `bottleneck.classification`),
  GitHub Actions and GitLab CI yaml templates, useful `jq`
  filters for throughput / p95 / slow-op extraction, exit-code
  contract for the analyzer, and known CI limitations
  (no real CMIS, small `--total` masks worker-saturation).

### Tests

- 5 new integration tests covering `--total`: caps N=1 path,
  caps N=2 multi-chunk path, larger-than-source is a no-op,
  zero rejected, `--help` lists the flag on every pipeline.
- 748 total green (up from 743), mypy + ruff clean.

### Notes

- Skipped version `0.32.0` reserved for the parallel change
  **031 mock-file-generator** developed on a separate branch.
- This change closes the Tier 1 (operator polish) queue. Next
  pending work needs real data (dry run staging) or external
  confirmation (§4 AS400 tracking pending bank decision).

---

## [0.33.0] — 2026-05-11 — **shell auto-completion (`cmcourier completion`)**

> Skips 0.32.0 — that version is reserved for the parallel
> change 031 (HTML report for `cmcourier analyze`) being
> developed on a separate branch.



The CLI surface area is now ~17 subcommands across 5 pipelines,
4 batch ops, 3 inspect targets, 3 analyze sub-modes, plus
doctor/background/as400-query. Tab-completion stops being a
nice-to-have and becomes a real DX win.

### Added

- **`cmcourier completion <bash|zsh|fish>`** subcommand. Emits
  the shell-completion script on stdout. Backed by Click's
  built-in :mod:`click.shell_completion` (auto-tracks every
  subcommand + option that ships in the future without
  maintenance).
- Install instructions documented in the new subcommand's
  docstring — one-line `eval` in `.bashrc`/`.zshrc`, or a
  redirect to `~/.config/fish/completions/cmcourier.fish` for
  fish.

### Tests

- 6 new CLI integration tests: every shell's script renders,
  unknown shells rejected by `click.Choice`, `--help` lists
  the subcommand and the supported shells.
- 743 total green (up from 737), mypy + ruff clean.

### Notes

- Zero impact on existing functionality — `cmcourier`
  invocations without `completion` behave identically.

---

## [0.31.0] — 2026-05-11 — **TUI multi-batch view (`CHUNKS` tab)**

The producer-consumer overlap shipped in 028 had a UX caveat:
when `--tui` was enabled, the orchestrator forced
`batches_in_flight=1` because the TUI was tightly bound to a
single `MetricsRecorder`. 030 lifts that restriction. The TUI
now renders multi-batch runs faithfully and gains a third
**`CHUNKS`** tab that lists every chunk's state in real time.

### Added

- **`ChunkState`** dataclass and orchestrator-level state
  machine (`MultiBatchOrchestrator.chunks_snapshot()` +
  `MultiBatchOrchestrator.active_recorder()`). Each chunk
  transitions `QUEUED → PREP → UPLOAD → DONE` (or `FAILED`)
  with thread-safe state updates from the prep / upload
  worker threads.
- **`TUIDataProvider`** accepts an optional
  `recorder_provider` callable that returns the
  currently-active chunk's recorder. The provider's
  `_metrics` accessor live-binds to whatever the
  orchestrator says is "current" — PREP and UPLOAD tabs
  render coherent data as chunks transition.
- **`TUIDataProvider`** accepts an optional
  `chunks_provider` callable; `TUISnapshot.chunks_state`
  is the rendered list.
- **`CHUNKS` tab** (`cmcourier/tui/chunks_tab.py`,
  shortcut `[C]`): counts header + per-chunk row with
  index, batch_id, status glyph, s5_done, s5_failed.

### Changed

- `cli/app.py::_run_with_optional_tui` no longer forces
  `batches_in_flight=1` when `--tui` is on. `--resume`
  still forces N=1 (resume is inherently single-batch).
- `cli/_tui_runner` renamed `run_pipeline_with_tui` →
  `run_orchestrator_with_tui`. The worker thread now runs
  `orchestrator.run(**kwargs)` (returns
  `MultiBatchRunReport`).
- `TUIDataProvider.__init__` keeps its old positional
  surface — `metrics_recorder` is now the **fallback**
  recorder used when no `recorder_provider` is supplied.
  Pre-030 callers keep working without changes.

### Tests

- 4 new orchestrator state-machine tests (chunks_snapshot
  empty, after run, marks failed, active_recorder lifecycle).
- 5 new CHUNKS-tab render tests (empty placeholder,
  single-DONE, mixed states, FAILED counted, long batch_id
  truncated).
- 737 total green (up from 728), mypy + ruff clean.

### Notes

- Operator runs that pass `--tui --batches-in-flight 2` now
  get the multi-batch flow with live updates. Operators who
  prefer the single-batch view can pass
  `--batches-in-flight 1` explicitly.

---

## [0.30.1] — 2026-05-11 — **fix: shared `BandwidthLimiter` (real cap enforced)**

A latent bug surfaced by 025's concurrent S5 worker pool: the
pre-029 `BandwidthLimiter` was constructed **per upload call**,
so each worker thread had its own token bucket. With
`cmis.workers=4` and `cmis.max_bandwidth_mbps=100`, the
effective network ceiling was `~400 Mbps` — four times the
configured value. The configured cap was meaningless.

### Fixed

- **`TokenBucket`** extracted from `BandwidthLimiter` as a
  thread-safe, process-shared bucket. `CmisUploader.__init__`
  builds one bucket from `cfg.max_bandwidth_mbps` and reuses
  it for every upload. Concurrent `consume()` calls serialize
  on an internal lock so the configured rate is the **global**
  ceiling.
- **`BandwidthLimiter.__init__(stream, bucket)`** — the
  limiter is now a thin file-like wrapper that defers
  throttling to the shared bucket. No per-instance token math.
- **`cmcourier analyze`** `network-bound` heuristic is now
  meaningful: the comparison against `cmis.max_bandwidth_mbps`
  reflects an actual enforced ceiling.

### Tests

- New `TestTokenBucket` group (3 tests): zero-mbps no-op,
  single-thread throttle, **property test proving 4
  concurrent workers cannot exceed the cap** (`wall_elapsed
  > expected_at_global_rate`).
- Existing `TestBandwidthLimiter` adapted to the new
  `(stream, bucket)` constructor — behavior for single-stream
  cases unchanged.
- 727 total green (up from 724), mypy clean, ruff clean.

### Notes

- Not on the POST-MVP roadmap (it was a latent bug, not a
  feature). The roadmap §1 (heavy/light lanes) explicitly
  required this fix as a prerequisite — that work is now
  unblocked.

---

## [0.30.0] — 2026-05-11 — **multi-batch orchestrator (POST-MVP §7, N=2)**

The "siempre dos lotes en vuelo, uno preparándose y otro
cargándose" model from POST-MVP §7 — turns out it was never
implemented. The pre-028 `pipeline.run()` did S0→S5 in one
sequential pass over the full trigger source. 028 introduces
a producer-consumer orchestrator that chunks the source and
overlaps prep + upload of consecutive chunks.

### Added

- **`ProcessingConfig`** Pydantic block under
  `pipeline.processing` with `batches_in_flight: int = Field(
  default=2, ge=1, le=2)`. Top-level
  `pipeline.processing.batches_in_flight`.
- **`cmcourier.orchestrators.chunked`** — pure
  `chunked(items, size)` helper.
- **`cmcourier.orchestrators.multi_batch.MultiBatchOrchestrator`**
  — wraps a `StagedPipeline` and runs multiple chunks with
  producer-consumer overlap. For `N=1` it's a thin
  pass-through (byte-identical to pre-028). For `N=2` it
  spawns one prep thread (S0..S4) and one upload thread
  (S5) communicating via a bounded `queue.Queue`.
- **`MultiBatchRunReport`** dataclass — aggregates per-chunk
  `RunReport`s plus a `failed_chunks` list.
- **`--batches-in-flight <N>` CLI flag** on every pipeline run
  command. Defaults to `config.processing.batches_in_flight`.
  `--resume` and `--tui` both force `N=1`.
- **Per-chunk MetricsRecorder** — each chunk gets its own
  recorder so per-chunk `batch_summary` events + slow-ops
  files stay isolated. The shared S5 worker pool +
  AutoTuneController + tracking store are reused across
  chunks.

### Changed

- **`_SlowOpHandler`** now filters log records by
  `record.batch_id` so multiple concurrent
  MetricsRecorders don't cross-pollinate slow ops. Records
  without a `batch_id` extra are dropped.
- **Stage methods** (`_stage_s0_s1`, `_stage_s2..s5`) accept
  an optional `recorder` keyword so the orchestrator can
  route per-chunk timings to per-chunk recorders. Default
  remains `self._metrics` for the legacy single-batch path.
- **CLI output**: when more than one chunk runs, per-chunk
  lines + a TOTALS line. When one chunk runs (or `N=1`),
  the legacy single-line summary is preserved verbatim.

### Tests

- 6 new schema tests for `ProcessingConfig`.
- 8 new chunker unit tests.
- 3 new MetricsRecorder isolation tests (handlers filter by
  batch_id; bandwidth sampler still sees everything).
- 7 new orchestrator unit tests (N=1 pass-through, N=2
  overlap, wall-clock proof of overlap, exception isolation,
  N=3 rejection, empty source, resume forces N=1).
- 5 new CLI integration tests covering `--batches-in-flight`.
- 724 total green (up from 695 in 027), mypy clean, ruff
  clean.

### Documentation

- New `docs/how-to/multi-batch.md` with the
  producer-consumer model, output format, failure
  semantics, and memory-budgeting guidance.

### Notes

- **N > 2 deferred**. The original POST-MVP §7 spec listed
  N up to 5. Supporting N>2 requires per-chunk shared-pool
  semantics for the S5 ResizableSemaphore + AutoTune
  controller that would significantly inflate this change.
  Documented as a future change.
- **TUI multi-batch view deferred**. The TUI currently
  shows one batch at a time. When `--tui` is on, the
  orchestrator forces `N=1` so the operator's view stays
  coherent.

---

## [0.29.0] — 2026-05-11 — **offline log analyzer (POST-MVP §3)**

Closes the second-half of the §17.4 story: now that tier 5 is
on disk (026), operators have a first-class way to *read* it.
The `cmcourier analyze` subcommand suite consumes the five
log tiers and produces per-batch reports, pairwise deltas, and
trend series — all deterministic, all read-only.

### Added

- **`cmcourier analyze batch <batch_id>`** — full per-batch
  report: header, per-stage table (count/p50/p95/p99),
  network table (per kind), system table (when tier 5 is
  available), top-5 slow ops, and a bottleneck verdict line
  with confidence + reasoning.
- **`cmcourier analyze compare <a> <b>`** — side-by-side
  delta: throughput delta, elapsed delta, per-stage p95
  delta, and a one-line bottleneck-class comparison.
- **`cmcourier analyze trends [--last N] [--pipeline <name>]`**
  — throughput + S5 p95 over the last N `batch_summary`
  events, optionally filtered by pipeline. Default `--last 10`.
- **`--format text|json`** on every subcommand. JSON is
  deterministic (sorted keys, 2-space indent, no embedded
  timestamps).
- **`--config <path>`** or **`--log-dir <path>`**: read
  from a YAML (to derive `log_dir` + `cmis.max_bandwidth_mbps`
  + worker count for the classifier) or skip the YAML and
  read raw.
- **`cmcourier.services.analyze`** module exposing
  `LogReader`, `BatchReport`, `BottleneckClassification`,
  `NetworkSummary`, `SystemSummary`, `CompareReport`,
  `TrendRow`, `build_batch_report`, `classify_bottleneck`,
  `compare_batches`, `compute_trends`, and the six
  formatter functions. All pure, all importable as a library.
- **Bottleneck classifier** with five classes
  (`cpu-bound`, `memory-bound`, `disk-bound`,
  `network-bound`, `worker-saturated`) + an `under-utilized`
  fallback. Rules + thresholds documented in
  `docs/how-to/log-analysis.md`.
- **Resilient JSONL reader** — malformed lines are logged
  WARNING and skipped; missing files yield empty record
  lists; cross-midnight rotated files are merged
  transparently by glob.

### Tests

- 16 new unit tests for `LogReader`, `classify_bottleneck`,
  and `build_batch_report` (tier reads + each bottleneck
  class + tie-break + no-samples fallback + aggregation).
- 7 new CLI integration tests covering every subcommand
  (text + JSON, deterministic output, trends filter, compare
  delta).
- 695 total passing (up from 672 in 026).

### Documentation

- New `docs/how-to/log-analysis.md` — when to use each
  subcommand, full bottleneck-rule table with thresholds,
  sample terminal output, and an operator playbook
  ("did doubling workers actually help?", "are we drifting
  over time?").

### Notes

- HTML report rendering listed in the POST-MVP §3
  acceptance criteria was explicitly **deferred** to a
  future follow-up. The current text + JSON pair is enough
  for terminal + CI + jq workflows.
- The analyzer is read-only — it never touches the
  pipeline's running state, the tracking SQLite, or any
  remote service. Safe to run mid-batch.

---

## [0.28.0] — 2026-05-11 — **tier-5 system metrics (POST-MVP §2)**

Closes the last `psutil`-shaped gap on the §17.4 observability
surface. When a pipeline runs, a daemon thread snapshots
host- and process-level metrics every 5 seconds (configurable)
and appends one JSON line per sample to
`./logs/system-{date}.jsonl`. This is the data input that
unblocks the offline log analyzer (POST-MVP §3) and lets us
validate the AIMD target the 025 auto-tune controller assumes.

### Added

- **`SystemMetricsSampler`** in
  `cmcourier/observability/system_metrics.py`. Daemon
  `cmcourier-syssampler` thread. Idempotent `start()` /
  `stop()`. First-sample delta fields are `0.0` (no baseline
  yet); subsequent samples compute MB/s from byte counters.
  Errors from `psutil` are caught, logged WARNING, and
  skipped — the thread never dies.
- **`SystemSample` dataclass** with the full tier-5 field
  set: `ts_iso`, `cpu_pct`, `ram_used_mb`, `ram_total_mb`,
  `disk_read_mbps`, `disk_write_mbps`, `net_in_mbps`,
  `net_out_mbps`, `process_pid`, `process_threads`,
  `process_cpu_pct`, `process_rss_mb`, and `active_workers`
  (live from `WorkerPoolStats.snapshot().busy`).
- **`SystemMetricsConfig`** Pydantic model under
  `observability.system_metrics`: `enabled: bool = True`,
  `sample_interval_s: float = 5.0` (range 1.0–60.0). The
  `_STRICT` model enforces extra-forbid like every other
  config block.
- **Legacy-bool coercion**: pre-026 YAMLs that wrote
  `observability.system_metrics: false` keep loading
  (`field_validator(mode="before")` lifts the bool into
  `{"enabled": <bool>}`).
- **Pipeline lifecycle hook**: `StagedPipeline` accepts a
  `sampler` kwarg, late-binds it to the worker pool stats,
  starts it in `run(...)`, and stops it in a `finally:`
  block so pipeline exceptions never leak the thread.
- **`build_sampler(observability_cfg, log_dir)`** factory in
  `observability.system_metrics`. Returns `None` when
  disabled; constructed (not started) sampler otherwise.

### Changed

- `ObservabilityConfig.system_metrics` switches from
  `bool = False` to a nested `SystemMetricsConfig` model.
  The pre-026 rejection validator (`_reject_system_metrics`)
  is removed.
- `config/wiring.py::build_pipeline` builds the sampler from
  the observability config and threads it into
  `StagedPipeline(sampler=...)`.

### Tests

- 6 new schema tests (REQ-004): structured-true,
  structured-false, structured-custom-interval, legacy
  bool-false coerced, legacy bool-true coerced, interval
  out-of-range rejected, unknown-field rejected.
- 10 new sampler unit tests (REQ-017): disabled→no-op,
  start/stop idempotent, first sample has zero deltas,
  second sample computes deltas correctly with patched
  psutil counters, `active_workers` propagation
  (None + WorkerPoolStats), late-binding via
  `attach_pool_stats`, JSONL write to today's file.
- 2 new integration tests (REQ-018): full
  `csv-trigger-pipeline` produces `system-<today>.jsonl`
  with valid JSON lines; `enabled: false` skips the
  sampler entirely.
- 672 tests total green (up from 655 in 025).

### Performance

- **Measured cost**: +0.10% CPU at the default 5 s interval
  over a 60 s window on the dev workstation (12 samples
  written, ≈1 sample/5 s). Spec target was <1%.

### Dependencies

- New runtime dep: `psutil>=5.9,<7.0`.
- New mypy stub dep: `types-psutil>=5.9,<7.0` in
  `.pre-commit-config.yaml`.

---

## [0.27.0] — 2026-05-10 — **live TUI + S5 worker pool + AIMD auto-tune (REBIRTH §10.6, §17.4)**

The S5 (CMIS upload) stage moves from a sequential loop to a real
`ThreadPoolExecutor` worker pool, gains a textual two-tab live
TUI, and grows an AIMD (Additive-Increase / Multiplicative-
Decrease) auto-tune controller. This is the §10.6 "TUI by default"
commitment realized end-to-end.

### Added

- **`ThreadPoolExecutor`-based S5** in `StagedPipeline._stage_s5`.
  The pool size comes from `cmis.workers` (default 4, range
  1..32). Each task acquires a `ResizableSemaphore` slot before
  uploading, so the AIMD controller can raise/lower the *active*
  cap without draining the pool.
- **`AutoTuneController`** (`services/auto_tune.py`). Runs on a
  daemon thread, polls the recorder's `current_stage_p95("S5")`
  every `cmis.auto_tune.interval_s` seconds, and applies AIMD:
  observed p95 < target → +1 worker; observed p95 > target →
  `*0.5` workers + bump upload timeout; in-band → noop. Honors
  a warmup window so the first decision waits for stable
  measurements. All decisions are logged with structured extras
  (`workers_before/after`, `timeout_before_s/after_s`,
  `p95_observed_ms`, `p95_target_ms`, `action`).
- **Textual two-tab TUI** (`src/cmcourier/tui/`). PREP tab shows
  S0..S4 progress bars + slow-op listings. UPLOAD tab shows S5
  progress, a WORKERS panel (capacity/in-use/idle/timeout/
  last-move/next-tick), a NETWORK panel + 60-bucket 1Hz
  bandwidth sparkline (y-axis 0 → `cmis.max_bandwidth_mbps`,
  auto-scale when ceiling is 0), and a RUN COMPLETE overlay.
  Tabs are switched with `[P]`/`[U]`; `[Q]` exits.
- **`--tui / --no-tui` CLI flag** on every pipeline run command
  (`csv-trigger`, `rvabrep`, `as400-trigger`, `local-scan`,
  `single-doc`). Default `tui=True`. When stderr is not a TTY
  (cron, CI, pytest), the TUI auto-disables silently. An
  *explicit* `--tui` in a non-TTY context exits **2** with a
  clear `ConfigurationError`. The `background` command does not
  accept `--tui` — unattended runs are always headless.
- **Worker label in network events** (`worker` field, e.g.
  `cmcourier-s5_3`). Whitelisted in
  `observability/formatter.py::ALLOWED_EXTRA_FIELDS` and
  surfaced in the TUI's slow-op rows.
- **`auto_tune` config block** (Pydantic-validated). Fields:
  `enabled`, `target_p95_ms`, `tolerance_ms`, `interval_s`,
  `warmup_s`, `min_workers`, `max_workers`,
  `min_timeout_s`, `max_timeout_s`. Cross-field validation
  enforces `min_workers ≤ max_workers` and
  `min_timeout_s ≤ max_timeout_s`.

### Changed

- **`CmisUploader._timeout_s` is now mutable** so the auto-tune
  controller can adjust the upload timeout. `CmisConfig` stays
  frozen — the per-instance override happens in the uploader.
- **Thread-safety on the hot path**: `MetricsRecorder._StageBucket`
  and `SlowOpAggregator._candidates` now hold a `threading.Lock`;
  `SQLiteTrackingStore` opens with `check_same_thread=False` and
  serializes reads through `_reader_lock`. `CmisUploader` gains
  `_folder_lock` + `_warm_lock` so concurrent workers can't
  double-warm or double-mkfolder.
- **Circular import broken**: `cmcourier/config/__init__.py` now
  resolves `build_pipeline` via a lazy `__getattr__` so
  `orchestrators.staged` can import the observability stack
  without re-entering config wiring.

### Tests

- 12 new unit tests for `WorkerPoolStats` + `ResizableSemaphore`.
- 10 new unit tests for the AIMD `decide()` function +
  `AutoTuneController`.
- 25 new TUI tests (chart sparkline, data provider, both tabs).
- 7 new integration tests for the S5 worker pool end-to-end.
- 4 new CLI tests for `--tui` / `--no-tui` semantics including
  the explicit-tui-in-non-TTY → exit 2 branch.
- 655 tests total green, mypy clean, ruff clean.

### Notes

- Slow / fast S5 lanes remain explicitly post-MVP per
  REBIRTH §10.7 — they aren't in 025 by design. The current
  pool is a single resizable pool sized by `cmis.workers`.
- The bandwidth chart uses the operator-configured
  `cmis.max_bandwidth_mbps` rather than an autodetected
  interface speed. Honest and fragile-detection-free.

---

## [0.26.0] — 2026-05-10 — **background runner (REBIRTH §11)**

Cron-friendly entry point for unattended pipeline execution.
Closes the last operationally-meaningful gap from REBIRTH §11
ahead of the real dry run.

### Added

- **`cmcourier background --pipeline <kind>`** — single
  dispatcher for unattended execution. Accepts the four
  production pipelines (`csv-trigger`, `rvabrep`,
  `as400-trigger`, `local-scan`); `single-doc` is intentionally
  rejected by Click's `Choice` (it's an ad-hoc tool, not a
  cron use case).
- **Per-config exclusive lock** via
  `cmcourier.cli.commands._lock.acquire_config_lock`. Lock file
  lives at `${XDG_RUNTIME_DIR:-/tmp}/cmcourier/<sha256(config_path)[:12]>.lock`.
  `fcntl.flock(fd, LOCK_EX | LOCK_NB)` — non-blocking. Second
  invocation on the same config exits **75** (`os.EX_TEMPFAIL`,
  cron-conventional "transient, retry later") and emits a
  WARNING `background_lock_held` log line.
- **`LockHeldError` exception** — raised by
  `acquire_config_lock` on contention. Carries the lock path
  for diagnostics. Released by the kernel on process exit
  including `SIGKILL` (fd-close semantics).
- **Quiet-on-success output**. The background runner suppresses
  the `_emit_summary` stdout line on success — only the
  structured observability tiers record the run. Cron stays
  silent on green; the operator's mailer only fires when
  something is wrong.
- **Failure stderr summary**. On `report.s5_failed > 0`,
  emits a single line:
  `pipeline=<kind> batch_id=<id> s5_failed=<n> exit_code=1`.
  Cron forwards this to the operator.
- **`--log-level WARNING` default** (interactive runs default
  to `INFO`). Same WARNING threshold as the rest of cron-aware
  Unix tooling.
- **5 background integration tests** + **9 unit tests** for
  the lock module:
  - Lock unit tests cover: roundtrip release, contention
    raises, deterministic path, XDG / /tmp fallback, PID +
    timestamp content, low-level fcntl semantics.
  - Background CLI tests cover: help lists flags, unknown
    pipeline rejected, quiet success, lock contention exits
    75, lock released after run.

### Changed

- **`_run_pipeline_command` in `cli/app.py`** gains a
  keyword-only `quiet: bool = False`. The interactive
  pipelines pass `quiet=False` by default (unchanged
  behavior); `background_command` passes `quiet=True`.
- **`_apply_resume`** gains `quiet: bool = False` for
  symmetry: when set, the "Nothing to resume" stdout echo is
  suppressed (still exits 0).
- **`cli/app.py`** registers the new `background_command` via
  `main.add_command(background_command)` next to the other
  top-level commands.

### Verification

- `pytest --cov`: **587 / 587 pass** in ~100 s (+14 net new).
- Coverage: total **94 %**;
  `cli/commands/_lock.py` at **100 %**,
  `cli/commands/background.py` at **100 %**.
- `ruff check` / `ruff format --check`: clean.
- `mypy src/cmcourier`: clean (50 source files).
- `pre-commit run --all-files`: ruff + ruff format + mypy all
  pass.
- Smoke: `cmcourier --help` lists `background` next to the
  existing 9 commands. `cmcourier background --help` lists
  every flag.

### Rationale

Until 024, the only way to schedule a CMCourier pipeline run
was to call `csv-trigger-pipeline run` (or one of its
siblings) from cron. That worked but leaked two problems:

1. **No instance lock.** Two overlapping cron runs would race
   on the tracking store. SQLite WAL keeps rows correct but
   the batch lifecycle (`start_batch` / `mark_stage_*` /
   `complete_batch`) interleaves badly enough to corrupt
   per-stage counts. The kernel-enforced flock guarantees
   only one runner per config at a time. Second runner exits
   immediately with `EX_TEMPFAIL` (75) — cron's
   `MAILTO=...` doesn't fire (success), cron's retry
   semantics resume on the next tick.
2. **Stdout chatter on success.** Cron emails on any
   stdout/stderr output by default. The interactive command
   prints a one-line `s5_done=N` summary on every successful
   run. With a daily cron that's a spam email a day. The
   structured logs (app log + metrics + slow-ops) already
   capture everything an operator needs — terminal output
   adds zero value to unattended runs.

**Architectural decisions:**

1. *fcntl over PID files.* PID files are operator-overrideable
   (`echo 0 > /var/run/cmcourier.pid`) and leak on SIGKILL.
   `fcntl.flock` is kernel-enforced and released
   automatically when the fd closes — including on `SIGKILL`.
   The lock file does store the PID + ISO timestamp for
   debugging, but operators MUST NOT use it for process
   control (the flock is authoritative).
2. *Per-config locks, not per-host.* Two configs targeting
   the same tracking store would still collide; that's an
   operator misconfiguration, not a runner bug. Lock keyed
   on `sha256(config_path.resolve())[:12]` means two
   invocations on the same config file collide
   deterministically.
3. *Reuse over reinvention.* `background_command` doesn't
   reimplement pipeline orchestration — it acquires the
   lock, then dispatches into `_run_pipeline_command` (the
   same helper the interactive commands use), with
   `quiet=True`. Auto-doctor + `--resume` work identically.
4. *Single-doc not supported.* `single-doc` requires
   `--shortname`/`--system`/`--cif` per invocation — that's
   ad-hoc, not scheduled. Click's `Choice` rejects it
   explicitly so operators don't accidentally schedule one.
5. *`os.EX_TEMPFAIL` not custom code.* The sysexits.h
   convention (75 = "transient failure, retry later") is
   what cron and systemd-timer + supervisor tools expect.
   Using the documented constant means no operator surprise.

---

## [0.25.0] — 2026-05-10 — **complete REBIRTH §11 menus**

Closes the §11 menus with three small commands. After this
change the only §11 entries still missing are the `background`
runner and the TUI — both depend on a TUI design that's a
separate change. Operators now have the full read-only triage +
offline-analysis surface.

### Added

- **`cmcourier inspect trigger [--source <descriptor>] [--limit N]`**
  — preview the first N triggers a source would emit. When
  `--source` is omitted, builds the strategy from
  `config.trigger` via the existing wiring helper. When
  `--source csv:<path>` is given, builds a one-off
  `CsvTriggerStrategy` over the path. When
  `--source single_doc:<short>,<sys>[,<cif>]` is given,
  builds a one-off `SingleDocTriggerStrategy`. Other schemes
  (`rvabrep`, `as400`, `local_scan`) require richer config —
  the command rejects with a clear hint pointing operators
  at the YAML.
- **`cmcourier inspect mapping-stats`** — structured summary of
  the Modelo Documental:
  - `Total mappings: <n>`
  - `Distinct document classes: <n>`
  - `Mappings with ID Corto: <n> / <total>`
  - `Distinct CM object types: <n>`
  - `Distinct CM folders: <n>`
  - Top-5 classes by mapping count (tie-break alphabetical).
- **`cmcourier batch export-report --batch <id> --format csv|json
  [--output <path>]`** — dump a batch's full state for offline
  analysis. CSV emits a flat S0..S5 table with batch metadata
  repeated on every row; JSON emits the full `BatchDetails`
  payload (stage_counts + failed_records nested). Default
  writes to stdout; `--output` writes a file plus a
  confirmation line.
- **`cmcourier.cli.commands._source_descriptor`** — new helper
  module owning the `csv:<path>` / `single_doc:<...>` parser.
  Pure function + frozen dataclass. Unit tested independently
  of Click.
- **18 new tests** across:
  - `tests/unit/cli/commands/test_source_descriptor.py` (10
    tests: scheme parsing + rejection paths).
  - `tests/integration/cli/test_inspect.py` (7 trigger + 3
    mapping-stats tests).
  - `tests/integration/cli/test_batch.py` (5 export-report
    tests).

### Changed

- **`cli/commands/inspect.py`** grew from 2 commands to 4
  (rvabrep, mapping, trigger, mapping-stats). Module size
  ~290 LOC.
- **`cli/commands/batch.py`** grew from 3 commands to 4
  (list, show, retry-failed, export-report). Module size ~290
  LOC.
- **`inspect trigger` "permissive secrets" path**: when
  building a strategy from `config.trigger`, CMIS env vars
  aren't required (only AS400 trigger kinds need
  `AS400_USERNAME` / `AS400_PASSWORD`). The fallback to an
  empty `Secrets` bundle lets csv-trigger / single-doc configs
  work without exporting CMIS creds — a real ergonomics win
  for read-only inspection.

### Verification

- `pytest --cov`: **573 / 573 pass** in ~96 s (+25 net new
  across the change cycle).
- Coverage: total **94 %**;
  `cli/commands/_source_descriptor.py` at **95 %**,
  `cli/commands/batch.py` at **96 %**,
  `cli/commands/inspect.py` at **92 %**.
- `ruff check` / `ruff format --check`: clean.
- `mypy src/cmcourier`: clean (48 source files).
- `pre-commit run --all-files`: ruff + ruff format + mypy all
  pass.
- Smoke: `cmcourier inspect --help` lists `trigger`,
  `rvabrep`, `mapping`, `mapping-stats`. `cmcourier batch
  --help` lists `list`, `show`, `retry-failed`,
  `export-report`.

### Rationale

Before 023 an operator who wanted to know "what would the
trigger source emit?" had to spin up a tiny pipeline run.
"How many CM classes does the Modelo Documental have?" meant
opening Excel. "Send me this batch's report" meant taking a
screenshot of the terminal. Three small commands close all
three gaps — none of them need new ports or schema changes.

**Architectural decisions worth flagging:**

1. *Reuse, don't fork.* `inspect trigger` without `--source`
   reuses the wiring's `_build_trigger_strategy`. `inspect
   mapping-stats` reuses `MappingService.get_all()` /
   `count()`. `batch export-report` reuses `get_batch_details`
   from 021. No service was modified; only new CLI surfaces.
2. *Descriptor parser in its own module.* Click subcommands
   call a pure function; the function is unit-testable
   without spinning up a CLI runner. Future schemes (when
   they're worth supporting via CLI args) land here.
3. *CSV stays flat; JSON nests.* `batch export-report`'s two
   formats serve two audiences. CSV is for Excel /
   spreadsheet workflows that hate nested data. JSON is for
   tooling that wants the full structured payload. No
   `--include-failed-records` flag — the format chooses for
   you.
4. *Inspect commands don't auto-doctor.* Unlike pipeline run
   commands (022), inspect commands are read-only and offline
   (they don't touch CMIS). Running doctor would just waste
   the operator's time during triage.
5. *`_strategy_from_config` falls back to empty secrets.*
   Inspect is read-only. CMIS isn't touched. If the operator
   hasn't exported CMIS env vars, that's fine for inspect.
   The full pipeline-run path keeps the strict secrets check
   it always had.

---

## [0.24.0] — 2026-05-10 — **pipeline safety flags (REBIRTH §11)**

Closes the pre-dry-run safety polish: pipelines auto-run doctor
before doing work, `--resume` infers the right `--from-stage`
from tracking state, and `doctor --check <group>` lets the
operator run a single check during triage.

### Added

- **Auto-doctor before every pipeline run.** Every
  `*-pipeline run` command (csv-trigger, rvabrep,
  as400-trigger, local-scan) plus `single-doc run` now calls
  `run_doctor(config, secrets)` after config + observability
  setup and before constructing the pipeline. FAIL → exit 2
  with the doctor report printed. PASS/WARN → proceeds.
- **`--skip-doctor` flag on every pipeline run command.**
  Bypasses the auto-doctor for dev iteration or trusted configs.
  When passed, no doctor output appears.
- **`--resume` flag on every pipeline run command.** Requires
  `--batch-id`. Queries the tracking store via
  `get_batch_details(batch_id)` (shipped in 021), inspects
  `stage_counts`, finds the lowest stage with
  `FAILED + PENDING > 0`, and uses that as `--from-stage`.
  Behaviors:
  - `--resume` without `--batch-id` → exit 2.
  - `--resume <unknown id>` → exit 1 with "Batch not found".
  - `--resume <clean batch>` → exit 0 with "Nothing to resume".
  - `--resume <mid-flight>` → resolves and runs; emits a
    `resume_resolved` event with the inferred stage.
  - `--resume` AND `--from-stage <non-default>` → `--from-stage`
    wins; WARNING log surfaces the override.
- **`doctor --check <name>` selective filter** with values
  `connections | mapping | metadata | cm-types | all`
  (default `all`). Group mapping:
  - `connections` → `log_dir_writable`, `cmis_connectivity`,
    `as400_connectivity`, `tracking_openable`
  - `mapping` → `mapping_completeness`
  - `metadata` → `metadata_sources`, `sample_dry_run`
  - `cm-types` → `cm_type_alignment`
  - `all` → every check (current behavior — regression)
  Auto-doctor (called from pipeline commands) always uses
  `selected="all"`; the filter only applies to standalone
  `cmcourier doctor` invocations.
- **`_run_auto_doctor` and `_apply_resume` helpers** in
  `cli/app.py` keep the per-command bodies thin (the heavy
  lifting lives in named helpers, the commands just dispatch).
- **`_CHECK_GROUPS` + `_selected` helper** in `cli/doctor.py`
  gate each `results.append(...)` line on group membership.
  `cm_type_alignment` SKIP fallback preserved when
  `cmis_connectivity` was run and FAILed within the same
  invocation.
- **14 new integration tests**:
  - 3 in `test_cli.py::TestAutoDoctor` — auto-doctor PASS,
    FAIL blocks pipeline, `--skip-doctor` bypasses.
  - 4 in `test_pipeline_kinds.py::TestResumeFlag` — missing
    batch id, unknown batch, clean batch, mid-flight resume.
  - 7 in `test_doctor.py::TestDoctorCheckFilter` — each
    group filter + `all` regression + CLI help + invalid
    value rejection.

### Changed

- **Every pipeline run command signature** gains `--skip-doctor`
  and `--resume` flags. `_run_pipeline_command` central helper
  picks them up. `single_doc_run_command` (the only outlier)
  applies the same logic inline.
- **`run_doctor`** signature extends with a keyword-only
  `selected: str = "all"`. Backwards-compatible: every existing
  call uses the default.
- **Existing CLI tests** were updated to pass `--skip-doctor`
  on every `*-pipeline run` invocation that doesn't specifically
  test the auto-doctor path. This preserves their original
  intent (exercise pipeline behavior, not doctor scaffolding).
  Scope: ~14 invocations across `test_cli.py`,
  `test_pipeline_kinds.py`, `test_pipeline_emits.py`.

### Verification

- `pytest --cov`: **548 / 548 pass** in ~101 s (+14 net new).
- Coverage: total **94 %**; `cli/app.py` at **89 %**,
  `cli/doctor.py` at **88 %**.
- `ruff check` / `ruff format --check`: clean.
- `mypy src/cmcourier`: clean (47 source files).
- `pre-commit run --all-files`: ruff + ruff format + mypy all
  pass.

### Rationale

Before 022 the operator could forget to run `doctor` before a
pipeline and only discover a broken CMIS auth 30 s into a run —
exactly when feedback hurts most. After 022 it's the other way
around: every pipeline run starts with a 5–10 s pre-flight and
either proceeds confidently or fails loud and early. The
`--skip-doctor` flag preserves the dev-iteration ergonomics:
when you trust your config and want fast feedback, opt out.

`--resume` solves the operator-math problem. Today's resume
flow requires `cmcourier batch show <id>` to find the lowest
stage with pending/failed work, then mental-math the
`--from-stage <n>` to pass back to the pipeline command. With
`--resume`, the tooling does the math: query → infer → run.
Edge cases (no batch_id, unknown batch, clean batch) all exit
cleanly with operator-readable messages. Explicit `--from-stage`
still wins — `--resume` is sugar, never a constraint.

`doctor --check <group>` is the triage shortcut. When the
operator already knows CMIS is fine but suspects Modelo
Documental, running the full 7-check suite (~10 s) just to
confirm wastes seconds. The group names come straight from
REBIRTH §11; the internal check names map cleanly onto them.

**Key architectural decisions:**

1. *Auto-doctor uses the FULL check set.* Even though the
   doctor command now supports group selection, the
   pre-pipeline auto-doctor always runs everything. Selective
   checks are an *operator triage tool*, not a way to bypass
   safety during a real run.
2. *Explicit beats implicit.* Whenever the user gave both
   `--resume` and `--from-stage`, the explicit number wins.
   A WARNING log line surfaces the override so the operator
   knows their `--from-stage` overrode the inferred value.
3. *No port additions, no schema changes.* Everything lives
   in `cli/app.py` and `cli/doctor.py`. The port method that
   `--resume` consumes (`get_batch_details`) shipped in 021;
   this change just wires it through a new CLI surface.
4. *Test-suite hygiene.* Adding `--skip-doctor` to ~14
   existing tests instead of stubbing every doctor check is
   the right tradeoff: those tests are about pipeline
   behavior, not pre-flight validation. The new
   `TestAutoDoctor` class explicitly exercises the
   pre-flight path.

---

## [0.23.0] — 2026-05-10 — **operator CLI essentials (REBIRTH §11)**

Adds the six commands an operator needs between pipeline runs:
batch lifecycle (list/show/retry-failed), preview commands (inspect
rvabrep/mapping), and a raw AS400 query escape hatch. Pure
additions on top of the existing pipelines + doctor + single-doc.
No CLI surface that previously worked has changed.

### Added

- **`cmcourier batch list [--status in_progress|completed]`** —
  enumerate batches with status + counts, newest first.
- **`cmcourier batch show <batch_id>`** — per-stage counts
  (S0..S5 × DONE/FAILED/PENDING) + failed records with their
  error messages.
- **`cmcourier batch retry-failed --batch <id> [--stage Sn]`** —
  reset `*_FAILED` rows in `migration_log` back to `*_PENDING`
  so the next pipeline run picks them up. Idempotent; reports
  count reset.
- **`cmcourier inspect rvabrep <shortname> <system_id>`** — print
  the RVABREP rows S1 would produce for one trigger. Reads
  through `IndexingService` to mirror real pipeline behavior.
- **`cmcourier inspect mapping <id_rvi>`** — print the CM mapping
  (folder + object type + required metadata fields) for one ID
  RVI from the Modelo Documental.
- **`cmcourier as400-query "<SQL>"`** — raw SQL against the AS400
  configured in YAML (preferring `trigger.as400_connection`,
  falling back to first `metadata.sources[*]` of kind `as400`).
  Result cells truncated to 80 chars per column. Debug-only.
- **3 new ITrackingStore port methods**: `list_batches`,
  `get_batch_details`, `retry_failed`. Implemented in
  `SQLiteTrackingStore` via the existing reader connection
  (writes use REPLACE on the status column for safety).
- **3 new domain dataclasses**: `BatchInfo` (with derived
  `status` property), `FailedRecord`, `BatchDetails` (with
  predictable `S0..S5 × DONE/FAILED/PENDING` shape).
- **`cmcourier.cli.commands` subpackage** — new home for the
  expanding CLI surface so `cli/app.py` stays a registry, not
  a kitchen sink.
- **23 new tests**: SQLite store (4 list/3 details/4 retry),
  batch CLI (3 × 4), inspect CLI (3 + 3), as400-query CLI (4).

### Changed

- **`cli/app.py`** registers the new groups + standalone command
  via `main.add_command(...)`. No change to existing pipeline
  commands.
- **`ITrackingStore`** gains 3 abstract methods. Only
  `SQLiteTrackingStore` implements the port in production; the
  `__abstractmethods__` test in `tests/unit/domain/test_ports.py`
  was extended to reflect the new contract.

### Verification

- `pytest --cov`: **534 / 534 pass** in ~91 s (+32 net new across
  the change cycle).
- Coverage: total **94.21 %**; `cli/commands/batch.py` at **96 %**,
  `inspect.py` at **95 %**, `as400_query.py` at **79 %** (error
  branches not exercised in tests; targeted by the doctor
  smoke), `_formatting.py` at **68 %** (edge cases like empty
  headers).
- `ruff check` / `ruff format --check`: clean.
- `mypy src/cmcourier`: clean (47 source files).
- `pre-commit run --all-files`: ruff + ruff format + mypy all
  pass.
- Smoke: `cmcourier --help` lists 9 commands (was 6).
  `cmcourier batch list --help`, `cmcourier inspect rvabrep
  --help`, `cmcourier as400-query --help` all render correctly.

### Rationale

Before 021 an operator who wanted to know "which batch failed and
why?" had to open SQLite manually. "Retry the failed S5 uploads?"
meant writing UPDATEs by hand. "What does S1 think of this
trigger?" required spinning up Python. These three workflows are
the daily bread of any migration in flight; making them ergonomic
is the difference between a dry run that uncovers issues and a
dry run that gets bogged down in tooling.

**Architectural decisions worth flagging:**

1. *Port extension, not direct SQLite from CLI*. Constitution I
   says adapters are behind ports. The temptation was strong to
   read SQLite directly from `batch list` for speed — resisted.
   Three new methods on `ITrackingStore`, three new SQLite
   implementations, and the CLI talks to the port. If a future
   AS400-backed tracking store lands, every operator command
   keeps working.

2. *`REPLACE(status, '_FAILED', '_PENDING')` for retry*. Safe
   because the only `_FAILED` substring in any `StageStatus`
   value is the suffix. A regression test pins this invariant.
   The alternative (parse + reassemble in Python before UPDATE)
   was strictly more code for no benefit.

3. *Predictable `stage_counts` shape*. The pivot helper always
   emits all six stages × three outcomes, even when zero. The
   CLI rendering is dumb because the data is consistent;
   adding a stage in the future is one-line change.

4. *`cli/commands/` subpackage*. Each new command family gets
   its own module. The directory was empty since project
   bootstrap — 021 finally uses it.

5. *Per-command observability*. Every new command calls
   `configure_observability(config.observability, "INFO")`
   after `load_config`. Batch ops, inspect previews, and
   raw queries all leave audit trails in `app-{date}.log`.

6. *`as400-query` warns about PII*. The command emits a WARNING
   to the observability log noting that raw cells may contain
   PII. Operators are responsible for what they query; the log
   captures the SQL prefix (≤80 chars) for after-the-fact
   review.

---

## [0.22.0] — 2026-05-10 — **observability tiers 1-4 (REBIRTH §17.4)**

Full-MVP observability surface. Operators now get structured JSON
logs, per-batch pipeline timing percentiles (p50/p95/p99), per-request
network latency for AS400 + CMIS, and a top-N slow-ops report — all
toggleable from YAML, all PII-masked by a central filter, all
parseable by `jq` or any log shipper. The dry run is no longer blind.

### Added

- **New package `src/cmcourier/observability/`** — peer to
  adapters/services. Modules: `formatter.py` (JsonFormatter),
  `pii.py` (PiiMaskingFilter + denylist), `metrics.py`
  (StageTimer, BatchSummary, MetricsRecorder, SlowOpAggregator,
  NetworkEvent), `setup.py` (`configure(config, log_level)`).
- **`ObservabilityConfig`** in `config/schema.py` with REBIRTH
  §17.4 fields: `enabled`, `pipeline_metrics`, `network_metrics`,
  `system_metrics`, `log_dir`, `log_format`, `rotation_mb`,
  `retention_days`, `slow_op_threshold_ms`, `slow_op_top_n`.
  `system_metrics=true` raises ValidationError — deferred to
  POST-MVP §2. `PipelineConfig.observability` defaults to a
  sane block so existing YAMLs keep validating.
- **Tier 1 — application log** (`logs/app-{date}.log`): JSON
  Lines, every record from the `cmcourier` logger hierarchy.
  `RotatingFileHandler` with configurable `rotation_mb` cap +
  5 backups. Always on when `enabled=True`.
- **Tier 2 — pipeline metrics** (`logs/metrics-{date}.jsonl`):
  one batch-summary line per pipeline run with
  `{pipeline, batch_id, total_docs, elapsed_s,
  throughput_docs_per_s, stages.{S0..S5}.{count, p50_ms, p95_ms,
  p99_ms, sum_ms}}`. Toggle via `pipeline_metrics`.
- **Tier 3 — network metrics** (`logs/network-{date}.jsonl`):
  per AS400 query + per CMIS HTTP request, with `kind`
  (`as400_query` / `cmis_upload` / `cmis_post` / `cmis_get`),
  `duration_ms`, plus shape-specific fields (`sql_prefix`,
  `row_count`, `size_bytes`, `status`, `url_prefix`). Toggle via
  `network_metrics`.
- **Tier 4 — slow-ops report** (`logs/slow-ops-{batch_id}.jsonl`):
  top-N slowest operations per batch, ranked descending,
  thresholded by `slow_op_threshold_ms`. Collected in-memory by
  a custom `_SlowOpHandler` attached to `cmcourier` +
  `cmcourier.metrics.network` at `start_batch`; flushed to disk
  at `close_batch`.
- **PII masking** via `PiiMaskingFilter` installed on every
  handler. Denylist: `cif`, `customer_name`, `account_number`,
  `nombre`, `phone`, `email`, `address`, `dni`; plus prefix
  `pii_*`. Values replaced with `***`. Constitution Principle
  VIII enforced at the formatter layer — callers pass PII via
  `extra={...}` and the filter catches it before any handler
  formats the record.
- **`StagedPipeline` instrumentation**: per-doc `stage_complete`
  events (S0..S5) emitted to the `cmcourier` logger at INFO
  with `extra={pipeline, stage, batch_id, txn_num, outcome,
  duration_ms}`. Aggregation flows into the per-batch summary.
- **Adapter instrumentation**: `As400DataSource.query` /
  `query_stream` emit AS400 network events. `CmisUploader`
  emits network events for warmup (GET), type-definition (GET),
  folder create (POST), and document upload (POST). 1-2 lines
  per request path; if `network_metrics=false`, the dedicated
  logger is silenced (level above CRITICAL) — emission cost is
  one level check.
- **Doctor check `log_dir_writable`**: probes
  `observability.log_dir` for create + write before the rest of
  the pre-flight runs. FAIL surfaces unwritable paths with a
  clear `OSError` detail. Runs first because if logging is
  broken, every other check's output is invisible.
- **`observability.setup.configure(config, log_level)`** — the
  primary entry point. Idempotent: removes existing handlers,
  resets propagation and levels, installs fresh. CLI entry
  points call this after `load_config()`. The legacy
  `cli/logging_setup.configure(level)` shim stays for pre-config
  paths (e.g., doctor's early failure path).
- **15 net new tests** across 4 files (`test_formatter.py`,
  `test_metrics.py`, `test_pipeline_emits.py`, doctor + schema
  additions). E2E asserts the four files materialize on disk
  with the expected JSON shape; PII regression confirms no CIF
  value reaches any handler output.

### Changed

- **`cmcourier/cli/logging_setup.py`** is now a 4-line shim that
  delegates to `observability.setup.configure(stderr_only=True)`.
  Backwards-compatible signature.
- **`cmcourier/cli/app.py`** calls
  `observability.setup.configure(config.observability, log_level)`
  after parsing in every entry point (run + doctor + single-doc).
- **`cmcourier/orchestrators/staged.py`** accepts optional
  `metrics_recorder` and `pipeline_name`. Per-stage work
  wrapped in `with StageTimer(...): ...`. `mark_failed()` on
  caught exception paths so the recorded outcome reflects
  reality. Batch lifecycle wraps `recorder.start_batch(...)` →
  stages → `recorder.close_batch(...)`.
- **`cmcourier/config/wiring.py`** builds a `MetricsRecorder`
  from `config.observability` and threads it into
  `StagedPipeline`. New `pipeline_name` kwarg defaults to
  `csv-trigger`.
- **`cmcourier/adapters/sources/as400.py`** times each
  `query`/`query_stream` call (including stream completion) and
  emits a network event.
- **`cmcourier/adapters/upload/cmis_uploader.py`** times the
  warmup, type-definition, and retry-loop POST paths. A new
  `_emit_network` helper centralizes the structured logging
  call.

### Verification

- `pytest --cov`: **502 / 502 pass** in ~65 s (+35 net new across
  the change cycle; the headline target was ≥15 new tests for
  observability itself).
- Coverage: total **94.92 %**; `observability/__init__.py` at
  **100 %**, `formatter.py` at **100 %**, `pii.py` at **100 %**,
  `setup.py` at **98 %**, `metrics.py` at **96 %**.
- `ruff check` / `ruff format --check`: clean.
- `mypy src/cmcourier`: clean (43 source files).
- `pre-commit run --all-files`: ruff + ruff format + mypy all
  pass.

### Rationale

The MVP was running on a single stderr text handler — fine for
unit-test feedback, blind for a real dry run. REBIRTH §17.4
specified the multi-tier surface; 020 ships the four cheap tiers
and explicitly defers the expensive one (`psutil` sampling).
With these tiers an operator can answer the questions that
matter during a real migration:

* "Why was this batch slow?" → `metrics-{date}.jsonl` shows
  which stage dominated. p95 vs p50 reveals tail latency.
* "Which document took the longest?" →
  `slow-ops-{batch_id}.jsonl` ranks top-N.
* "Is the upload network bound?" →
  `network-{date}.jsonl` per-request timings make this trivial
  to chart.
* "Did the pipeline really finish stage S2 for all docs?" →
  `app-{date}.log` has per-doc `stage_complete` events.

**Key architectural decisions** worth remembering:

1. *Logger-name routing*. Each tier has a named logger
   (`cmcourier.metrics.pipeline`, `.network`, `.slow_ops`). The
   handler/formatter/filter wiring lives in `setup.py`. Caller
   code uses normal `logger.info(...)` with `extra={...}` —
   blissfully unaware of where the bytes go.
2. *Slow-ops via handler interception*. A custom
   `_SlowOpHandler` is attached at `start_batch` to `cmcourier`
   + `cmcourier.metrics.network`. Any record with `duration_ms`
   above threshold becomes a candidate. No constructor changes
   to adapters — they just emit, the handler catches.
3. *PII at the formatter boundary*. The denylist filter mutates
   `record.__dict__` BEFORE the formatter runs. Even if a
   caller accidentally passes a CIF as `extra={"cif": "..."}`,
   the disk only sees `***`. The `name` key is intentionally
   absent from the denylist (it collides with
   `LogRecord.name` — masking it triggers an infinite
   audit-log recursion).
4. *State leak resistance*. `_reset_all_handlers` resets level
   to NOTSET and propagation to True for every monitored logger
   before installing fresh handlers. Tests share the process
   logging state; without the reset, propagate=False from one
   test would silently break caplog in the next.

---

## [0.21.0] — 2026-05-10 — **adapter port-hygiene cleanup**

Closes a Constitution Principle I (hexagonal architecture) deuda:
the last two adapters that implemented their ports structurally
(duck-typed) now declare formal inheritance. Pure declarative
cleanup — zero behavioral changes.

### Added

- **`PdfAssembler` now inherits from `IAssembler`**. The class
  declaration is `class PdfAssembler(IAssembler):`. Python's ABC
  machinery now guards against any future drift: if a required
  abstract method were ever removed, `PdfAssembler(...)` would
  raise `TypeError` at instantiation.
- **`CmisUploader` now inherits from `IUploader`**. Same guarantee:
  `ensure_folder`, `upload`, `test_connection`,
  `get_type_definition` are now formally overrides validated by
  mypy.
- **2 new conformance tests**:
  - `tests/integration/adapters/test_pdf_assembler.py::TestPortConformance::test_pdf_assembler_is_iassembler`
  - `tests/integration/adapters/test_cmis_uploader.py::TestPortConformance::test_cmis_uploader_is_iuploader`
  Each instantiates the adapter and asserts `isinstance(adapter,
  port)` returns `True`. They fail loudly if a future change
  drops the inheritance.

### Changed

- **Adapter import blocks**: `pdf_assembler.py` and
  `cmis_uploader.py` each gained one import line
  (`from cmcourier.domain.ports import IAssembler` /
  `IUploader`). No other source edits.
- **`__mro__`**: `PdfAssembler.__mro__` now contains `IAssembler`;
  `CmisUploader.__mro__` now contains `IUploader`. This is the
  observable runtime side of the change — `isinstance` checks
  work, registries that filter by port type work, doctor /
  diagnostic code can rely on it.

### Verification

- `pytest --cov`: **467 / 467 pass** in ~69 s (+2 net new).
- Coverage: total **94.79 %** (unchanged);
  `adapters/assembly/pdf_assembler.py` at **98 %**;
  `adapters/upload/cmis_uploader.py` at **94 %**.
- `ruff check` / `ruff format --check`: clean.
- `mypy src/cmcourier`: clean (38 source files). Validated the
  override signatures match the port abstract methods. No new
  errors surfaced — signatures were already aligned, the
  declaration just made the alignment formal.
- `pre-commit run --all-files`: ruff + ruff format + mypy all
  pass.

### Rationale

Constitution Principle I demands a strict port/adapter split. The
project had been 60 % consistent (`TabularDataSource`,
`As400DataSource`, `SQLiteTrackingStore`, and all 5 S0 strategies
already inherited their ports). The two outliers were the
assembler and uploader — both worked because Python uses duck
typing at runtime, but neither was guarded against signature drift
and neither passed `isinstance(adapter, port)` checks.

This change closes the gap with minimal surface area: 2 imports,
2 class declarations, 2 tests. mypy now validates every override,
and Python's ABC instantiation check guards against missing
methods. A future port-signature change (e.g., adding a parameter)
will now surface at the adapter override instead of at the call
site — a much earlier and more actionable failure point.

The change is also a pedagogical artifact for new contributors:
the ports/adapters split is no longer "mostly enforced, sometimes
implicit" — every adapter says, at the top of its class
declaration, which port it implements.

---

## [0.20.0] — 2026-05-10 — **per-source AS400 query override**

Closes the production-data scale gap left by 015. AS400 metadata
sources can now use a custom `SELECT ...` query (with filtering and
column projection) instead of `SELECT * FROM <table>`. The
MetadataService prefetch is untouched — the adapter wraps the
query in a derived-table alias so the full `IDataSource` contract
(`get_all`, `count`, `get_by_fields*`) keeps working transparently.

### Added

- **`As400MetadataSourceConfig.query: str | None`** — new optional
  field. Operators specify a complete `SELECT ...` statement scoped
  to the data the migration actually needs (e.g.,
  `SELECT CIF, NAME FROM CUSTOMERS WHERE ACTIVE = 'Y'`). Pydantic's
  `min_length=1` rejects empty strings.
- **`As400MetadataSourceConfig.table: str | None`** — now optional.
  An `@model_validator(mode="after")` enforces exactly-one of
  `table` / `query`. Both-set and neither-set both raise
  `ValidationError` at load time.
- **`As400DataSource` constructor accepts `query: str | None`** —
  new keyword-only argument. Mutually exclusive with `table`. The
  adapter computes `self._source_expr = f"({query}) AS T" if query
  else table` and uses that expression in every generated SQL
  template.
- **Derived-table alias (`AS T`)** wraps the operator query
  whenever it's used as a `FROM` source. DB2/AS400 requires the
  alias; using a single-letter `T` keeps generated SQL minimal.
- **3 new schema tests**: query mode loads correctly, both-set
  rejected with "exactly one" message, neither-set rejected.
- **7 new adapter tests**: construction validation
  (both/query-only/neither), and query-mode SQL templates for
  `get_all` (subquery alias), `count`, `get_by_fields`, plus a
  table-mode regression test asserting no subquery wrapping when
  `table` is used.
- **1 new wiring integration test**: query-mode YAML builds a
  pipeline whose metadata registry contains an `As400DataSource`
  with the expected `_source_expr`.

### Changed

- **`As400DataSource._table` attribute renamed to `_source_expr`**.
  The new name reflects that the value may be either a bare table
  identifier (table mode) or a parenthesized derived-table
  expression (query mode). All internal SQL templates updated.
- **`As400DataSource.__init__` signature**: `table` now defaults to
  `""` (was required). Backwards-compat preserved — all existing
  call sites pass `table=...` explicitly.
- **Constructor rejects (both `table` AND `query` set)** with
  `ConfigurationError` at the adapter boundary. Schema validation
  catches the same case earlier, but the adapter check enforces the
  invariant at every call site (defense in depth).
- **`_build_metadata_sources` in `config/wiring.py`** and the
  doctor's `_open_metadata_source` helper pass `query=src_cfg.query`
  through to the adapter. Falsy `table` defaults to `""`.

### Verification

- `pytest --cov`: **465 / 465 pass** in ~70 s (+11 net new: 7
  adapter, 3 schema, 1 wiring).
- Coverage: total **94.79 %**; `adapters/sources/as400.py` at **88
  %** (unchanged from 015).
- `ruff check` / `ruff format --check`: clean.
- `mypy src/cmcourier`: clean (38 source files). Caught a real
  callsite (`doctor.py`) where `table: str | None` had to be
  coerced — fixed by passing `source_cfg.table or ""`.
- `pre-commit run --all-files`: ruff + ruff format + mypy all
  pass.
- Smoke: YAML loader parses
  `metadata.sources[].query` correctly, `table` becomes `None`
  when absent.

### Rationale

015 enabled AS400 metadata sources but only supported `SELECT *
FROM <table>`. Production AS400 tables can have millions of rows
and dozens of columns the migration never touches. Without query
filtering, operators were forced to pre-stage the data into CSVs —
defeating the value of native AS400 sources. 018 closes this gap
without changing the prefetch model (1 source = 1 cached dataset);
the operator simply scopes the query.

The "per-field" framing in earlier roadmap notes was a misnomer.
Per-field query overrides would break the shared-prefetch model
(each field would need its own dataset). 018 settles on
**per-source** — one query feeds one alias, which many fields can
reference. This is consistent with the 015 source-registry
architecture and keeps Constitution I (hexagonal architecture)
intact.

The derived-table alias (`(query) AS T`) is the key invariant: it
lets the existing `IDataSource` methods (`count`,
`get_by_fields`, `get_by_fields_in`) issue `... FROM (subquery) AS
T WHERE ...` without knowing whether the source is table- or
query-backed. The MetadataService, doctor, and every other caller
sees a single polymorphic adapter.

---

## [0.19.0] — 2026-05-10 — **single-doc-pipeline (REBIRTH §10.2 diagnostic surface)**

Completes the pipeline surface: 4 production pipelines + 1 diagnostic
pipeline. Operators can now push a specific shortname/system/cif
through the full S1..S5 chain from the CLI without scanning a batch
— useful for re-pushing a single failed doc or smoke-testing a new
config against a known target.

### Added

- **`cmcourier.services.triggers.single_doc.SingleDocTriggerStrategy`**
  — minimal S0 strategy that yields exactly one `TriggerRecord` built
  from constructor args (`shortname`, `system_id`, optional `cif`).
  Empty-string `cif` is normalized to `None`. No data source; the
  trigger is carried in-process.
- **`SingleDocTriggerConfig(kind: Literal["single_doc"])`** — new
  schema member in `TriggerConfigUnion`. No extra fields — the
  trigger comes from CLI args, not YAML.
- **`cmcourier single-doc run`** — new Click sub-group + command:
  `--config <yaml> --shortname X --system Y [--cif Z]`, plus the
  standard `--batch-id`, `--from-stage`, `--batch-size`,
  `--log-level` flags. Verifies `config.trigger.kind == "single_doc"`
  and exits 2 on mismatch.
- **`build_pipeline(config, secrets, *, trigger_strategy_override=None)`**
  — keyword-only override that bypasses the schema-driven dispatch.
  The CLI uses it to inject the pre-built strategy; the
  `_build_trigger_strategy` branch for `SingleDocTriggerConfig`
  raises `ConfigurationError` so non-CLI callers fail loudly.
- **Doctor SKIP branch**: `_check_sample_dry_run` returns SKIP
  (`reason="trigger_kind_single_doc_requires_cli_args"`) when
  `trigger.kind == "single_doc"`. Without this, the dry-run would
  fail at construction time and confuse operators.
- **7 new unit tests** for `SingleDocTriggerStrategy` (single yield,
  cif None / empty-string / present, `S0Strategy` protocol, empty
  shortname raises, empty system_id raises, `source_descriptor`
  ignored).
- **2 new schema tests** (`kind=single_doc` loads to
  `SingleDocTriggerConfig`; extra fields rejected).
- **2 new wiring tests** (`build_pipeline` without override raises;
  with override returns a `StagedPipeline` whose
  `_trigger_strategy is` the override).
- **3 new CLI tests** (`single-doc run --help`, happy path with
  mocked CMIS, kind mismatch).
- **1 new doctor test** (sample_dry_run returns SKIP for
  `kind=single_doc`).

### Changed

- **`_TriggerKind` Literal in `cli/app.py`** extended to include
  `"single_doc"`.
- **`__all__` in `cmcourier.config.schema`** adds
  `SingleDocTriggerConfig`.
- **`__all__` and module docstring in
  `cmcourier.services.triggers.__init__`** updated to re-export
  `SingleDocTriggerStrategy` and acknowledge the 5th strategy
  (4 production + 1 diagnostic).
- **Root `--help`** now lists six command groups: 4 pipelines +
  `single-doc` + `doctor`.

### Verification

- `pytest --cov`: **454 / 454 pass** in ~65 s (+15 net new: 7
  strategy, 2 schema, 2 wiring, 3 CLI, 1 doctor).
- Coverage: total **94.73 %**;
  `services/triggers/single_doc.py` at **100 %**.
- `ruff check` / `ruff format --check`: clean.
- `mypy src/cmcourier`: clean (38 source files).
- `pre-commit run --all-files`: ruff + ruff format + mypy all pass.
- Smoke: `cmcourier --help` lists 6 commands;
  `cmcourier single-doc run --help` lists all required flags.

### Rationale

Closes the REBIRTH §10.2 pipeline catalog: four production pipelines
(csv-trigger, rvabrep, as400-trigger, local-scan) + one diagnostic
pipeline (single-doc). The override pattern keeps the schema layer
honest — `_build_trigger_strategy` still raises for any caller that
tries to wire single-doc without injecting a strategy, so the only
legitimate entry point remains the dedicated CLI command. This
preserves Constitution V (config validated at startup) while opening
a narrow, well-documented seam for CLI-driven dispatch.

---

## [0.18.0] — 2026-05-10 — **local-scan-pipeline (4th production pipeline)**

Closes the production-pipeline set. With 016, the project covers
every trigger source mode REBIRTH §5.1 commits to: csv, direct
rvabrep, as400, local_scan.

### Added

- **`cmcourier.services.triggers.local_scan.LocalScanTriggerStrategy`**
  — real implementation. Lists `scan_path` non-recursively, filters
  to `*.PDF` (case-insensitive) and `*.001` (paged-doc first page
  per REBIRTH §3.4), and for each file queries the RVABREP source
  via `get_by_fields({file_name_column: name})`. Yields one
  `TriggerRecord` per matched row. Files with no RVABREP match are
  logged at WARNING (`file_name`, `scan_path` in `extra`) and
  dropped.
- **`LocalScanTriggerConfig(kind: Literal["local_scan"], scan_path: DirectoryPath)`**
  — new schema member in the `TriggerConfigUnion` discriminated
  union. Pydantic's `DirectoryPath` validates that the path exists
  at load time.
- **`cmcourier local-scan-pipeline run --config <yaml>`** — new
  Click command. Identical surface to the other pipeline commands
  minus `--triggers` (no CSV override for local_scan). Verifies
  `config.trigger.kind == "local_scan"` and exits 2 on mismatch.
- **`RvabrepColumnsConfig.file_name_column: str = "ABAJCD"`** — new
  field on the existing dataclass. Drives the local_scan strategy's
  per-file query into RVABREP. Default matches REBIRTH §3.2
  physical name; production configs override to the friendly name.
- **10 new unit tests** for `LocalScanTriggerStrategy` covering:
  happy path, non-trigger filename filtering (`.002` / `.txt` /
  `.tmp` ignored), WARNING on unmatched file, missing `scan_path`
  raises, blank shortname dropped, case-insensitive `.PDF` match,
  empty CIF → None, empty directory yields zero triggers, S0Strategy
  protocol check, default columns config.
- **2 new schema tests** for `kind=local_scan` (loads to
  `LocalScanTriggerConfig`; rejects missing `scan_path`).
- **3 new CLI tests** (`--help`, happy path with mocked CMIS, kind
  mismatch).
- **1 new wiring test** verifying `LocalScanTriggerStrategy`
  dispatch.

### Changed

- **`cmcourier.services.triggers.stubs` module DELETED**. With
  `LocalScanTriggerStrategy` promoted, no stubs remain. The
  `__init__.py` re-export is updated.
- **`tests/unit/services/test_trigger_strategies.py::TestStubStrategies`
  removed**. The class was testing the stub's `NotImplementedError`
  behavior; the new `TestLocalScanStrategy` covers the real
  implementation.
- **`_TriggerKind` Literal in `cli/app.py`** extended to include
  `"local_scan"`.
- **`__all__` in `cmcourier.config.schema`** adds
  `LocalScanTriggerConfig`.

### Verification

- `pytest -v`: **439 / 439 pass** in ~64 s (+12 net new: 10 strategy
  + 2 schema + 3 CLI + 1 wiring − 3 obsolete stub tests).
- `pytest --cov=src/cmcourier`: total branch coverage **94.94%**.
  `services/triggers/local_scan.py` at **100%**.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean across 37 source files.
- `pre-commit run --all-files`: clean.
- Smoke: `cmcourier --help` lists **5 commands**
  (csv-trigger-pipeline, rvabrep-pipeline, as400-trigger-pipeline,
  **local-scan-pipeline**, doctor).

### Rationale

- **Closes the production-pipeline set**. REBIRTH §5.1 listed four
  trigger source modes; 016 ships the fourth. No more stubs in the
  trigger strategies module — `services/triggers/stubs.py` is
  retired entirely.
- **One trigger record per matched ROW, not per FILE**. A single
  filesystem entry might map to multiple RVABREP rows in pathological
  cases (e.g., the same filename re-archived for a different
  shortname). The downstream `IndexingService` dedupes by
  `(shortname, system_id)` already; emitting per row preserves
  information.
- **`*.PDF` + `*.001` filter is hard-coded** per REBIRTH §3.4: paged
  documents always have a `.001` first page, native PDFs end in
  `.PDF`. Custom filename patterns (e.g., `.JPG` directly archived)
  are out of scope; operators curate the folder.
- **No `cif_lookup_source` parameter**. The original stub had it as
  a hint at REBIRTH §5.1's "cif must be resolved" requirement.
  Today's metadata service handles CIF self-healing centrally
  (REBIRTH §6.5) — the strategy doesn't need its own CIF lookup.
- **Non-recursive scanning**. Recursive support is a one-line
  `Path.rglob` future change; the MVP keeps the iteration surface
  small.
- **CLI omits `--triggers` flag** because local_scan has no
  CSV-trigger override concept. Operators point at a different
  folder by editing the YAML.

---

## [0.17.0] — 2026-05-10 — **AS400 metadata sources**

Closes the gap left by 014. Pipelines with `as400:<alias>` source
types in `metadata.field_sources` now work end-to-end. The MVP is
fully production-ready: every adapter, every pipeline, every
metadata source kind.

### Added

- **`CsvMetadataSourceConfig`** + **`As400MetadataSourceConfig`** —
  two concrete schema classes that tag the `MetadataSourceConfig`
  discriminated union by `kind`. The CSV shape is unchanged in
  semantics (just gains a `kind: Literal["csv"] = "csv"` default).
  The AS400 shape carries `alias`, `as400_connection`, and `table`
  (the prefetch target — `SELECT * FROM <table>` runs at
  `MetadataService` construction).
- **`_build_metadata_sources(sources, secrets) -> dict[str, IDataSource]`**
  helper in `cmcourier.config.wiring`. Dispatches by `kind` and
  builds the right concrete data source (`TabularDataSource` for
  csv, `As400DataSource` for as400). Required AS400 credentials are
  validated at this point — missing values raise
  `ConfigurationError("AS400 credentials required for as400
  metadata source", missing_vars=[...])`.
- **Doctor `_open_metadata_source(source_cfg, secrets)`** helper.
  The existing `_check_metadata_sources` check now opens both csv
  and as400 sources via this dispatcher; the connectivity probe is
  the same `count()` call regardless of kind.
- **9 new tests** across schema, wiring, and doctor (5 schema for
  the discriminated union, 2 wiring for the kind-dispatch + missing-
  secret branch, 2 doctor for mixed-source happy paths).

### Changed

- **`_inject_default_trigger_kind` renamed to `_inject_default_kinds`**
  and extended to inject `kind: "csv"` into each `metadata.sources[i]`
  that omits it. Existing 012/013 configs continue to load
  unchanged.
- **`config.wiring._reject_unsupported_source_types` REMOVED**.
  `as400:*` source types in `field_sources` are now legitimate —
  the metadata source registry provides the backing data source,
  and `MetadataService`'s alias-validation catches dangling
  references (unchanged behavior). No prior consumer relied on the
  guard; the removal is safe.
- **`_check_metadata_sources(config, secrets)`** signature gained
  `secrets` so the AS400 branch can supply credentials when opening
  the connection. The csv branch ignores the new argument.
- **`MetadataSourceConfig`** is now a `Annotated[Csv... | As400...,
  Field(discriminator="kind")]` type alias. Existing imports
  (including `MetadataSourceConfig` directly) keep working — the
  alias preserves the name. The legacy single-class shape is now
  `CsvMetadataSourceConfig` and is re-exported under
  `__all__`.

### Verification

- `pytest -v`: **427 / 427 pass** in ~52 s (421 from earlier + 9
  net new tests across schema/wiring/doctor; 3 obsolete tests
  removed: the `_reject_unsupported_source_types`-era test in
  `test_wiring.py`).
- `pytest --cov=src/cmcourier`: total branch coverage stays above
  95%.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean across 37 source files.
- `pre-commit run --all-files`: clean.
- Smoke: `cmcourier --help` lists 4 commands (unchanged from 014);
  the new metadata-source schema is opt-in (operators add `kind:
  as400` entries when they want).

### Rationale

- **MetadataService unchanged**. The prefetch loop already iterates
  `sources_registry.values()` and calls `IDataSource.get_all()`.
  Both `TabularDataSource` and `As400DataSource` implement
  `IDataSource.get_all()`; the cache key shape
  `(alias, key_column, key_value, value_column)` is naturally
  source-agnostic. No code change, no test change to the service.
  Constitution Principle I (hexagonal architecture) pays off
  exactly here: a new adapter slots in without rippling.
- **Prefetch AS400 sources by default** (per user direction).
  REBIRTH §12's `metadata_prefetch_exclude: ["RVABREP"]` excludes
  AS400 by default; 015 deviates because the operator-controlled
  table is usually `CLIENTS` or `ACCOUNTS` (~10s of thousands of
  rows, ~5-50 MB in RAM). A future change can add a per-source
  `prefetch: bool` flag if memory becomes a constraint.
- **Per-field `as400_query` deferred**. REBIRTH §12 supports custom
  SQL per field (`as400_query: "SELECT NOMBRE FROM RVILIB.CLIENT_TABLE
  WHERE CIF = ?"`). 015 simplifies: each AS400 metadata source maps
  to ONE table. Operators who need joins / filters can pre-export
  to a CSV and use a `csv:<alias>` source instead. Custom-SQL
  support is a follow-up change.
- **`_reject_unsupported_source_types` removal is safe**. The
  guard was a placeholder added in 011 because no consumer existed
  for `as400:*` yet. 015 ships the consumer. The MetadataService's
  existing alias-validation catches misconfiguration: a `field_sources[X].sources[i].source_type == "as400:typo"` referencing an
  alias not in `metadata.sources` raises
  `ConfigurationError("unknown CSV alias")` at prefetch time. (The
  error message's "CSV" text is now slightly stale; a cleanup
  rename is queued for a follow-up.)
- **Operator-facing change is small**. A config with a single
  csv-only metadata source needs zero edits (loader injects
  `kind: "csv"`). A config with an AS400 metadata source needs only:
  ```yaml
  metadata:
    sources:
      - kind: as400
        alias: customers
        as400_connection:
          host: 10.x.x.x
        table: CLIENTS
  ```
  plus the existing `AS400_USERNAME`/`AS400_PASSWORD` env vars
  (from 014).

---

## [0.16.0] — 2026-05-10 — **multi-pipeline + AS400 production-ready**

Largest change of the project. Five thrusts in one PR.

### Added

- **`cmcourier.adapters.sources.as400.As400DataSource`** — concrete
  `IDataSource` over pyodbc. Lazy `import pyodbc` inside `_connect()` so
  importing this module never crashes in environments without unixODBC
  headers (failure surfaces on first real call). All pyodbc.Error
  exceptions are wrapped in `IndexingError` with SQLSTATE extracted from
  `exc.args[0]` when the format matches. IN-list queries chunked at 1000
  values. `query_stream` uses `fetchmany(500)`. Single connection per
  instance (thread-local connections deferred per REBIRTH §3.1 + change
  010's single-threaded decision).
- **`cmcourier.services.triggers.as400.As400TriggerStrategy`** —
  real implementation replacing the 006 stub. Runs a configured SQL
  query and yields `TriggerRecord` per row. Blank rows dropped with an
  INFO log of the count. Lives in its own module
  (`services/triggers/as400.py`); the stub at `stubs.py` is removed.
- **`cmcourier rvabrep-pipeline run --config <yaml>`** — new CLI
  command. Verifies `trigger.kind == "rvabrep"` after load_config;
  mismatch exits 2.
- **`cmcourier as400-trigger-pipeline run --config <yaml>`** — new
  CLI command. Same shape; verifies `trigger.kind == "as400"`.
- **Doctor `as400_connectivity` check** — runs when `trigger.kind ==
  "as400"`, opens the AS400 connection + `SELECT 1`. SKIPped when
  kind is csv or rvabrep. Inserted between `cmis_connectivity` and
  `tracking_openable` so connectivity failures cluster at the top.
- **`As400ConnectionConfig`** new Pydantic schema block (host, port,
  database, driver, table). Credentials still env-only.
- **22 new tests**: ~14 AS400 adapter tests with mocked pyodbc, ~5
  schema discriminated-union tests, ~3 wiring + CLI tests for the new
  pipelines, ~1 new doctor test.

### Changed

- **`CsvTriggerPipeline` → `StagedPipeline`**. Module renamed via
  `git mv` (`orchestrators/csv_trigger.py` → `orchestrators/staged.py`).
  Class is now generic — the S0 strategy is injected, no longer csv-
  specific. Constitution III rule of three: with the 2nd pipeline
  landing, the abstraction is earned. Every test file referencing the
  old name updated in-place.
- **`TriggerConfig` discriminated union**. `trigger.kind` is the
  discriminator (`csv` | `rvabrep` | `as400`). Three concrete schema
  classes: `CsvTriggerConfig`, `RvabrepTriggerConfig`,
  `As400TriggerConfig`. `TriggerCsvConfig` kept as a backwards-compat
  alias. The loader injects `kind: "csv"` into trigger blocks that
  omit it, so existing change 012 configs continue to load
  unchanged.
- **`build_pipeline` dispatches on `config.trigger.kind`**. Three
  branches: csv (existing), rvabrep (DirectRvabrepTriggerStrategy
  over the existing indexing source), as400 (new As400DataSource +
  As400TriggerStrategy). The as400 branch requires
  `secrets.as400_username` and `secrets.as400_password` to be set;
  missing values raise `ConfigurationError`.
- **CLI `app.py` refactored**. Extracted `_run_pipeline_command(...,
  *, expected_kind=X)` helper used by all three pipeline commands.
- **`As400TriggerStrategy` stub removed** from
  `services/triggers/stubs.py`. The real strategy now lives at
  `services/triggers/as400.py`. The stubs module retains only
  `LocalScanTriggerStrategy`.

### Verification

- `pytest -v`: **421 / 421 pass** in ~51 s (395 from earlier + 26
  net new across AS400, schema, wiring, CLI, doctor).
- `pytest --cov=src/cmcourier`: total branch coverage stays above
  95%. `adapters/sources/as400.py` ≥ 90%, `services/triggers/as400.py`
  100%, `orchestrators/staged.py` ≥ 96% (renamed but untouched
  logically).
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean across 37 source files.
- `pre-commit run --all-files`: clean.
- Smoke: `cmcourier --help` lists 4 commands; each pipeline's
  `--help` lists its flags.

### Rationale

- **AS400 unblocks every `as400:*` consumer**. Even without
  `MetadataService.as400:<alias>` support shipping today, the
  adapter is the gate. Once 014 merges, the next change adds the
  metadata fetch path in ~1 hour.
- **Generic StagedPipeline beats subclassing**. The 5 per-stage
  methods are identical across pipelines; only S0 differs. One
  class + injected strategy is the simplest correct abstraction.
  Subclasses or a mixin would be ~30 LOC of indirection for zero
  added expressiveness.
- **Discriminated union over a single fat `TriggerConfig`**: gives
  operators a clear schema error ("unknown kind: ftp") instead of
  silently accepting fields the wiring won't use. Backwards-compat
  via loader default keeps 012's YAMLs valid.
- **AS400 metadata source deferred to a follow-up**. The wiring
  rejects `as400:*` source types at `build_pipeline` time; the YAML
  schema permits the prefix (operators can document AS400 sources
  before the consumer ships). Splitting MetadataService's
  `_fetch_as400` into its own change keeps 014's blast radius
  bounded.
- **pyodbc lazy import** means the project's CI can install the
  package without ODBC system libraries. Real connection attempts
  fail at the call site with a clear error, not at import time.
- **AS400 retry is the same as CMIS retry**: deferred. The IDataSource
  port doesn't currently mandate a retry policy; AS400 query
  failures bubble up as `IndexingError` and the orchestrator's S1
  trigger-level error handling logs at WARNING and continues.

---

## [0.15.0] — 2026-05-10 — **pre-flight `doctor` command**

Operators get a fast pre-flight check before the first real
`csv-trigger-pipeline run`. A mis-configured pipeline that previously
failed 5-30 s in (after side effects had started) now fails in under
5 seconds with a structured report naming the specific check.

### Added

- **`cmcourier doctor --config <yaml>`** — new top-level Click command
  (sibling of `csv-trigger-pipeline`). Runs 6 checks in order and
  prints a `[STATUS] check_name — message` line per check, indented
  details (`key=value`), and a summary line. Exit codes: 0 if no
  FAIL (PASS/WARN/SKIP allowed), 1 on any FAIL, 2 on config error,
  3 on unhandled exception.
- **`cmcourier.cli.doctor`** module with:
  - `CheckStatus` (`enum.StrEnum`): `PASS` / `FAIL` / `WARN` / `SKIP`.
  - `CheckResult` (frozen+slots): `name`, `status`, `message`,
    `details: Mapping[str, str]`.
  - `DoctorReport` (frozen+slots): `results`, `elapsed_seconds`, plus
    `passed_count` / `failed_count` / `warn_count` / `skip_count` /
    `has_failures` properties.
  - `run_doctor(config, secrets) -> DoctorReport` — entry point that
    never raises; per-check exceptions become `FAIL` results.
  - 6 private `_check_*` functions covering:
    1. **`cmis_connectivity`** — warmup + repositoryInfo + non-empty
       `repository_id`.
    2. **`tracking_openable`** — `SQLiteTrackingStore` opens at the
       configured `db_path` and closes cleanly.
    3. **`mapping_completeness`** — Modelo Documental has ≥1 row
       (WARN if zero, FAIL on adapter exception).
    4. **`metadata_sources`** — every CSV alias has ≥1 row.
    5. **`cm_type_alignment`** — every distinct `cm_object_type` in
       the mapping resolves via CMIS `getTypeDefinition`. Surfaces
       ALL missing types in one pass. SKIPped if check 1 FAILed.
    6. **`sample_dry_run`** — manually walks S1→S2→S3→S4 on the first
       trigger's first doc, no upload. Cleans up the staged PDF on
       success. SKIPped if zero triggers or zero docs.
- **`IUploader.get_type_definition(object_type_id) -> Mapping[str, Any]`**
  — new abstract method. `CmisUploader` implements via
  `GET {base_url}/{repo_id}?cmisselector=typeDefinition&typeId=<id>`.
  Bypasses the retry loop — pre-flight prefers fail-loud over
  retry-quietly. Raises `CMISClientError` on 4xx (typically 404 for
  missing types) and `CMISServerError` on 5xx.
- **12 integration tests** in `tests/integration/cli/test_doctor.py`
  covering happy path, every check's failure mode, and CLI exit
  codes. Plus 3 new `TestGetTypeDefinition` tests in
  `tests/integration/adapters/test_cmis_uploader.py`.

### Changed

- `IUploader` port gains one abstract method (`get_type_definition`).
  `tests/unit/domain/test_ports.py` updated to include it in the
  abstract-method set.
- `src/cmcourier/cli/app.py` gains the `doctor` command + a small
  `_emit_doctor_report(report)` helper.

### Verification

- `pytest -v`: **395 / 395 pass** in ~65 s (380 from earlier + 15
  new: 12 doctor + 3 type-definition).
- `pytest --cov=src/cmcourier`: total branch coverage **95.94%**.
  `cli/doctor.py` at **93%**; `adapters/upload/cmis_uploader.py`
  at **94%**.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean across 35 source files.
- `pre-commit run --all-files`: clean.
- Smoke: `cmcourier doctor --help` lists `--config` and `--log-level`.

### Rationale

- **Pre-flight or pre-flight**: every operational failure mode
  reachable at validation time is. A 5-second SKIP at the
  trigger-CSV-empty case beats a 60-second batch-load that aborts
  mid-S2.
- **`get_type_definition` bypasses retry**. A 5xx during pre-flight
  is worth surfacing immediately; if it's flaky, the operator
  re-runs doctor — that's the equivalent of "retry once" but with
  human judgement attached. Production uploads still benefit from
  the retry policy.
- **`cm_type_alignment` surfaces ALL missing types** (not
  short-circuit). Operators fix multiple gaps in one round-trip
  instead of running doctor seven times.
- **`sample_dry_run` walks S1-S4 manually**, NOT via the
  orchestrator. The orchestrator would open the tracking store,
  call `start_batch`, etc. — irrelevant side effects for a
  read-only validation. The dry-run accesses the pipeline's
  private collaborator fields (`_trigger_strategy`,
  `_indexing_service`, etc.) — an intentional internal coupling
  that the doctor pays for in exchange for not duplicating the
  full wiring logic from `build_pipeline`.
- **Staged PDF cleaned up**. `contextlib.suppress(OSError)` around
  the unlink keeps doctor as close to "leaves no artifacts" as the
  filesystem allows.
- **No `--skip-doctor` flag on `run`**. Doctor is opt-in. Forcing
  it into the run loop adds latency to every iteration and couples
  two commands; operators run doctor when they want, not as a
  retried side-effect.
- **AS400 connectivity SKIPped**. The adapter doesn't exist yet;
  silently reporting SKIP is honest. When AS400 lands, doctor
  picks up the check by reading `config.cmis` vs a future
  `config.as400`.

---

## [0.14.0] — 2026-05-10 — **MVP CLI usable end-to-end**

This release ships the operator-facing layer. With `cmcourier
csv-trigger-pipeline run --config <yaml>`, the MVP pipeline is invokable
without writing Python. Four new modules wrap change 011's orchestrator
under a Pydantic v2 schema, a YAML loader, an adapter factory, and a
Click command. Credentials live exclusively in environment variables.

### Added

- `cmcourier.config.schema` — Pydantic v2 model graph for the full
  pipeline. Every model `ConfigDict(frozen=True, extra="forbid")`.
  `FilePath` for required-exists inputs, `Path` for outputs.
- `cmcourier.config.loader` — `load_config(path)` via `yaml.safe_load`
  + `model_validate`; `load_secrets()` reads CMIS_USERNAME /
  CMIS_PASSWORD (required) + AS400_* (optional). Both raise
  `ConfigurationError` with structured context.
- `cmcourier.config.wiring.build_pipeline(config, secrets)` — pure
  factory that opens every TabularDataSource and wires the orchestrator.
  Three private converters translate Pydantic models to the services'
  existing dataclass-based configs.
- `cmcourier.cli.app` — Click root group with one `csv-trigger-pipeline
  run` command. Flags: --config (req), --batch-id, --from-stage,
  --batch-size, --triggers, --log-level. Exit codes 0/1/2/3 per spec.
- `cmcourier.cli.logging_setup.configure(level)` — single stderr
  handler on the root logger; idempotent.
- 43 new tests across schema/loader/wiring/CLI.
- `pyproject.toml`: PyYAML>=6.0,<7.0 runtime; types-PyYAML>=6.0,<7.0 dev.
- `.pre-commit-config.yaml`: types-PyYAML in mypy hook's additional_dependencies.

### Changed

- `SQLiteTrackingStore` now explicitly inherits `ITrackingStore`
  (nominal typing for mypy strict at the wiring layer).
- `cmcourier.config.__init__` re-exports PipelineConfig, Secrets,
  load_config, load_secrets, build_pipeline.

### Verification

- pytest: 380/380 pass in ~62 s.
- coverage: 96.63% total. config/schema.py, config/loader.py,
  config/wiring.py, cli/logging_setup.py all 100%. cli/app.py 86%.
- ruff / mypy / pre-commit: clean.
- Smoke: `cmcourier --help` and `cmcourier csv-trigger-pipeline run
  --help` list the expected commands and flags.

### Rationale

- Pydantic v2 without pydantic-settings (per user direction). Env
  vars read manually — one less dep, zero magic.
- Schema enforces `extra="forbid"` so mis-configuration fails at load
  time, not 30 seconds into a real run.
- Wiring layer owns the schema → service-config translation. Services
  and adapters never import Pydantic — Constitution Principle I.
- `as400:*` rejected at wiring, not at schema. The schema accepts the
  prefix (documentation / future-proofing); the wiring layer enforces
  "do we have an adapter for this?".
- Single stderr logger (tier-based config is a future focused change).
- `SQLiteTrackingStore` now inherits `ITrackingStore` — duck-typing
  worked for tests but tripped mypy at the wiring boundary. The
  remaining adapters (`PdfAssembler`, `CmisUploader`) have the same
  gap and will be cleaned up in a follow-up.

---

## [0.13.0] — 2026-05-10 — **MVP pipeline end-to-end**

---

## [0.13.0] — 2026-05-10 — **MVP pipeline end-to-end**

This release ships the **first runnable MVP migration pipeline**. With
`CsvTriggerPipeline`, all of S0..S6 are wired against real adapters and
services — no stubs, no placeholders. The orchestrator IS the wiring;
every collaborator it imports has been on `main` since changes 003-010.

### Added

- **`cmcourier.orchestrators.csv_trigger.CsvTriggerPipeline`** — the first
  runnable orchestrator. Implements REBIRTH §10.2's `csv-trigger-pipeline`
  composition: `S0(csv) → S1 → S2 → S3 → S4 → S5 → S6 (transversal)`.
  Constructor takes the seven collaborators by keyword (`trigger_strategy`,
  `indexing_service`, `mapping_service`, `metadata_service`, `assembler`,
  `uploader`, `tracking_store`); `run()` returns a `RunReport` with
  per-stage counters and elapsed time.
- **`cmcourier.orchestrators.csv_trigger.RunReport`** — frozen+slots
  dataclass with `batch_id`, `total_triggers`, `total_docs`, per-stage
  `_done` / `_failed` counters, `s1_skipped_cross_batch`, and
  `elapsed_seconds`. Counter invariant: `s(N)_done + s(N)_failed == s(N-1)_done`.
- **Cross-batch idempotency** (REBIRTH §10): docs that are already at
  `S5_DONE` in any **prior** batch are skipped silently — no
  `migration_log` row in the new batch, no CMIS calls. Counts toward
  `RunReport.s1_skipped_cross_batch` with an INFO log carrying
  `reason="cross_batch_uploaded"`. If the doc is already at S5_DONE in
  the **current** batch (idempotent rerun), the cross-batch skip does
  NOT fire and the doc flows through stages with per-stage skip-checks.
- **Stage-by-stage resume** (REBIRTH §10.3): `run(batch_id=..., from_stage=N)`
  reuses an existing batch. S0+S1 still re-execute (re-read CSV, re-index
  RVABREP) but the orchestrator filters the fresh S1 output through
  `tracking_store.list_txn_nums_for_batch(batch_id)` — docs not in the
  prior batch's scope are logged at INFO with `reason="resume_out_of_scope"`
  and dropped. Within each stage, `is_stage_done` (new semantic — see
  Changed) per-doc short-circuits the work for already-done docs.
  Re-running with `from_stage=1` on a completed batch issues ZERO uploads.
- **20 pipeline integration tests** in
  `tests/integration/pipeline/test_csv_trigger_pipeline.py` across 9
  groups: parameter validation, fresh full run, S1 error handling,
  cross-batch skip, per-stage failures (S2/S3/S4/S5), resume (3 modes),
  heterogeneous batch, S0 failure, healed-CIF propagation.
  Branch coverage on `orchestrators/csv_trigger.py`: **96%**.
- **Pipeline test harness** at `tests/integration/pipeline/conftest.py`:
  wires every adapter / service from the existing fixture set, plus a
  `register_cmis_for_docs(txn_nums)` helper that pre-stubs warmup /
  folder creation / upload responses via the `responses` library. Each
  test composes its scenario by writing a trigger CSV under `tmp_path`,
  building a pipeline via the factory, and asserting on the `RunReport`
  plus side effects in the tracking store.
- **Pipeline RVABREP fixture** at `tests/fixtures/pipeline/rvabrep.csv` —
  6 synthetic rows tailored to the orchestrator test scenarios
  (happy path, unmapped id_rvi, missing files, metadata-source-fail,
  CIF self-healing) and pointing at the assembly fixtures from change 009.
- **`ITrackingStore.list_txn_nums_for_batch(batch_id) -> set[str]`** —
  new abstract method. Returns the set of `rvabrep_txn_num` values in
  `migration_log` for the given batch. Unknown batches return `set()`.
  Implemented in `SQLiteTrackingStore` via
  `SELECT DISTINCT rvabrep_txn_num FROM migration_log WHERE batch_id = ?`.
- **`ITrackingStore.flush()` abstract method** — promoted from
  `SQLiteTrackingStore` to the port. Orchestrators call this before any
  read that depends on writes from the same run (the "read my own writes"
  anchor). Synchronous implementations may make this a no-op.

### Changed

- **`SQLiteTrackingStore.is_stage_done(txn, batch_id, stage)`** semantic
  changed from "row's `status` field equals exactly `stage.value`" to
  "row has reached at least `stage` in this batch". Implementation now
  uses an `IN (...)` clause against the set of statuses ≥ the requested
  stage (e.g., `is_stage_done(S2_DONE)` returns True for rows currently
  at S2_DONE, S3_PENDING, S3_DONE, S3_FAILED, …, S5_FAILED). The old
  semantic was unusable for resume logic — after S5_DONE, every prior
  `is_stage_done(S(N)_DONE)` would return False because the row's status
  had moved on. Existing 007 tests still pass (they only check
  immediately after `mark_stage_done`); two new tests in
  `TestListTxnNumsForBatch` lock in the new semantic. **This is a
  behavioral change but no public callers existed before this change.**
- `src/cmcourier/orchestrators/__init__.py` re-exports
  `CsvTriggerPipeline` and `RunReport`.
- `src/cmcourier/domain/ports.py` gains two abstract methods on
  `ITrackingStore` (above). `tests/unit/domain/test_ports.py` updated.

### Verification

- `pytest -v`: **337 / 337 pass** in ~58 s (314 from earlier changes + 20
  pipeline tests + 2 SQLite port-amendment tests + 1 ports test).
- `pytest --cov=src/cmcourier`: total branch coverage **96.07%**;
  `orchestrators/csv_trigger.py` at **96%** (target ≥ 85%);
  `adapters/tracking/sqlite.py` holds at **92%**.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean across 30 source files.
- `pre-commit run --all-files`: ruff (legacy alias), ruff format, mypy
  all pass.

### Rationale

- **First MVP pipeline**. Every adapter and service from changes 003-010
  is now reachable through `CsvTriggerPipeline.run`. The only remaining
  blocker before operators can run real migrations is the CLI + config
  layer (Click command, Pydantic v2 config schema, YAML loader). That is
  the next change, NOT this one.
- **`is_stage_done` semantic redesign justified by real consumer**. The
  exception's first real consumer (the orchestrator) needed "has the doc
  reached at least stage N", not "is the doc currently at stage N
  exactly". The old semantic was speculation — useful for 007's spec but
  unusable for 011. Existing tests survived because they only checked
  the state immediately after a transition. Changing the semantic in
  one place (the adapter) avoids two competing methods on the port.
- **Cross-batch is_uploaded skip checks the SAME batch first**. Without
  this branch, idempotent re-runs (`run(batch_id=existing)`) would treat
  every doc as cross-batch-skipped because `is_uploaded(txn)` queries
  for `S5_DONE` in ANY batch, including the current one. The orchestrator
  preempts this by first asking `is_stage_done(txn, batch_id, S1_DONE)`
  for the current batch; if True, the doc flows through stages with
  per-stage skip-checks. If False, `is_uploaded` is consulted for the
  cross-batch case.
- **Trigger-level errors stay out of `migration_log`**. `RVABREPNotFoundError`
  and `RVABREPDeletedError` fire before any doc identity exists for the
  trigger. Creating a row would force a fake `rvabrep_txn_num`. Logging
  at WARNING with `shortname` + `system_id` is the right granularity;
  trigger-level metrics (how many triggers, how many empty) come from
  the `RunReport.total_triggers` vs `total_docs` ratio.
- **`flush` is part of the port**. The orchestrator needs the
  "read-your-writes" guarantee before reading state it just wrote
  (`is_stage_done` after `mark_stage_done`). Making `flush` abstract
  forces every implementation to declare its consistency model —
  asynchronous stores block, synchronous stores no-op.
- **Resume re-runs S0 + S1 wastefully**. The orchestrator re-reads the
  trigger CSV and re-indexes RVABREP on every resume invocation. A
  more efficient design (rehydrate (trigger, doc) state from
  `migration_log` rows) would require storing more fields per row and
  is a clear post-MVP optimization. The current cost is bounded by
  batch size, and resume is an operator-driven action — not a hot path.
- **Per-stage methods follow the same shape but are not abstracted**.
  Constitution III rule of three: 5 similar `_stage_sN` bodies (~25
  LOC each) is under the abstraction budget. Other pipelines (rvabrep,
  as400, local-scan, single-doc) will reuse most of this shape — when
  the 2nd pipeline lands, the orchestrator's stage skeleton becomes a
  candidate for extraction.

---

## [0.12.0] — 2026-05-10

### Added

- **`cmcourier.adapters.upload.cmis_uploader.CmisUploader`** — concrete `IUploader` for IBM Content Manager via the CMIS Browser Binding REST/JSON protocol (REBIRTH §8). Single-threaded MVP: one `requests.Session` shared across calls; thread-local sessions deferred to a follow-up change when the orchestrator's worker pool lands. Holds an in-memory `set[str]` folder cache so a verified or created folder path is never re-POSTed within a process lifetime.
- **Lazy JSESSIONID warmup** (REBIRTH §8.2): no HTTP at construction time; the first call to `test_connection`, `ensure_folder`, or `upload` issues `GET {base_url}/{repo_id}?cmisselector=repositoryInfo`. Re-warmup fires on any 401 from a subsequent POST.
- **Recursive idempotent folder creation** (REBIRTH §8.3): `ensure_folder(path)` walks segments left-to-right, skips any segment starting with `$` (system folders like `$type`), and POSTs `createFolder` to the parent for the rest. HTTP 409 (Conflict) is treated as success; the resulting path is still added to the cache. Re-invocation after a successful walk issues zero HTTP calls.
- **Streaming multipart upload** (REBIRTH §8.5) via `requests-toolbelt.MultipartEncoder`. The file is read from disk on demand by the encoder; the adapter never calls `.read()` on the whole stream. Property bag is laid out as `propertyId[N] / propertyValue[N]` pairs in insertion order, with three fixed slots for `cmis:objectTypeId`, `cmis:name`, `cmis:contentStreamMimeType` (the first three triples) and then the caller's `properties` mapping appended starting at index 3.
- **`cmcourier.adapters.upload.cmis_uploader.BandwidthLimiter`** (REBIRTH §8.6) — token-bucket file-stream wrapper with `read`, `seek`, `tell`, `close`, `name`, `__enter__`, `__exit__`. `mbps <= 0` disables throttling (read passthrough). Positive `mbps` throttles to `mbps * 1_000_000` bytes per second via a `time.monotonic()` refill loop. Passthrough methods are required so `MultipartEncoder` introspection works.
- **Complete retry policy** (REBIRTH §8.7): HTTP 201/2xx → success; HTTP 401 → re-warmup + retry exactly once (a second 401 raises `CMISClientError(status_code=401)`); HTTP 4xx (other) → fail-fast `CMISClientError`; HTTP 5xx → exponential backoff (`retry_base_delay_s * 2**(attempt-1)`, capped at 60 s), up to `retry_max_attempts`; `requests.exceptions.ConnectionError` whose message contains `"10053"` (Windows abort) → `ERROR` log + doubled sleep; retry budget exhausted → `RetriesExhaustedError(txn_num, attempts)` with the last `CMISServerError` as `__cause__`. 409 is handled as success ONLY in `_create_folder_segment`, never in the generic post path.
- **Three-path `cmis:objectId` parser** (REBIRTH §8.8): `succinctProperties["cmis:objectId"]` → `properties["cmis:objectId"]["value"]` → `str(data.get("id", "unknown"))`. Each fallback is reachable from a real IBM response shape variant. Unparseable JSON returns `"unknown"`.
- **`cmcourier.adapters.upload.cmis_uploader.CmisConfig`** — frozen+slots dataclass with `base_url`, `repo_id`, `username`, `password`, `timeout_seconds=300.0`, `verify_ssl=False`, `max_bandwidth_mbps=0.0`, `retry_max_attempts=3`, `retry_base_delay_s=2.0`.
- **26 integration tests** in `tests/integration/adapters/test_cmis_uploader.py` across 9 groups: config, warmup, `test_connection`, `ensure_folder` (skip `$`, recursive, cache, 409, cached-after-409), upload happy path (3 objectId fallbacks + Content-Type assertion), retry (5xx-then-201, 4xx fail-fast, 401 re-warmup, retries exhausted), Windows-10053 (delay doubling + ERROR log), BandwidthLimiter (throttle + passthrough + passthrough methods), logging discipline. Branch coverage on `cmis_uploader.py`: **94%** (target ≥ 85%).

### Changed

- `src/cmcourier/adapters/upload/__init__.py` re-exports `BandwidthLimiter`, `CmisConfig`, `CmisUploader`.
- **`pyproject.toml`** dev deps add `responses>=0.25,<1.0` for HTTP mocking. `responses` is the dev-only library that lets the integration tests exercise the real `requests` stack with the network stubbed — Constitution Principle VI's "no mocking the SUT" applies; `responses` mocks the network, not `requests`.

### Verification

- `pytest -v`: **314 / 314 pass** in ~36 s (288 from earlier changes + 26 new).
- `pytest --cov=src/cmcourier`: total branch coverage **96.21%**; `adapters/upload/cmis_uploader.py` at **94%**.
- `ruff check`, `ruff format --check`: clean (one `PTH123` lint nudged `open(...)` to `path.open(...)` during verification).
- `mypy --strict on cmcourier.*`: clean across 29 source files.
- `pre-commit run --all-files`: ruff (legacy alias), ruff format, mypy all pass.

### Rationale

- **Stage S5 closes the adapter set** for the MVP `rvabrep-pipeline`. With S0 (triggers), S1 (indexing), S2 (mapping), S3 (metadata), S4 (assembly), S5 (upload), and S6 (tracking) all real, the next change is the orchestrator — every adapter it cables will be production code, not a stub.
- **MVP includes BandwidthLimiter and complete retry policy** (per user direction). Skipping these to ship the adapter faster would mean either a noticeable production retry hole or a flaky first-week dry-run on shared corporate networks. The retry policy is the most heavily-tested area of the adapter precisely because its failure modes are silent and expensive.
- **Single-threaded MVP** (also per user direction): the adapter holds ONE `requests.Session`. REBIRTH §8.2's "per thread" note becomes load-bearing only when the orchestrator wants worker pools; refactoring to `threading.local()` is a focused, ~10-line change in a follow-up. Shipping it now would mean test fixtures and async patterns we'd be designing around a hypothetical orchestrator instead of a real one.
- **`responses` chosen over `requests-mock`**: same author surface, but `responses` integrates as a pytest fixture / context manager rather than monkey-patching `requests.adapters`. The result is a flat top-down test reading: register stubs → run code → inspect calls. The `responses.add_callback` API also lets us inspect the multipart `Content-Type` boundary without parsing the body.
- **`requests-toolbelt.MultipartEncoder` is non-negotiable**. Loading a 540-page TIFF into memory before POSTing is the production failure mode REBIRTH §8.5 explicitly warns against. The encoder reads the file stream on demand and computes content-length without buffering. Test 4.13 asserts the request header rather than the body bytes because `responses` does not faithfully reproduce multipart wire bytes anyway.
- **409 lives in `_create_folder_segment`, not in `_post_with_retries`**: making the generic retry path treat 409 as success would mask conflicts on document creation (where 409 means a real cmis:name collision, not idempotency). Locality of decision-making beats DRY here.
- **`assert last_exc is not None` before `RetriesExhaustedError(...) from last_exc`** is intentional. `mypy --strict` cannot prove the loop entered, so the assertion satisfies both the type checker and a future reader. The assertion is reachable only if `retry_max_attempts >= 1` (configured default 3); a misconfiguration `retry_max_attempts=0` falls through to the assert as a `AssertionError` — that is acceptable behavior, distinct from a runtime upload failure.
- **Logging discipline (Constitution VIII)**: retry / warn / error logs carry `txn_num`, `attempt`, `status_code`, and `folder_path` via the `extra` dict; no property values, no response bodies beyond a 1024-char truncation. `TestLoggingDiscipline` verifies that a `clbNonGroup.BAC_CIF` value containing the sentinel `BAC_VALUE_THAT_MUST_NOT_LEAK_999999` never appears in any log record across an entire retry cycle.

---

## [0.11.0] — 2026-05-10

### Added

- **`cmcourier.adapters.assembly.pdf_assembler.PdfAssembler`** — concrete `IAssembler` for Stage S4 (REBIRTH §7). Dispatches on `RVABREPDocument.is_pdf`: native PDFs pass through via `shutil.copy2` to `{temp_dir}/{txn_num}.pdf` with `page_count` read from `doc.total_pages` (we trust RVABREP, do not parse the PDF); paged documents are glob-discovered, sorted by `int(extension)` to handle variable padding (REBIRTH §3.4), and merged via `img2pdf.convert` (fast path) with a `PIL.Image` + `PyPDF2.PdfMerger` fallback for mixed-content edge cases.
- **`cmcourier.adapters.assembly.pdf_assembler.AssemblerConfig`** — frozen+slots dataclass exposing `source_root`, `temp_dir`, and `image_type_map` (defaults from REBIRTH §7.5 — `B → image/tiff`, `O → application/pdf`, `C → image/jpeg`).
- **OneDrive temp-dir trap** (REBIRTH §7.4): if `temp_dir` resolves to a `./tmp` variant (`tmp`, `./tmp`, `tmp/`, `.\\tmp`), the assembler diverts to `Path(tempfile.gettempdir()) / "cmcourier_tmp"` and creates the dir at construction time. Constants `_ONEDRIVE_TRAP_VARIANTS` and `_DIVERTED_DIR_NAME` live as module-level frozensets.
- **Page discovery semantics**: glob `FILECODE.*` in the source directory, filter to entries whose extension is purely numeric (`str.isdigit`), sort by `int(extension)`. The native PDF extension `.PDF` is excluded by the digit filter. Missing source dir or zero numeric pages raises `SourceFileMissingError(file_path=...)`. A discovered/expected mismatch emits a `WARNING` log naming `txn_num` + counts but does NOT raise — the filesystem is the source of truth.
- **Dual-path assembly**: img2pdf primary, Pillow + PyPDF2 fallback. The fallback opens each page via `PIL.Image`, converts to RGB if necessary (mode `1` TIFFs cannot save as PDF directly), writes each page as a single-page PDF into a `BytesIO`, and merges via `PdfMerger`. If both paths fail, the assembler raises `PDFAssemblyFailedError(txn_num=..., reason=...)` with the secondary exception as `__cause__`.
- **18 integration tests** in `tests/integration/adapters/test_pdf_assembler.py` across 9 groups: construction, native passthrough, paged happy path (TIFF + JPEG + variable padding + unrelated-PDF exclusion), page-count mismatch WARNING, source-files missing, fallback path (monkey-patched img2pdf), both-paths-fail, output validation (PyPDF2 reader inspection), logging discipline. Branch coverage on `pdf_assembler.py`: **98%** (target ≥ 90%).
- **`tests/integration/adapters/conftest.py`** — session-scoped autouse fixture generator using Pillow to materialize the binary fixtures (TIFF / JPEG / PDF) under `tests/fixtures/assembly/`. Idempotent (skips existing files). Generated binaries are gitignored.
- **`.gitignore`** updated with patterns for the generated assembly fixtures (`tests/fixtures/assembly/**/*.{pdf,PDF,tif,tiff,jpg,jpeg}` plus numeric-extension page files like `.001`, `.10`, `.540`).

### Changed

- `src/cmcourier/adapters/assembly/__init__.py` re-exports `PdfAssembler` and `AssemblerConfig`.

### Verification

- `pytest -v`: **288 / 288 pass** in ~33 s (270 from earlier changes + 18 new).
- `pytest --cov=src/cmcourier`: total branch coverage **96.55%**; `adapters/assembly/pdf_assembler.py` at **98%**.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean across 28 source files (the existing `img2pdf` / `PyPDF2` `ignore_missing_imports` blocks in `pyproject.toml` cover the new module's third-party imports).
- `pre-commit run --all-files`: ruff (legacy alias), ruff format, mypy all pass.

### Rationale

- **Stage S4 is self-contained** — filesystem only, no network, no AS400. With S4 shipping, the only remaining adapter for the MVP `rvabrep-pipeline` is S5 (CMIS upload). Tracking + service triangle + S0 strategies are all already in place.
- **Both assembly paths included in MVP** (per user direction): the Pillow/PyPDF2 fallback adds ~30 LOC and ~2 tests but exercises real `PIL` + `PyPDF2` code under a monkey-patched img2pdf, so the adapter is "fit for purpose" from v1 without leaving a half-shipped fallback to wire up later.
- **`page_count` comes from `doc.total_pages` for native PDFs, from the glob result for paged docs**. Parsing the native PDF would be extra IO with no business value — RVABREP is the authority for the document's intended page count, and the staged PDF is what we ship to CM regardless.
- **Page-count mismatch is a WARNING, not an error**. The filesystem is the source of truth. If a paged document has 540 pages claimed in RVABREP but only 539 on disk, the migration still ships 539 — refusing would block real production data. Operators see the WARNING in tier-2 logs and investigate offline.
- **OneDrive trap baked into the constructor** (not a callable utility) because misconfiguration here destroys throughput silently (locked files, retry storms). Catching it at construction surfaces the diversion immediately in startup logs; tier-3 ops can grep for `temp_dir` divergence.
- **Synthetic-fixture pattern** mirrors change 005 (xlsx generation in `tests/conftest.py`) — binary blobs stay out of git history; regeneration is sub-second and deterministic. This keeps repo size flat and avoids merge conflicts on opaque binaries.
- **PyPDF2 v3 deprecation warning** (`PyPDF2 is deprecated. Please move to the pypdf library instead.`) is acknowledged but accepted for now. A follow-up change can migrate to `pypdf` without touching the assembler's public API; the migration is a constitutional amendment of the `Constraints` section, not a domain change.

---

## [0.10.0] — 2026-05-10

### Added

- **`cmcourier.services.indexing.IndexingService`** — concrete Stage S1 (REBIRTH §10.1). Given a `TriggerRecord`, returns every non-deleted `RVABREPDocument` matching `(shortname, system_id)`. CIF is intentionally NOT a filter — CIF self-healing is the responsibility of Stage S3 (REBIRTH §6.5).
- **Two public APIs**: `find_documents(trigger) -> list[RVABREPDocument]` raises `RVABREPNotFoundError` / `RVABREPDeletedError` / `IndexingError`; `find_documents_batch(triggers) -> Iterator[(trigger, list)]` yields one pair per input trigger with empty lists on miss (silent — orchestrators decide semantics). Batched API chunks input into IN-list batches of 50 (REBIRTH §10.1) issuing one `get_by_fields_in` call per chunk.
- **`cmcourier.services.indexing.IndexingColumnsConfig`** — frozen+slots dataclass mapping adapter row keys onto `RVABREPDocument` fields. Defaults match REBIRTH §3.2 physical column names verbatim (`ABABCD`, `ABAACD`, `ABAANB`, `ABACST`, `ABAHCD` = id_rvi, …); tests override every column to the CSV fixture's friendly names.
- **Duplicate `txn_num` handling**: WARNING log + first-wins (mirrors MappingService's REBIRTH §4.3 precedent). No exception is raised. Production data quality issues surface in logs, not in the pipeline's error path.
- **Row coercion**: `creation_date` parses via `parse_cymmdd`; `last_view_date` of `'0'` or `''` becomes `None`; `total_pages` coerces to `int` with empty/`None` → `0`; every other field is `str()`-coerced defensively against pandas / pyodbc returning native ints.
- **22 unit tests** in `tests/unit/services/test_indexing.py` across 7 groups (construction, single-trigger, duplicates, batched, coercion, error wrap, logging). Branch coverage on `services/indexing.py`: **96%** (target ≥ 95%).
- **1 fixture CSV** under `tests/fixtures/services/rvabrep_index_sample.csv`: 15 synthetic rows covering vanilla multi-match, fully-deleted, mixed-deleted, duplicate txn_num, same-shortname-across-systems, `last_view_date='0'` / `''`, PDF and paged variants.

### Changed

- `src/cmcourier/services/__init__.py` re-exports `IndexingService` and `IndexingColumnsConfig` (alongside the prior 15 public symbols).
- **`cmcourier.domain.exceptions.RVABREPDeletedError`** amended from `(txn_num, delete_code)` to `(shortname, system_id, deleted_count)`. The exception's first real consumer (IndexingService) describes the SET case "every matching row is deleted", not "this specific record is deleted". `tests/unit/domain/test_exceptions.py` updated to assert the new shape. No production code uses the old signature.

### Verification

- `pytest -v`: **270 / 270 pass** in ~24 s (248 from earlier changes + 22 new).
- `pytest --cov=src/cmcourier`: total branch coverage **96.40%**; `services/indexing.py` at **96%**.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean across 27 source files.
- `pre-commit run --all-files`: ruff (legacy alias), ruff format, mypy all pass.

### Rationale

- **Closes the service triangle**. Mapping (S2, change 004), Metadata (S3, change 005), and now Indexing (S1) are the three services every CMCourier pipeline relies on. With this change, the next milestone is the first orchestrator that wires S0..S6 end-to-end.
- **CIF is NOT a filter here**. REBIRTH §6.5 makes CIF self-healing a Stage S3 responsibility — adding CIF to the WHERE clause would either reject legitimate documents (when the trigger's CIF is missing) or duplicate CIF resolution logic across two stages. Single source of truth wins.
- **Batched API yields empty on miss, not raises**. Single-trigger callers (single-doc pipeline, doctor command) want typed errors. Orchestrator callers want to keep processing the batch — a missing trigger becomes a tracking event, not an exception that aborts the iterator. The two APIs express the two semantics cleanly.
- **One `get_by_fields_in` per chunk, Python-side grouping by `(shortname, system_id)`**: triggers in the same chunk may have different `system_id`s, so passing `system_id` as a fixed filter would over-restrict. The over-fetch is bounded (cardinality of shortnames across systems is small in practice).
- **`RVABREPDeletedError` amendment is justified**: the exception's original `(txn_num, delete_code)` shape modeled a single-doc workflow that hadn't shipped. The set-semantic shape `(shortname, system_id, deleted_count)` matches the actual S1 use case where "every matching row is deleted" is the failure surface. The single-doc pipeline, when it lands, can introduce a separate exception (or extend this one additively) without churn.
- **Logging discipline (Constitution VIII)**: the WARNING for duplicate txn_num carries `shortname` and `duplicate_count` in `extra`, never the values of `cif` / `index2..6`. The test in `TestLoggingDiscipline` asserts that the CIF value `'456789'` from the duplicate fixture row never appears in any log record.

---

## [0.9.0] — 2026-05-10

### Added

- **`cmcourier.adapters.tracking.sqlite.SQLiteTrackingStore`** — concrete `ITrackingStore` over stdlib `sqlite3`. Two-connection model (sync reader + async writer daemon thread fed by a `queue.Queue`); WAL journal + `synchronous=OFF` + 64 MiB page cache + temp_store=MEMORY (REBIRTH §9.3); batched commits up to 500 writes or every 1 s (REBIRTH §9.4); cross-batch idempotency via the partial index `idx_migration_log_uploaded` on `rvabrep_txn_num WHERE status='S5_DONE'`; within-batch idempotency via the unique index `idx_migration_log_txn_batch` on `(rvabrep_txn_num, batch_id)` plus `INSERT OR IGNORE` on `mark_stage_pending`. `start_batch` is the only synchronous write (returns a UUID4 the caller needs immediately). `flush()` blocks on `queue.join()` for test determinism and orchestrators that need to read state they just wrote. `close()` is idempotent and drains pending writes.
- **`MigrationRecord.batch_id: str`** — new required field on the domain dataclass (`src/cmcourier/domain/models.py`) between `rvabrep_file_name` and `status`. Resolves a port inconsistency where `mark_stage_pending(record, stage)` had no way to know the record's batch — putting it on the record itself is cleaner than amending the port signature.
- **`tests/integration/adapters/test_sqlite_tracking_store.py`** — 25 integration tests against a real per-test SQLite file (no mocks; Constitution Principle VI) across 7 groups: schema, batch lifecycle, per-stage state machine, queries, lifecycle, error wrapping, and the writer's 500-row batch cap. `_make_record(batch_id, txn_num, **overrides)` helper at module level.
- **2 new unit tests** in `tests/unit/domain/test_models.py` covering the new `batch_id` field on `MigrationRecord` (default-value rejection + presence on construction). Existing `MigrationRecord` constructions in the file updated to pass `batch_id="batch-test-001"`.

### Changed

- `src/cmcourier/adapters/tracking/__init__.py` re-exports `SQLiteTrackingStore`.

### Verification

- `pytest -v`: **248 / 248 pass** in ~22 s (222 from earlier changes + 25 new integration tests + 1 new unit test on the new field; net +26).
- `pytest --cov=src/cmcourier`: total branch coverage **96.41 %**; `adapters/tracking/sqlite.py` at **92 %** (target ≥ 90 %).
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean across 26 source files.
- `pre-commit run --all-files`: ruff (legacy alias), ruff format, mypy all pass.

### Rationale

- Stage S6 (Tracking) is transversal — every pipeline depends on it. Without it, no orchestrator can resume after a crash, no `is_uploaded` skip-check is possible, and no per-stage retry can be scoped. This change ships the only tracking backend the MVP needs.
- **Two SQLite connections, one writer thread** is the lightest design that simultaneously meets the throughput target (REBIRTH §9.4 calls out a 200 000-document target on a single process) and respects SQLite's threading rules. WAL coordinates the two connections so a writer never blocks a reader. `synchronous=OFF` is acceptable because every operation is idempotent (Constitution Principle II) — a crashed batch is replayed, not corrupted.
- **`start_batch` is the only synchronous write** because the caller needs the UUID4 immediately to attach to records that flow into subsequent stages. Every other write is `enqueue + return` so orchestrators are not bottlenecked on disk.
- **Idempotency is encoded in the schema**, not in Python: the unique index on `(rvabrep_txn_num, batch_id)` lets `INSERT OR IGNORE` be the entire body of `mark_stage_pending`'s SQL; the partial index on `WHERE status='S5_DONE'` makes `is_uploaded` an O(1) read regardless of how many batches have run. Constitution Principle II is structural in this adapter.
- **`preprocess_staging` and `document_cache` tables are explicitly OUT OF SCOPE** for this change — the 3-phase pipeline and the cross-mode metadata cache that use them are deferred to post-MVP (`docs/roadmap/POST-MVP.md`). Shipping only the two tables the MVP actually needs avoids ALM debt later.
- **Logging discipline (Constitution Principle VIII)**: logs identify operational keys (`txn_num`, `batch_id`) but never field values; `error_message` bodies live in the DB but are never echoed back to logs.

---

## [0.8.0] — 2026-05-10

### Added

- **`cmcourier.services.triggers.csv.CsvTriggerStrategy`** — concrete `S0Strategy` over any tabular `IDataSource`. Validates required columns at first row; treats blank `CIF` as `None` (CIF self-healing in stage S3 covers it); skips rows with blank `shortname`/`system_id` with an INFO log of the count. Lazy iteration.
- **`cmcourier.services.triggers.direct_rvabrep.DirectRvabrepTriggerStrategy`** — concrete `S0Strategy` that scans RVABREP itself, with optional `RvabrepFilters(systems, document_types)`. Picks the smaller filter for the IN-list query and rejects the other in Python during iteration. Deduplicates `(shortname, system_id)` pairs (first occurrence wins, matching REBIRTH §4.3 / MappingService precedent).
- **`cmcourier.services.triggers.stubs.{As400TriggerStrategy, LocalScanTriggerStrategy}`** — concrete `S0Strategy` placeholders. Constructor succeeds; `acquire()` raises `NotImplementedError` with messages naming the missing dependency. Same late-fail pattern used for `as400:<alias>` in 005.
- **3 frozen+slots config dataclasses**: `CsvTriggerColumnsConfig` (defaults match REBIRTH §12 trigger config — `ShortName`, `CIF`, `SystemID`), `RvabrepColumnsConfig` (defaults match RVABREP physical columns from §3.2 — `ABABCD`, `ABACCD`, `ABAACD`, `ABAHCD`), `RvabrepFilters`.
- **21 unit tests** in `tests/unit/services/test_trigger_strategies.py` (3 test classes covering CSV, RVABREP, stubs). All using real `TabularDataSource` over CSV fixtures. Branch coverage on `services/triggers/*`: **100%**.
- **4 fixture CSVs** under `tests/fixtures/services/triggers/`: `trigger_list.csv` (5 rows incl. blanks), `trigger_list_alt_columns.csv` (custom column names), `trigger_list_missing_col.csv` (validates required-column error), `rvabrep_export.csv` (8 rows, 4 unique pairs after dedup).

### Changed

- `src/cmcourier/services/__init__.py` re-exports the 7 new public symbols from `triggers/` (in addition to the 8 from `mapping`/`metadata`).

### Verification

- `pytest -v`: **222 / 222 pass** in ~3 s (201 from earlier changes + 21 new).
- `pytest --cov`: total project branch coverage holds at ≥94%; `services/triggers/*` at **100%**.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.services.*`: clean across 25 source files.
- `pre-commit run --all-files`: clean.

### Rationale

- Stage S0 (Trigger Acquisition) is the entry point of every pipeline. With S0 unimplemented, no orchestrator could run end-to-end. This change ships the two real strategies needed for the MVP pipelines (`rvabrep-pipeline`, `csv-trigger-pipeline`) and gates the other two with explicit stubs that document the missing dependency.
- **No `TriggerService` wrapper class.** The `S0Strategy` port already represents the trigger-acquisition abstraction; orchestrators in future changes instantiate the appropriate strategy directly per pipeline. The strategies ARE the service.
- The `source_descriptor` parameter on `S0Strategy.acquire()` is silently ignored by every strategy. It's a vestigial port parameter from 002; refining the port to remove it is out of scope (would require an amendment to 002's spec).
- Stubs raise at `acquire()`, not at construction. That lets orchestrators dispatch to them with valid wiring and surface the "missing dependency" error to operators only when the strategy is actually used.

---

## [0.7.0] — 2026-05-10

### Added

- **`cmcourier.services.metadata.MetadataService`** — most complex service in CMCourier so far; engine of stage S3 (Metadata Resolution) per REBIRTH §6. Per-field fallback chain with validation regexes (`re.fullmatch`), default-value fallback (validated against the first source's regex), CIF self-healing (returns a new `TriggerRecord` since the input is frozen), and field-alias normalization (case-insensitive forward map).
- **Five frozen+slots dataclasses**: `MetadataConfig`, `FieldSourceConfig`, `SourceConfig`, `ValidationConfig`, `MetadataResolution`. Carry the configuration shape and the resolution result.
- **Source types supported**: `trigger` (read TriggerRecord attribute), `rvabrep` (read RVABREPDocument attribute), `csv:<alias>` (lookup via IDataSource). `as400:<alias>` raises `NotImplementedError` with an explicit message naming the missing AS400 adapter — that source type lights up when the AS400 adapter ships.
- **Eager pre-fetching of CSV sources** at construction. Cache keyed by `(alias, key_column, key_value, value_column)` so a single CSV source serves multiple fields without re-iterating. `setdefault` preserves first-occurrence on duplicate keys (matches MappingService's REBIRTH §4.3 first-wins precedent).
- **CIF self-healing** (REBIRTH §6.5): if `trigger.cif is None` and `BAC_CIF` is among the canonical fields to resolve, the service resolves `BAC_CIF` first and returns a new `TriggerRecord` with the resolved CIF. Subsequent CSV lookups (which use `trigger.cif` as the lookup key) see the resolved value.
- **`MetadataResolution`** as the typed return shape: `metadata: ResolvedMetadata` + `healed_trigger: TriggerRecord`. Callers (orchestrators, in later changes) MUST use `result.healed_trigger` for subsequent stages.
- **32 unit tests** in `tests/unit/services/test_metadata.py` covering construction + pre-fetch (3), vanilla per source type (3), fallback chain (5), CIF self-healing (4), aliases (3), source dispatch (3), type immutability (2), and edge cases (9). Branch coverage on `metadata.py`: **99%** (target ≥95%).
- **3 CSV fixtures** under `tests/fixtures/services/metadata/`: `clients.csv`, `accounts.csv`, `cards.csv`. Synthetic CIFs (`123456`, `234567`, `345678`) and synthetic names (`JUAN PEREZ TEST`, etc.).

### Changed

- **Pre-commit hook bumped**: `.pre-commit-config.yaml` `ruff-pre-commit` rev from `v0.4.10` to `v0.15.12` to align with the local venv's resolved version. Five changes in a row had hit the version drift; this resolves it. Ruff's hook IDs changed slightly (`ruff` → `ruff (legacy alias)`, `ruff-format` → `ruff format`) but behavior is identical.
- `src/cmcourier/services/__init__.py` re-exports the six new public symbols from `metadata` (in addition to the two from `mapping`).

### Verification

- `pytest -v`: **201 / 201 pass** in ~3 s (169 from earlier changes + 32 new).
- `pytest --cov=src/cmcourier`: total branch coverage **94%+**. Coverage on `services/metadata.py`: **99%**.
- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.services.*`: clean across 21 source files.
- `pre-commit run --all-files`: ruff (legacy alias), ruff format, mypy all pass.

### Rationale

- The metadata layer is the heart of CMCourier's "configurability" promise: every CMIS property comes from the fallback chain, with validation per source and a safety-net default. Without this service, no document can be uploaded with correct metadata.
- **Pre-fetching included in this change (not deferred)**: REBIRTH §6.6 explicitly notes that without it, a 200,000-document migration would fire tens of thousands of point queries against AS400. The pre-fetch is central to the architecture, not an optimization to bolt on later.
- **CIF self-healing returns a new `TriggerRecord` instead of mutating**: domain models are `frozen=True`. The contract is documented and tested; orchestrators threading `healed_trigger` forward is the next change's responsibility.
- **`as400:<alias>` raises `NotImplementedError` with explicit message**: cleaner than partially-implementing it. The handler will be added in one line when the AS400 adapter ships; tests pin the contract today.
- **Logging discipline (Constitution Principle VIII)**: the service logs field NAMES (`BAC_CIF`, `BAC_Nombre_Cliente`) but NEVER field VALUES. Customer name, account number, and CIF VALUES are PII; field names are not.

---

## [0.6.0] — 2026-05-09

### Added

- **`cmcourier.services.mapping.MappingService`** — the first service-layer class. Caches the Modelo Documental (REBIRTH §4) at construction from any `IDataSource` and exposes `get_mapping(id_rvi)`, `get_all()`, `count()`, and `__contains__`. Stage S2 of every pipeline depends on this lookup, as does the future `doctor` command's mapping-completeness check.
- **`cmcourier.services.mapping.MappingColumnsConfig`** — frozen dataclass for column-name overrides. Defaults match REBIRTH §4.1 (`"ID CLASE DOCUMENTAL"`, `"ID RVI"`, `"ID Corto"`, `"CLASE DOCUMENTAL"`, `"METADATOS"`).
- **Duplicate handling** per REBIRTH §4.3: first occurrence of a repeated `ID RVI` wins; subsequent occurrences are dropped with a `WARNING` log entry naming the duplicate value.
- **Empty-ID-RVI handling**: rows with blank or whitespace-only `ID RVI` cells are silently skipped; the constructor logs an `INFO` line with the skipped count.
- **METADATOS parsing**: comma-separated, whitespace-tolerant, empty-fragment-filtering. `(""," CIF, NUM "," CIF , ", "CIF,", "CIF,,NUM_CUENTA")` all yield clean tuples without surprises.
- **`tests/unit/services/test_mapping.py`** — 21 unit tests using a real `TabularDataSource` over `tests/fixtures/services/modelo_documental.csv` (no IDataSource mocks; the SUT does no I/O so the adapter is wiring, not the system under test). Coverage on `services/mapping.py`: **100 %**.
- **`tests/fixtures/services/modelo_documental.csv`** — 8-row fixture with vanilla rows, METADATOS edge cases (empty, whitespace, trailing comma, doubled comma), one duplicate `ID RVI`, and one empty-ID row.

### Changed

- `src/cmcourier/services/__init__.py` re-exports `MappingService` and `MappingColumnsConfig` so callers write `from cmcourier.services import MappingService`.
- README "Status checklist" ticks the fourth-change milestone.

### Verification

- `pytest -v`: **169 / 169 pass** in 1.32 s (148 from earlier changes + 21 new).
- `pytest --cov=src/cmcourier`: **total branch coverage 95.34 %** (threshold 80 %); `services/mapping.py` 100 %; `domain/*` 95-100 %; `adapters/sources/tabular.py` 96 %.
- `ruff check`, `ruff format --check`, `mypy --strict`: all clean.
- `pre-commit run --all-files`: ruff, ruff-format, mypy all pass.

### Rationale

- **First service layer in CMCourier**. Validates that the hexagonal architecture established by 001-003 holds together end-to-end: `services/mapping.py` imports only `cmcourier.domain.*` (Constitution Principle I); the test wires a real `TabularDataSource` adapter; the service raises the domain-defined `IDRViNotMappedError` on cache miss. Future services (metadata, trigger, document) follow the same shape.
- **Eager-load + dict cache** chosen over lazy-with-cache-miss-query because the Modelo Documental is small (< 1000 rows in practice) and stage S2 needs O(1) lookup at pipeline scale.
- **Field aliases (CIF → BAC_CIF, REBIRTH §6.2) NOT handled here**. They are the responsibility of the metadata service (next change). Mapping exposes raw names from the source.
- **Logging via stdlib `logging.getLogger(__name__)`** is PII-safe in this layer because `id_rvi` is a document-class code, not customer data. The PII masking helper (`cli/ui/logging.py`, forthcoming) routes the loggers properly when it lands.

---

## [0.5.0] — 2026-05-09

### Added

- **`cmcourier.adapters.sources.tabular.TabularDataSource`** — first concrete `IDataSource` implementation. Reads CSV and XLSX files via pandas (with `openpyxl` as the engine for `.xlsx`/`.xls`), exposes the full IDataSource contract minus the SQL methods, and normalizes pandas `NaN` to Python `None` at the port boundary so callers never see pandas-specific sentinels.
- **`tests/integration/adapters/test_tabular_data_source.py`** — 34 integration tests parametrized over CSV / XLSX. Covers the contract methods, lifecycle (`close`, idempotency, post-close access), file-extension dispatch (case-insensitive, unknown rejected), encoding override (latin-1 fixture), and multi-sheet XLSX selection. Branch coverage on the new module: 96 % (target ≥ 90 %).
- **`tests/fixtures/sources/`** — synthetic test fixtures: `sample.csv`, `bad_extension.txt`, `latin1.csv` (committed), and `sample.xlsx` / `multi_sheet.xlsx` (generated at session start by a new `tests/conftest.py` autouse fixture; `*.xlsx` is gitignored to keep binaries out of the repo).
- **`openpyxl>=3.1,<4.0`** added to runtime dependencies — required by `pandas.read_excel` for `.xlsx` files.

### Changed

- `tests/conftest.py` now hosts a session-scoped autouse fixture (`_generate_xlsx_fixtures`) that materializes `sample.xlsx` and `multi_sheet.xlsx` at session start if they do not exist. Previously the file held only a docstring.
- `src/cmcourier/adapters/sources/__init__.py` re-exports `TabularDataSource` so callers write `from cmcourier.adapters.sources import TabularDataSource`.
- `.gitignore` excludes `tests/fixtures/sources/*.xlsx` (deterministic regeneration; binary diffs in git are noise).

### Verification

- `pytest`: **148 / 148 pass** in 2.81 s (112 unit + 34 integration + 2 smoke tests).
- `pytest --cov=src/cmcourier`: **total branch coverage 94.33 %** (threshold 80 %; tabular.py 96 %, domain layer 95-100 %).
- `ruff check`, `ruff format --check`: clean.
- `mypy src/cmcourier/`: clean across 19 source files.
- `pre-commit run --all-files`: ruff, ruff-format, mypy all pass.

### Rationale

- Provides the first concrete adapter so subsequent service-layer changes (004+) have a real `IDataSource` to test against without depending on AS400 — Constitution Principle VI's canonical dev/test substitute. The AS400 adapter, when it lands, implements the same port; both are interchangeable behind the abstraction.
- `query()` and `query_stream()` raise `NotImplementedError` with explicit messages rather than fake SQL via `pandasql` or `duckdb`. The IDataSource port is broad enough to cover both AS400 (SQL) and tabular (field-based) use cases; service code that calls `query()` knows it is talking to a SQL-capable adapter. A future ISP refactor of the port can split the SQL methods off if the asymmetry becomes painful.
- `dtype=str` always — preserves leading zeros (`"000456"` does not become integer 456) and unifies type semantics across CSV/XLSX. Type interpretation is a service-layer responsibility via factories, not an adapter concern.
- One class for both formats — they share the IDataSource methods identically; only loading differs. Two classes would duplicate ~80 % of the code without benefit.
- `openpyxl` is a transitive technical consequence of the explicit XLSX scope decision for this change. Not a constitutional amendment.

---

## [0.4.0] — 2026-05-09

### Added

- **`cmcourier.domain.models`** — frozen dataclasses (`@dataclass(frozen=True, slots=True)`) for `TriggerRecord`, `RVABREPDocument`, `CMMapping`, `ResolvedMetadata`, `StagedFile`, and `MigrationRecord`. The `StageStatus` enum (subclassing `enum.StrEnum` from Python 3.11) encodes the per-stage state machine from REBIRTH §10.3 with values matching member names so persistence layers can store them directly. Module-level helpers `parse_cymmdd`, `is_pdf_filename`, `compute_cm_folder`, and `compute_cm_object_type` live alongside the models because they are intrinsic to model semantics (REBIRTH §3.3, §3.4, §4.2).
- **`cmcourier.domain.ports`** — abstract interfaces `IDataSource`, `ITrackingStore` (with stage-aware methods `is_stage_done`, `mark_stage_pending`, `mark_stage_done`, `mark_stage_failed`, plus the cross-batch `is_uploaded` idempotency anchor), `IAssembler`, `IUploader`, and `S0Strategy` (the new abstraction for the four trigger source modes from REBIRTH §5.1). All declared as `abc.ABC` with `@abstractmethod` decorators. Concrete implementations land in 003+.
- **`cmcourier.domain.exceptions`** — typed hierarchy rooted at `CMCourierError`, organized by stage (`TriggerError` S0, `IndexingError` S1 with `RVABREPNotFoundError` / `RVABREPDeletedError` / `RVABREPDuplicateError`, `MappingError` S2 with `IDRViNotMappedError`, `MetadataError` S3 with `SourceFailedError` / `DefaultValidationFailedError`, `AssemblyError` S4 with `SourceFileMissingError` / `PDFAssemblyFailedError`, `UploadError` S5 with `CMISClientError` / `CMISServerError` / `RetriesExhaustedError`, `TrackingError` S6) plus `ConfigurationError`. Every concrete subclass carries explicit named context parameters (`txn_num`, `id_rvi`, `batch_id`, etc.) for structured logging per Constitution Principle VIII.
- **`cmcourier.domain.__init__`** re-exports every public name (35 symbols) so callers write `from cmcourier.domain import IDataSource` regardless of which submodule the symbol lives in. `__all__` is alphabetized.
- **`tests/unit/domain/test_models.py`**, **`test_ports.py`**, **`test_exceptions.py`**, **`test_imports.py`** — 112 unit tests covering construction, validation rejection, frozen-ness, computed properties, helper edge cases (CYYMMDD round-trip, the REBIRTH §4.2 example, etc.), abstract-class semantics, exception hierarchy filtering, structured-context surfacing in `str(exc)`, and complete `__all__` re-export coverage.

### Verification

- `pytest -m unit -v tests/unit/domain/`: **112 / 112 pass** in 0.17 s.
- `pytest --cov=src/cmcourier/domain`: **98.56 % branch coverage** (target ≥ 95 %).
- `mypy src/cmcourier/`: clean across 18 source files with strict mode applied to `domain/`, `services/`, `orchestrators/`.
- `ruff check src/ tests/`, `ruff format --check`: clean.
- `pre-commit run --all-files`: ruff, ruff-format, and mypy hooks all pass.

### Rationale

- Provides the stable contract that every adapter (003+) and service (004+) will build against. Without this layer, no concrete code can be written without inventing types ad-hoc.
- All dataclasses are `frozen=True, slots=True` to make accidental mutation impossible and to keep per-instance memory footprint small at scale (200 000+ records in flight is plausible per REBIRTH §10.4).
- Exceptions carry structured context for downstream PII-safe logging in the observability layer (REBIRTH §17.4) without relying on message parsing.
- Constitution Principle I held throughout: zero third-party imports inside `src/cmcourier/domain/`. The only non-stdlib dependencies in test files are `pytest` itself.

---

## [0.3.0] — 2026-05-09

### Added

- **`pyproject.toml`** (PEP 621) declaring all runtime and dev dependencies per Constitution §Constraints, with major-version bounds on every package: `pydantic`, `click`, `pyodbc`, `requests`, `requests-toolbelt`, `pandas`, `img2pdf`, `Pillow`, `PyPDF2` (runtime); `pytest`, `pytest-cov`, `ruff`, `mypy`, `pre-commit`, `types-requests`, `pandas-stubs` (dev).
- **`src/cmcourier/`** in src layout (PEP 420) with hexagonal layering visible from day one: `domain/`, `adapters/{sources,tracking,assembly,upload}/`, `services/`, `orchestrators/`, `cli/{commands,ui}/`, `config/`. Every directory has an explicit `__init__.py` with a layer-purpose docstring.
- **`src/cmcourier/__init__.py`** exposes `__version__ = "0.0.0"`.
- **`src/cmcourier/cli/app.py`** Click group placeholder reserving the `cmcourier` binary entry point.
- **`tests/`** with `unit/{domain,services,orchestrators}/` and `integration/{adapters,pipeline}/` mirrors plus `conftest.py` (empty fixtures placeholder) and `tests/test_smoke.py` (asserts package imports and exposes a SemVer `__version__`).
- **`.pre-commit-config.yaml`** with ruff (lint + format), mypy on staged `src/cmcourier/` files, conventional-pre-commit on `commit-msg`, and a custom local hook (`scripts/hooks/no-co-authored-by.sh`) that blocks any commit message containing `Co-Authored-By` (Constitution Principle IX).
- **`scripts/hooks/no-co-authored-by.sh`** — executable Bash hook backing the rule above.
- **`.gitignore`** covering Python build/runtime artifacts, tooling caches, virtualenvs, IDE junk, and operational artifacts (`logs/`, `tmp/`, `staging/`, SQLite tracking files).
- **`.editorconfig`** with 4-space indent, LF endings, UTF-8, trim trailing whitespace, final newline; `*.md` exempt from trailing-space trim; `*.{yml,yaml,json,toml}` use 2-space indent.
- **`docs/INDEX.md`** — canonical map of every documentation artifact in the repository, organized by purpose per the Diátaxis framework. Updated by every change that adds or moves a doc.
- **`docs/how-to/README.md`** — index of how-to guides (problem-oriented "How to use"), with naming convention (`how-to/<task-slug>.md`) and an empty list at MVP start.
- **`docs/explanation/README.md`** — index of explanation documents (understanding-oriented "How it works"), with naming convention (`explanation/<concept-slug>.md`) and a pointer to the canonical domain explanation in REBIRTH.
- **README "Getting started"** section populated with prerequisites (including unixODBC-dev / IBM iSeries Access driver requirement for `pyodbc`), install / test / lint / type-check commands, env-var conventions, and a pointer to `docs/INDEX.md`.
- **README "Documentation map"** prominently links `docs/INDEX.md` as the canonical entry point.

### Changed

- README "Documentation map" expanded with rows for `docs/INDEX.md`, `docs/how-to/README.md`, `docs/explanation/README.md`.
- README "Status checklist" ticks the `/sdd-init` and Python-skeleton-bootstrap milestones.

### Rationale

- This change executes Phase 0 of the implementation order from `docs/domain/CMCOURIER_REBIRTH.md §15`, now under SDD discipline (spec / plan / tasks landed in commits `c908927` and `56a091c`; this commit ships the implementation).
- The skeleton holds **no business logic** — its only purpose is to give every subsequent change a working sandbox. The smoke test (`tests/test_smoke.py`) is the single proof that the scaffolding works: it asserts that `import cmcourier` succeeds and that `__version__` is a SemVer string.
- Pre-commit hooks enforce the constitutional rules from the first commit onward — Conventional Commits, no `Co-Authored-By` trailer, ruff lint + format, mypy on staged files. This is the moment the constitution stops being a document and starts being executable.
- Coverage threshold (80%) is configured but trivially passes on the empty skeleton. It becomes binding the moment the first real code lands.
- Documentation architecture follows the [Diátaxis framework](https://diataxis.fr): docs split by purpose (learn / solve / look up / understand) rather than by topic. We materialize only the two quadrants the user explicitly requested (`how-to`, `explanation`); `tutorials` and `reference` are deferred to natural-content moments per `specs/001-bootstrap-python-skeleton/plan.md §13`.

---

## [0.2.0] — 2026-05-08

### Added
- **`docs/domain/CMCOURIER_REBIRTH.md` §10 rewritten**: replaced the old "Execution Modes A/B/C" model with a stage-based pipeline architecture. Eight atomic stages (`S0`–`S7`) compose into named pipelines exposed as CLI commands.
- **`docs/domain/CMCOURIER_REBIRTH.md §10.5`**: Pre-Flight Validation specification. Automatic before any pipeline run; available as standalone `cmcourier doctor` command.
- **`docs/domain/CMCOURIER_REBIRTH.md §10.6`**: TUI by default with PREP / UPLOAD tabs (Rich); `cmcourier background` is the explicit headless exception.
- **`docs/domain/CMCOURIER_REBIRTH.md §10.7`**: Adaptive heavy / light upload lanes — design intent recorded, marked as post-MVP feature.
- **`docs/domain/CMCOURIER_REBIRTH.md §11`**: CLI surface restructured to match stage-based pipelines. `doctor`, pipelines as commands, `batch` and `inspect` subcommand groups.
- **`docs/domain/CMCOURIER_REBIRTH.md §17.4`**: Observability section expanded into five logging tiers (application, pipeline, network, system, slow-ops) with per-tier configuration toggles, bottleneck identification framework, PII discipline.
- **`docs/roadmap/POST-MVP.md`**: New exhaustive roadmap of nine deferred features (adaptive lanes, system metrics, log analysis tooling, AS400 tracking backend, AIMD auto-tuning, additional pipelines, multi-batch parallelism, per-batch bandwidth, cross-batch metadata cache) plus a watchlist. Each entry: intent, design, MVP placeholder, why deferred, acceptance criteria.
- **`README.md`**: project overview, status, documentation map, tech stack, project workflow, status checklist.
- **`CONTRIBUTING.md`**: SDD workflow, branching, conventional commits, PR standards, constitutional amendment procedure pointer.
- **`CHANGELOG.md`**: this file.

### Changed
- **Configuration schema (`§12` of REBIRTH)**: removed the global `datasource_mode` field. Trigger source is selected by which pipeline command is invoked, not by a config flag.

### Rationale
- The user surfaced a list of design changes that the rewrite should adopt: pipelines as composable stages, modes as commands rather than config, an explicit `doctor` command, TUI everywhere except background, batch-as-first-class with two-batch producer-consumer flow, stage-by-stage execution per batch, exhaustive observability, validatable mapping/metadata configurations.
- Document Class Mapping (`S2`) was promoted to a separate stage from Metadata Resolution (`S3`) so missing mappings and missing metadata produce distinct error classes — better diagnosis, better doctor output.
- The adaptive heavy/light lane design was explicitly deferred to post-MVP after a viability vs complexity trade-off review. Single-lane MVP delivers correct results; adaptive lanes deliver faster results.

---

## [0.1.0] — 2026-05-08

### Added
- **`.specify/memory/constitution.md`** ratified at v1.0.0 with nine core principles:
  - I. Hexagonal Architecture is Non-Negotiable
  - II. Idempotency is Sacred
  - III. No God Objects — Decompose by Responsibility
  - IV. Streaming Over Buffering
  - V. Config is the Single Source of Truth
  - VI. Real Test Pyramid (AS400 is not mocked)
  - VII. Spec Before Code
  - VIII. Data Sensitivity is Non-Negotiable
  - IX. Concepts Over Code, Verify Over Assume
- Constraints section: Python 3.11+, Pydantic v2, Click, pyodbc, requests + requests-toolbelt, pandas, img2pdf + Pillow + PyPDF2, SQLite (WAL), pytest, ruff, mypy.
- File and directory conventions per GitHub Spec Kit (`.specify/memory/`, `specs/<NNN-feature-slug>/`).
- Governance section: amendment procedure with SemVer (MAJOR/MINOR/PATCH), enforcement, document precedence chain.
- Project structure under `docs/domain/` (REBIRTH ground truth) and `docs/samples/{csv,excel,responses}/` (reference fixtures from RVIMigration).

### Moved
- `CMCOURIER_REBIRTH.md` → `docs/domain/CMCOURIER_REBIRTH.md` (preserved as git rename).
- `*.csv`, `*.xlsx`, `EjemploRespuestaCMIS.txt` → `docs/samples/{csv,excel,responses}/` (preserved as git renames).

### Rationale
- The old project (`RVIMigration`) drifted into a 1341-line God Object without immutable principles guiding the work. The constitution exists so the rewrite does not repeat that history.
- Spec Kit was chosen over OpenSpec for file-based, git-versioned SDD artifacts.

---

## How to read this changelog

- **Added**: new functionality or documentation
- **Changed**: existing behavior or documentation modified
- **Deprecated**: behavior or feature on its way out
- **Removed**: behavior or feature deleted
- **Fixed**: bug fixes
- **Security**: security-relevant changes
- **Moved**: file relocations (preserved as git renames where possible)
- **Rationale**: the *why* behind a release, when not obvious from the entries above

Pre-1.0.0 versions are documentation milestones. 1.0.0 will mark the first production-ready MVP migration.

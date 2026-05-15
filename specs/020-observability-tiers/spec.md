# Spec — 020-observability-tiers

**Status**: Draft
**Owner**: bitBreaker
**Date**: 2026-05-10
**Predecessors**: 012 (CLI + logging stub)
**Successors**: TBD (post-MVP §2 system metrics, §3 offline analyzer)

---

## 1. Problem

Today the CLI ships a single stderr text-format logger. the spec
defines a tiered observability surface that operators need before the
first real dry run: structured JSON logs, per-stage timing
aggregates, network-level latency for AS400 and CMIS, and a top-N
slow-ops report per batch. Without these tiers we cannot answer
"why was this batch slow?" or "which document took the longest?" —
the operator only sees text scroll past on stderr and an end summary
with totals.

POST-MVP §2 confirms **system metrics (tier 5, `psutil` sampling) is
deferred** — too costly to enable while we're still debugging
migration logic. 020 ships the four cheap tiers (app log, pipeline
metrics, network metrics, slow ops) plus the configuration surface
and the central PII masking helper.

---

## 2. Goals

- **G1**: Operators get structured JSON log output by default
  (`logs/app-{date}.log`) with one event per line, parseable by
  `jq` / log shippers.
- **G2**: Each batch close emits a single pipeline-metrics line
  with per-stage timing percentiles (p50/p95/p99), counts, and
  throughput.
- **G3**: Each AS400 query and each CMIS HTTP request emits a
  network-metrics event with duration and size.
- **G4**: At batch close, the top-N slowest operations land in a
  per-batch slow-ops file for offline review.
- **G5**: All PII (CIF, customer names, account numbers) is masked
  at the formatter level — values never reach the disk regardless
  of which logger emits them.
- **G6**: The whole subsystem is toggleable from YAML
  (`observability.enabled: false` disables the file handlers and
  reverts to stderr-only).
- **G7**: Pre-flight (`cmcourier doctor`) validates the log dir is
  writable.

## 3. Non-goals

- **NG1**: System metrics (tier 5, `psutil`). Explicitly deferred
  to POST-MVP §2.
- **NG2**: Offline log analyzer. POST-MVP §3.
- **NG3**: Live TUI dashboard. the spec, separate change.
- **NG4**: Log rotation by size. We use Python's
  `RotatingFileHandler` with the configured `rotation_mb` cap
  (built-in, no extra work); rotation strategy beyond that is
  out of scope.
- **NG5**: Retention/cleanup job. `retention_days` lives in the
  schema for future use; no scheduled cleanup ships in 020.
- **NG6**: Migrating existing logger names. Existing call sites
  (`_log.info("foo", ...)`) keep working — we add **structured
  fields via `extra={...}`** at the relevant emit points; we do
  not rewrite the call sites.
- **NG7**: Per-environment routing (dev / staging / prod). One
  config, one log dir.

---

## 4. Requirements (RFC 2119)

### Schema

- **REQ-001**: `cmcourier.config.schema` MUST add
  `ObservabilityConfig` with fields per the spec:
  - `enabled: bool = True`
  - `pipeline_metrics: bool = True`
  - `network_metrics: bool = True`
  - `system_metrics: bool = False` (MVP placeholder; rejected if
    set to True until POST-MVP §2 lands)
  - `log_dir: Path = Path("./logs")`
  - `log_format: Literal["json", "text"] = "json"`
  - `rotation_mb: int = Field(default=100, ge=1)`
  - `retention_days: int = Field(default=30, ge=1)`
  - `slow_op_threshold_ms: int = Field(default=5000, ge=0)`
  - `slow_op_top_n: int = Field(default=20, ge=1)`
- **REQ-002**: `PipelineConfig.observability:
  ObservabilityConfig = Field(default_factory=ObservabilityConfig)`.
  Existing YAMLs without an `observability:` block MUST keep
  validating (default values kick in).
- **REQ-003**: `system_metrics: true` in YAML MUST raise
  `ValidationError` with a message pointing to POST-MVP §2.

### Package layout

- **REQ-004**: A new top-level package
  `src/cmcourier/observability/` MUST contain:
  - `__init__.py` — re-exports public surface
  - `setup.py` — `configure(config, log_level)` entry point
  - `formatter.py` — `JsonFormatter` (one JSON object per record)
  - `pii.py` — `PiiMaskingFilter` (denylist mask)
  - `metrics.py` — `MetricsRecorder`, `StageTimer`, `BatchSummary`,
    `NetworkEvent`, `SlowOpAggregator`
- **REQ-005**: `src/cmcourier/cli/logging_setup.py` MUST become a
  thin shim that delegates to `observability.setup.configure(...)`.
  Existing `configure(level)` signature MUST remain callable for
  the smoke-test code path that doesn't have a full config (e.g.
  doctor's early load failure).

### Logger hierarchy

- **REQ-006**: The package MUST install named loggers:
  - `cmcourier` (root for application events) → app log handler
  - `cmcourier.metrics.pipeline` → metrics file handler
  - `cmcourier.metrics.network` → network file handler
  - `cmcourier.metrics.slow_ops` → slow-ops file handler (per
    batch — file path determined at batch start)
- **REQ-007**: Each handler MUST use the `JsonFormatter` when
  `log_format == "json"` and a text formatter otherwise. The
  metrics loggers MUST always be JSON regardless of `log_format`
  (the JSONL files are machine-parseable by design).
- **REQ-008**: The `cmcourier` root logger MUST keep an stderr
  handler so operators see live progress. `--log-level` controls
  this handler's level.

### File outputs

- **REQ-009**: `app-{YYYY-MM-DD}.log` — one record per line. Each
  line is a JSON object with at minimum: `ts` (ISO8601 UTC),
  `level`, `logger`, `msg`, plus any `extra` fields the caller
  passed.
- **REQ-010**: `metrics-{YYYY-MM-DD}.jsonl` — one record per batch
  close. Schema:
  ```json
  {"ts": "...", "kind": "batch_summary", "pipeline": "csv-trigger",
   "batch_id": "batch_001", "total_docs": 100, "elapsed_s": 60.2,
   "throughput_docs_per_s": 1.66,
   "stages": {"S0": {"count": 100, "p50_ms": 5.0, "p95_ms": 8.0,
                      "p99_ms": 12.0, "sum_ms": 600.0},
              "S1": {...}, ..., "S5": {...}}}
  ```
- **REQ-011**: `network-{YYYY-MM-DD}.jsonl` — one record per
  AS400 query or CMIS HTTP request. Schema:
  ```json
  {"ts": "...", "kind": "as400_query", "duration_ms": 12.4,
   "sql_prefix": "SELECT ...", "row_count": 4}
  {"ts": "...", "kind": "cmis_upload", "duration_ms": 543.0,
   "size_bytes": 102400, "status": 201, "url_prefix": "http://..."}
  {"ts": "...", "kind": "cmis_get", "duration_ms": 12.0,
   "status": 200, "url_prefix": "http://..."}
  ```
- **REQ-012**: `slow-ops-{batch_id}.jsonl` — one record per
  slow-op entry in the top-N. Schema:
  ```json
  {"rank": 1, "kind": "cmis_upload", "duration_ms": 5432.0,
   "txn_num": "TXN_042", "stage": "S5_UPLOAD",
   "size_bytes": 1048576}
  ```
  The file MUST be opened at batch start and finalized at batch
  close. Only events whose duration ≥ `slow_op_threshold_ms` are
  candidates; top-N by descending duration.

### PII masking

- **REQ-013**: A `PiiMaskingFilter` MUST be installed on every
  handler. Known PII fields (`cif`, `customer_name`,
  `account_number`, `nombre`, `pii_*`) MUST be redacted to
  `"***"` in both the `extra` dict and the formatted message.
- **REQ-014**: The filter MUST log NAMES of redacted fields but
  NEVER values. The redaction log line is itself emitted to the
  `cmcourier.observability` logger at DEBUG level for auditability.
- **REQ-015**: Constitution Principle VIII holds: tests MUST
  verify no PII value appears in any handler output.

### Orchestrator instrumentation

- **REQ-016**: `StagedPipeline.run` MUST emit a per-doc
  `stage_complete` event to the `cmcourier` logger at INFO with
  `extra={pipeline, stage, batch_id, txn_num, outcome,
  duration_ms}` for every stage transition (S0..S5).
- **REQ-017**: `StagedPipeline.run` MUST emit a batch summary to
  `cmcourier.metrics.pipeline` at batch close with the schema
  from REQ-010.
- **REQ-018**: `StagedPipeline.run` MUST emit slow-ops top-N to
  `cmcourier.metrics.slow_ops` at batch close with the schema
  from REQ-012.

### Network event emission

- **REQ-019**: `As400DataSource.query` and `query_stream` MUST
  emit a `cmcourier.metrics.network` event per request with
  `kind="as400_query"`, `duration_ms`, `sql_prefix` (≤80 chars),
  `row_count` (when known; `None` for streamed queries).
- **REQ-020**: `CmisUploader` HTTP request paths (`upload`,
  `ensure_folder`, `test_connection`, `get_type_definition`)
  MUST emit a `cmcourier.metrics.network` event per request
  with `kind` (`cmis_upload` / `cmis_post` / `cmis_get`),
  `duration_ms`, `size_bytes` (when applicable), `status` (HTTP
  code), `url_prefix` (≤80 chars).
- **REQ-021**: When `observability.network_metrics: false`, the
  emission MUST be skipped (no file handler, no event creation
  cost beyond a check).

### Doctor integration

- **REQ-022**: `cmcourier doctor` MUST add a new check
  `log_dir_writable` that verifies `observability.log_dir` exists
  (or can be created) and is writable. PASS / FAIL / SKIP
  semantics consistent with existing checks.

### Tests

- **REQ-023**: ≥5 schema tests cover the new
  `ObservabilityConfig` fields (defaults, system_metrics rejected
  if True, log_format invalid value rejected, all numeric ranges).
- **REQ-024**: ≥4 formatter/filter unit tests cover JSON output
  shape, PII masking, ts format, and text fallback.
- **REQ-025**: ≥3 metrics-aggregator unit tests cover stage
  timing percentiles, slow-ops top-N selection, throughput
  calculation.
- **REQ-026**: ≥3 integration tests verify end-to-end file
  emission: app log written, metrics line written at batch close,
  network events written for CMIS uploads.
- **REQ-027**: ≥1 PII regression test confirms no CIF / name
  value appears in any handler's output even when callers pass
  them in `extra`.
- **REQ-028**: ≥1 doctor test for `log_dir_writable`.

### Verification

- **REQ-029**: `pytest` MUST report ≥482 tests passing (current
  467 baseline + ~15 net new).
- **REQ-030**: `mypy src/cmcourier/` MUST report zero errors.
- **REQ-031**: Coverage on `observability/` MUST be ≥85%.

---

## 5. Acceptance scenarios

1. **Defaults apply**: A YAML without `observability:` block
   loads; `config.observability` has the defaults from §17.4.
2. **System metrics gate**: A YAML with
   `observability.system_metrics: true` is rejected at load time
   with a message pointing to POST-MVP §2.
3. **App log produced**: A pipeline run writes
   `./logs/app-2026-05-10.log` containing JSON Lines with one
   record per stage completion plus pipeline start/end events.
4. **Metrics line produced**: A pipeline run writes
   `./logs/metrics-2026-05-10.jsonl` with exactly one line for
   the batch, containing `stages.S0..S5` percentiles and
   throughput.
5. **Network events captured**: A pipeline run that uploads N
   documents to CMIS writes ≥N CMIS network events plus the
   trigger/indexing AS400 events (if applicable) to
   `network-{date}.jsonl`.
6. **Slow-ops filtered**: With `slow_op_threshold_ms=100`, only
   operations slower than 100ms appear in
   `slow-ops-{batch_id}.jsonl`; top-N sorted descending.
7. **PII never leaks**: An integration test passes a fake CIF
   value through `extra={"cif": "BAD"}`; the resulting file
   contains `"cif": "***"` and the value `"BAD"` appears nowhere.
8. **Disable kills file handlers**: With
   `observability.enabled: false`, no `./logs/` files are created;
   stderr handler still works.
9. **Doctor flags unwritable dir**: A YAML with
   `observability.log_dir: /no_perm/` makes
   `cmcourier doctor` exit 1 with a FAIL on `log_dir_writable`.
10. **JSON format on text formatters**: With `log_format: text`
    the app log is text; metrics/network/slow-ops files are
    still JSONL (always machine-readable).
11. **Throughput accuracy**: A 10-doc batch over 10 seconds
    yields `throughput_docs_per_s ≈ 1.0` in the metrics line
    (±5% tolerance for test stability).
12. **Network metrics off**: With `network_metrics: false`,
    `network-{date}.jsonl` is not created.
13. **Existing tests unaffected**: Current 467-test suite passes
    without modification; new tests are additive.

---

## 6. Out of scope (explicit)

- System metrics (`psutil` sampling) — POST-MVP §2
- Offline log analyzer — POST-MVP §3
- Live TUI dashboard — the spec
- Custom rotation/retention policies beyond `RotatingFileHandler`
- Per-environment log routing
- Log shipper integration (Splunk, ELK, Application Insights)
  beyond JSON Lines that any shipper can tail
- Existing log call rewrites — only new emit points and `extra`
  enrichment

---

## 7. Definitions

- **Tier**: a logical stream of observability data with its own
  file, format, and toggle. Tiers 1-4 ship in 020; tier 5 is
  POST-MVP.
- **PII**: Personally Identifiable Information — CIF, customer
  names, account numbers, anything that lets an outsider link a
  log record to a real person.
- **Slow op**: any operation whose `duration_ms ≥
  slow_op_threshold_ms`. Candidates aggregate per batch;
  top-N (sorted descending) ship to the slow-ops file.

---

## 8. References

- the spec — Observability
- the spec — pipeline stage definitions (S0..S6)
- POST-MVP §2 — System Metrics (deferred)
- POST-MVP §3 — Offline Log Analyzer (deferred)
- Constitution Principle VIII — PII discipline
- 012 — CLI + initial logging setup (this change extends)

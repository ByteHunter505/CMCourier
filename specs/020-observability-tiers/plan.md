# Plan — 020-observability-tiers

**Status**: Draft
**Spec**: `specs/020-observability-tiers/spec.md`

---

## 1. Architecture in one paragraph

A new top-level package `src/cmcourier/observability/` owns
formatter, PII filter, and metrics helpers. It's a peer to
adapters/services/orchestrators — used by all layers, configured
by the CLI. Python's stdlib `logging` is the transport: named
loggers route events to dedicated `RotatingFileHandler`s. The
JSON formatter renders structured records to JSON Lines. A
single `PiiMaskingFilter` runs on every handler. The orchestrator
emits per-stage events and a batch-close summary; adapters emit
network events. Slow ops aggregate in-memory per batch and flush
to disk at close.

---

## 2. Module layout

```
src/cmcourier/observability/
  __init__.py                # public re-exports: configure, MetricsRecorder, StageTimer
  setup.py                   # configure(config, log_level, *, batch_id=None)
  formatter.py               # JsonFormatter
  pii.py                     # PiiMaskingFilter (denylist), MASK
  metrics.py                 # MetricsRecorder, StageTimer, BatchSummary, NetworkEvent, SlowOpAggregator
src/cmcourier/cli/logging_setup.py     # shim that calls observability.setup.configure
src/cmcourier/config/schema.py         # ObservabilityConfig + PipelineConfig.observability
src/cmcourier/orchestrators/staged.py  # emit stage_complete events + batch summary
src/cmcourier/adapters/sources/as400.py        # emit network events
src/cmcourier/adapters/upload/cmis_uploader.py # emit network events
src/cmcourier/cli/doctor.py            # +log_dir_writable check
```

No new dependencies — everything stdlib (`logging`, `statistics`,
`time`, `pathlib`, `json`).

---

## 3. Public API contracts

### 3.1 `ObservabilityConfig`

```python
class ObservabilityConfig(BaseModel):
    model_config = _STRICT
    enabled: bool = True
    pipeline_metrics: bool = True
    network_metrics: bool = True
    system_metrics: bool = False
    log_dir: Path = Path("./logs")
    log_format: Literal["json", "text"] = "json"
    rotation_mb: int = Field(default=100, ge=1)
    retention_days: int = Field(default=30, ge=1)
    slow_op_threshold_ms: int = Field(default=5000, ge=0)
    slow_op_top_n: int = Field(default=20, ge=1)

    @field_validator("system_metrics")
    @classmethod
    def _reject_system_metrics(cls, v: bool) -> bool:
        if v:
            raise ValueError(
                "observability.system_metrics is post-MVP (see docs/roadmap/POST-MVP.md §2)"
            )
        return v
```

### 3.2 `observability.setup.configure`

```python
def configure(
    config: ObservabilityConfig,
    log_level: str,
    *,
    stderr_only: bool = False,
) -> None:
    """Install loggers, handlers, formatter, and PII filter.

    Idempotent: subsequent calls remove existing handlers first
    (matches the existing cli/logging_setup contract).

    ``stderr_only=True`` is the fallback path for `cmcourier doctor`
    early-load failures where we don't yet have a parsed config.
    """
```

### 3.3 `MetricsRecorder`

```python
class MetricsRecorder:
    """Per-batch metrics aggregator. Owned by the orchestrator."""

    def __init__(self, config: ObservabilityConfig) -> None: ...

    def start_batch(self, *, pipeline: str, batch_id: str) -> None:
        """Open per-batch state (slow-ops file, in-memory buckets)."""

    def record_stage(
        self,
        *,
        stage: str,
        batch_id: str,
        txn_num: str,
        duration_ms: float,
        outcome: str,
    ) -> None: ...

    def record_network(self, event: NetworkEvent) -> None: ...

    def close_batch(
        self,
        *,
        pipeline: str,
        batch_id: str,
        total_docs: int,
        elapsed_s: float,
    ) -> None:
        """Emit batch summary line + slow-ops top-N. Close per-batch files."""
```

### 3.4 `StageTimer`

```python
class StageTimer:
    """Context manager that times a stage and records via MetricsRecorder."""

    def __init__(
        self,
        recorder: MetricsRecorder,
        *,
        stage: str,
        batch_id: str,
        txn_num: str,
    ) -> None: ...

    def __enter__(self) -> StageTimer: ...
    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...
```

### 3.5 `NetworkEvent`

```python
@dataclass(frozen=True, slots=True)
class NetworkEvent:
    kind: str                # "as400_query" | "cmis_upload" | "cmis_post" | "cmis_get"
    duration_ms: float
    sql_prefix: str = ""     # only for as400_query
    row_count: int | None = None  # only for as400_query when known
    size_bytes: int | None = None # only for cmis_upload
    status: int | None = None     # only for cmis_*
    url_prefix: str = ""     # only for cmis_*
    txn_num: str = ""        # optional context
```

---

## 4. Algorithm sketches

### 4.1 JsonFormatter

```python
class JsonFormatter(logging.Formatter):
    def format(self, record: LogRecord) -> str:
        payload = {
            "ts": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Promote known extra fields from record.__dict__
        for key in _ALLOWED_EXTRA_FIELDS:
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__
            payload["exc_msg"] = str(record.exc_info[1])
        return json.dumps(payload, default=str, ensure_ascii=False)
```

`_ALLOWED_EXTRA_FIELDS = {"pipeline", "stage", "batch_id", "txn_num", "outcome", "duration_ms", "kind", "sql_prefix", "row_count", "size_bytes", "status", "url_prefix"}`.

### 4.2 PiiMaskingFilter

```python
_DENYLIST = frozenset({"cif", "customer_name", "account_number", "nombre", "name"})

class PiiMaskingFilter(logging.Filter):
    def filter(self, record: LogRecord) -> bool:
        masked: list[str] = []
        for key in list(record.__dict__):
            if key.lower() in _DENYLIST or key.lower().startswith("pii_"):
                record.__dict__[key] = "***"
                masked.append(key)
        # Mask formatted string too: rebuild msg if extras were redacted
        if masked:
            # Audit log (DEBUG only — names, not values)
            _audit.debug("pii_masked", extra={"fields": ",".join(sorted(masked))})
        return True  # always pass record through
```

### 4.3 BatchSummary aggregation

```python
@dataclass(slots=True)
class _StageBucket:
    durations_ms: list[float] = field(default_factory=list)

    def record(self, duration_ms: float) -> None:
        self.durations_ms.append(duration_ms)

    def summary(self) -> dict[str, float | int]:
        if not self.durations_ms:
            return {"count": 0, "p50_ms": 0.0, "p95_ms": 0.0,
                    "p99_ms": 0.0, "sum_ms": 0.0}
        sorted_ms = sorted(self.durations_ms)
        n = len(sorted_ms)
        return {
            "count": n,
            "p50_ms": _percentile(sorted_ms, 0.50),
            "p95_ms": _percentile(sorted_ms, 0.95),
            "p99_ms": _percentile(sorted_ms, 0.99),
            "sum_ms": sum(sorted_ms),
        }
```

`_percentile(sorted_list, q)` = nearest-rank percentile.

### 4.4 SlowOpAggregator

```python
class SlowOpAggregator:
    def __init__(self, *, threshold_ms: float, top_n: int) -> None:
        self._threshold_ms = threshold_ms
        self._top_n = top_n
        self._candidates: list[dict[str, Any]] = []

    def consider(self, *, kind: str, duration_ms: float, **fields) -> None:
        if duration_ms < self._threshold_ms:
            return
        self._candidates.append({"kind": kind, "duration_ms": duration_ms, **fields})

    def top(self) -> list[dict[str, Any]]:
        ranked = sorted(self._candidates, key=lambda d: d["duration_ms"], reverse=True)[: self._top_n]
        return [{"rank": i + 1, **entry} for i, entry in enumerate(ranked)]
```

### 4.5 Orchestrator instrumentation

In `StagedPipeline.run()`:
- At batch start: `recorder.start_batch(pipeline=self._pipeline_name, batch_id=batch_id)`
- Per stage transition: wrap in `with StageTimer(recorder, stage=..., batch_id=..., txn_num=...): ...`
- At batch close: `recorder.close_batch(pipeline=..., batch_id=..., total_docs=..., elapsed_s=...)`

The wrap is minimal — existing stage logic doesn't change, just the surrounding `with` block.

### 4.6 Adapter instrumentation

`As400DataSource.query`:
```python
def query(self, sql, params=None):
    t0 = time.monotonic()
    try:
        rows = ... # existing logic
        self._recorder.record_network(NetworkEvent(
            kind="as400_query",
            duration_ms=(time.monotonic() - t0) * 1000,
            sql_prefix=sql[:80],
            row_count=len(rows),
        ))
        return rows
    except _pyodbc_error_type() as exc:
        # also emit the network event (with row_count=None) on failure
        ...
```

But injecting `recorder` into every adapter is invasive. **Alternative**: emit via logger only. The adapter just calls:

```python
_network_log.info("as400_query", extra={
    "kind": "as400_query",
    "duration_ms": dms,
    "sql_prefix": sql[:80],
    "row_count": len(rows),
})
```

The `cmcourier.metrics.network` logger has the file handler. If `network_metrics: false`, the logger's effective level is set above INFO during `configure()` → no emission.

**Decision**: go with the **logger-only** approach. No constructor changes to adapters; the only edit is adding 1-2 lines per request path. `MetricsRecorder` is owned by the orchestrator for batch-level aggregation only. Slow-ops aggregation uses a custom `logging.Handler` that intercepts records from `cmcourier.metrics.network` and from a per-doc app event channel.

Actually simpler: at batch close, the recorder scans the JSONL files it owns (or its in-memory buffer). I'll keep slow-ops in-memory via a custom handler installed during `start_batch` that filters by threshold and accumulates.

### 4.7 Slow-ops collection via handler

```python
class _SlowOpHandler(logging.Handler):
    def __init__(self, aggregator: SlowOpAggregator) -> None:
        super().__init__(level=logging.INFO)
        self._agg = aggregator

    def emit(self, record: LogRecord) -> None:
        dms = getattr(record, "duration_ms", None)
        if dms is None:
            return
        self._agg.consider(
            kind=getattr(record, "kind", record.name),
            duration_ms=float(dms),
            txn_num=getattr(record, "txn_num", ""),
            stage=getattr(record, "stage", ""),
            size_bytes=getattr(record, "size_bytes", None),
        )
```

Attached at batch start to `cmcourier` and `cmcourier.metrics.network`. Detached at batch close.

---

## 5. Test plan

### 5.1 Schema (`tests/unit/config/test_schema.py`) — 5 tests

- defaults present
- system_metrics=True rejected with POST-MVP message
- log_format invalid rejected
- rotation_mb < 1 rejected
- existing YAMLs without observability still validate (regression)

### 5.2 Formatter + PII (`tests/unit/observability/test_formatter.py`) — 4 tests

- JSON record has ts/level/logger/msg + extras
- text formatter fallback
- PII denylist masks CIF
- PII allowed fields (txn_num, stage) pass through

### 5.3 Metrics helpers (`tests/unit/observability/test_metrics.py`) — 5 tests

- percentile correctness (small + odd-sized + edge cases)
- BatchSummary with empty stage returns zeros
- SlowOpAggregator filters by threshold
- SlowOpAggregator caps at top_n
- StageTimer records on __exit__ with outcome=FAIL on exception

### 5.4 Setup/wiring (`tests/integration/observability/test_setup.py`) — 4 tests

- configure() writes app log on INFO call
- configure() with enabled=False does not create log dir
- metrics handler emits to metrics-{date}.jsonl
- network handler emits to network-{date}.jsonl

### 5.5 End-to-end (`tests/integration/observability/test_pipeline_emits.py`) — 3 tests

- csv-trigger-pipeline run produces app log, metrics line, network events
- slow-ops file created with top-N entries when threshold met
- PII regression: extra={cif: "VAL"} → file contains "***", never "VAL"

### 5.6 Doctor (`tests/integration/cli/test_doctor.py`) — 1 test

- log_dir_writable check FAILs for unwritable dir

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..003 (schema) | §3.1 | §5.1 |
| REQ-004..008 (package, hierarchy) | §3.2, §3.3 | §5.4 |
| REQ-009..012 (file outputs) | §4.1, §4.3, §4.4 | §5.4, §5.5 |
| REQ-013..015 (PII) | §4.2 | §5.2, §5.5 |
| REQ-016..018 (orchestrator) | §4.5 | §5.5 |
| REQ-019..021 (network events) | §4.6 | §5.5 |
| REQ-022 (doctor) | §2 (new check) | §5.6 |
| REQ-023..028 (test counts) | §5 | all |
| REQ-029..031 (verification) | — | pytest/mypy |

---

## 7. Files touched

```
NEW   src/cmcourier/observability/__init__.py
NEW   src/cmcourier/observability/setup.py
NEW   src/cmcourier/observability/formatter.py
NEW   src/cmcourier/observability/pii.py
NEW   src/cmcourier/observability/metrics.py
EDIT  src/cmcourier/cli/logging_setup.py
EDIT  src/cmcourier/config/schema.py
EDIT  src/cmcourier/orchestrators/staged.py
EDIT  src/cmcourier/adapters/sources/as400.py
EDIT  src/cmcourier/adapters/upload/cmis_uploader.py
EDIT  src/cmcourier/cli/doctor.py
EDIT  src/cmcourier/cli/app.py            # call observability.configure with the parsed config
EDIT  tests/unit/config/test_schema.py
NEW   tests/unit/observability/test_formatter.py
NEW   tests/unit/observability/test_metrics.py
NEW   tests/integration/observability/test_setup.py
NEW   tests/integration/observability/test_pipeline_emits.py
EDIT  tests/integration/cli/test_doctor.py
EDIT  CHANGELOG.md
EDIT  README.md
NEW   specs/020-observability-tiers/{spec,plan,tasks}.md
```

---

## 8. Risks

- **R1**: Instrumenting `StagedPipeline.run()` is invasive — the
  current stage loop wraps a lot of logic. Mitigation: wrap the
  smallest possible block per stage (the per-doc call) in
  `with StageTimer(...)` and emit `stage_complete` at exit. No
  business logic changes.
- **R2**: `RotatingFileHandler` opens files at handler creation.
  Tests that run in `tmp_path` must use a per-test log dir or the
  handlers will write to a shared global location. Mitigation:
  every integration test passes `log_dir=tmp_path / "logs"` via
  the YAML; idempotent `configure()` reinstalls handlers per test.
- **R3**: PII masking on extras is fine, but the formatted message
  (`record.getMessage()`) can also embed PII via `%s`-style
  interpolation. Mitigation: the masking filter mutates `args`
  before `getMessage()` runs (Python's logging passes args
  through `record.getMessage()`). If the msg contains a literal
  CIF, that's a caller-side bug — we add a regex pass as a belt
  for known patterns (6-digit numeric on CIF position).
  **Decision**: redact only `extra` fields by name in 020;
  message-body regex scanning is over-engineering for MVP.
  Document the contract: callers pass PII via `extra={"cif": ...}`,
  never inline in the message.
- **R4**: Slow-ops handler runs on every record emitted to
  monitored loggers — overhead. Mitigation: the `consider()`
  method short-circuits if `duration_ms < threshold` (which is the
  common case). No allocation for non-slow records.
- **R5**: `cmcourier doctor` runs in environments where the log
  dir doesn't exist yet. The new check MUST attempt to create the
  dir (`mkdir parents=True, exist_ok=True`) and then test write —
  not just check existence. Mitigation: implement that order.
- **R6**: Existing 467 tests instantiate `configure(level)` (the
  old signature) via `cli/logging_setup.py`. The shim must accept
  this old form (no config arg) and fall back to stderr-only mode.
  Mitigation: `configure(level: str = "INFO")` keeps the old
  semantics; the new full-config entry point is
  `observability.setup.configure(config, level)`.
- **R7**: Logger-name pollution: if tests share state via the
  global `logging` root, one test's handlers can leak into the
  next. Mitigation: every test uses `configure_logging("INFO")`
  fresh, and the new setup function explicitly removes existing
  handlers on each call (already the contract).

---

## 9. Estimated effort

- Spec / plan / tasks: 60 min (done)
- Phase 1 (foundation + schema + formatter + pii + tier 1 + tests): 90 min
- Phase 2 (metrics aggregator + orchestrator instrumentation + tests): 90 min
- Phase 3 (network events from CMIS+AS400 + slow ops + doctor check + tests): 90 min
- Phase 4 (verification + docs + commit + merge): 30 min
- **Total**: ~5 h

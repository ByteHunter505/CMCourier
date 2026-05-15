# Spec — 017-single-doc-pipeline

**Status**: Draft
**Pipeline**: `single-doc` (the spec — debug / ad-hoc).
**Constitution alignment**: I (`SingleDocTriggerStrategy` implements
`S0Strategy`), III (the strategy is < 30 LOC, the CLI command body
≤ 50 lines), V (the trigger comes from CLI args, not config — the
config still drives every other adapter).

---

## 1. Intent

Ship the diagnostic pipeline from the spec:

> `single-doc` — `S1 → S2 → S3 → S4 → S5 → S7` (one
> shortname/system) — Debugging, ad-hoc operator pushes

Use case: an operator needs to migrate or re-process a specific
client's documents without scanning a full batch. The trigger comes
from CLI args; the rest of the pipeline is identical.

---

## 2. Scope

### In scope

- **`cmcourier.services.triggers.single_doc.SingleDocTriggerStrategy`**
  — new strategy that yields ONE `TriggerRecord` built from the
  CLI-provided `shortname`, `cif` (optional), and `system_id`.
- **`SingleDocTriggerConfig(kind: Literal["single_doc"])`** — schema
  member added to `TriggerConfigUnion`. NO extra fields. The kind
  tag exists purely so configs can declare "this YAML is intended
  for single-doc use". The trigger values themselves come from CLI
  args.
- **`build_pipeline(config, secrets, *, trigger_strategy_override=None)`**
  — new keyword argument. When provided, the wiring's normal
  trigger-strategy dispatch is bypassed.
- **`_build_trigger_strategy`** for `SingleDocTriggerConfig` raises
  `ConfigurationError("single_doc kind requires CLI trigger args; use 'cmcourier single-doc run' command")`.
  This prevents accidental misuse via the wrong command.
- **`cmcourier single-doc run`** new Click command:
  - `--config PATH` (required).
  - `--shortname TEXT` (required).
  - `--system TEXT` (required) — the trigger's system_id.
  - `--cif TEXT` (optional, default None — triggers CIF
    self-healing per the spec).
  - `--batch-id`, `--from-stage`, `--batch-size`, `--log-level`
    — same shape as other pipeline commands.
- **Doctor `_check_sample_dry_run` SKIPS** when
  `config.trigger.kind == "single_doc"` (the trigger comes from CLI
  args, so the doctor has nothing to dry-run against the YAML
  alone).
- Tests: ~5 unit tests for the strategy, ~2 schema tests, ~3 CLI
  tests, ~1 doctor test.

### Out of scope

- **`--txn-num` filter** to target a SPECIFIC RVABREP doc within
  the shortname's set. Today the pipeline processes ALL docs for
  the shortname (same as csv-trigger-pipeline). A txn-num filter
  is a small follow-up — needs an `IndexingService.find_one(txn_num)`
  method or post-S1 filtering.
- **Bulk trigger args** via `--triggers <csv>` for the single-doc
  command. If the operator has multiple triggers, they should use
  `csv-trigger-pipeline`.
- **Stream-from-stdin** for the trigger. CLI args are sufficient.
- **CLI flag aliases** (e.g., `-s` for `--shortname`). Long names
  only, for clarity.

---

## 3. Functional requirements (RFC 2119)

### Strategy

- **REQ-001** `SingleDocTriggerStrategy` MUST be a concrete
  `S0Strategy` subclass at
  `cmcourier.services.triggers.single_doc`.
- **REQ-002** Constructor signature:
  `SingleDocTriggerStrategy(shortname: str, system_id: str, cif: str | None = None)`.
  All three are required keyword arguments (well — `cif` has a
  None default).
- **REQ-003** `acquire(source_descriptor: str = "")` MUST yield
  exactly ONE `TriggerRecord(shortname=..., cif=..., system_id=...)`
  and stop.
- **REQ-004** `shortname` and `system_id` MUST be non-empty (the
  `TriggerRecord` dataclass already validates this).

### Schema

- **REQ-005** `SingleDocTriggerConfig` MUST be added with:
  ```python
  class SingleDocTriggerConfig(BaseModel):
      model_config = _STRICT
      kind: Literal["single_doc"]
  ```
  No additional fields.
- **REQ-006** `TriggerConfigUnion` MUST include
  `SingleDocTriggerConfig`.
- **REQ-007** `__all__` in `cmcourier.config.schema` MUST export
  `SingleDocTriggerConfig`.

### Wiring

- **REQ-008** `build_pipeline` signature MUST gain a keyword
  argument `trigger_strategy_override: S0Strategy | None = None`.
  When set, the wiring uses it instead of dispatching by
  `config.trigger.kind`.
- **REQ-009** `_build_trigger_strategy` for `SingleDocTriggerConfig`
  MUST raise `ConfigurationError("single_doc kind requires CLI
  trigger args", hint="use `cmcourier single-doc run` command")`.
  This branch is reachable only if `build_pipeline` is called
  without `trigger_strategy_override`.

### CLI

- **REQ-010** A new Click command `cmcourier single-doc run` MUST
  be added at the top level (sibling of the four pipeline groups).
- **REQ-011** Flags:
  - `--config PATH` (required).
  - `--shortname TEXT` (required).
  - `--system TEXT` (required).
  - `--cif TEXT` (default None).
  - `--batch-id TEXT` (default None).
  - `--from-stage INT` (default 1, range 1..5).
  - `--batch-size INT` (optional override).
  - `--log-level [DEBUG|INFO|WARNING|ERROR]` (default INFO).
- **REQ-012** Command body MUST:
  1. `configure_logging(log_level)`.
  2. `load_config(config_path)` + `load_secrets()`. Exit 2 on
     `ConfigurationError`.
  3. Verify `config.trigger.kind == "single_doc"`. Exit 2 on
     mismatch with a clear message.
  4. Build `SingleDocTriggerStrategy(shortname, system_id=system,
     cif=cif)` (None if empty).
  5. Build the pipeline via
     `build_pipeline(config, secrets, trigger_strategy_override=strategy)`.
  6. Call `pipeline.run(source_descriptor="", batch_size=...,
     batch_id=..., from_stage=...)`.
  7. Catch unhandled exceptions and exit 3.
  8. Print summary line and exit 0 / 1 per existing convention.

### Doctor

- **REQ-013** `_check_sample_dry_run` MUST return SKIP with
  `reason="trigger_kind_single_doc_requires_cli_args"` when
  `config.trigger.kind == "single_doc"`. The check does not attempt
  to build a pipeline for these configs.

### Logging discipline

- **REQ-014** The strategy's `acquire` method MUST NOT log the
  trigger's `cif` value. Yielding the TriggerRecord is silent.

---

## 4. Acceptance scenarios

### 4.1 Strategy yields exactly one trigger
- Given `SingleDocTriggerStrategy("TESTCLIENT01", "1", cif="123456")`.
- When `list(strategy.acquire())` is called.
- Then exactly one `TriggerRecord` is returned with the matching
  fields.

### 4.2 cif=None propagates
- Given `SingleDocTriggerStrategy("X", "1", cif=None)`.
- When `acquire` runs.
- Then the yielded `TriggerRecord.cif is None`.

### 4.3 Schema accepts kind=single_doc with no extra fields
- Given a YAML with `trigger: {kind: single_doc}` and everything
  else valid.
- When `load_config` runs.
- Then `config.trigger` is `SingleDocTriggerConfig`.

### 4.4 Schema rejects extra fields under single_doc kind
- Given a YAML with `trigger: {kind: single_doc, shortname: X}`.
- When `load_config` runs.
- Then a Pydantic validation error (extra="forbid").

### 4.5 build_pipeline rejects single_doc kind without override
- Given a `kind=single_doc` config + no trigger_strategy_override.
- When `build_pipeline(config, secrets)` is called.
- Then `ConfigurationError("single_doc kind requires CLI trigger args", ...)`.

### 4.6 build_pipeline with override succeeds
- Given a `kind=single_doc` config + a SingleDocTriggerStrategy
  override.
- When `build_pipeline(config, secrets, trigger_strategy_override=strategy)`
  is called.
- Then a `StagedPipeline` is returned; the strategy is the override
  instance.

### 4.7 CLI happy path
- Given a `kind=single_doc` YAML + `--shortname TESTCLIENT01
  --system 1 --cif 123456` + mocked CMIS.
- When `cmcourier single-doc run --config <yaml> --shortname X
  --system Y --cif Z`.
- Then exit 0; `s5_done >= 1` in stdout.

### 4.8 CLI without --cif (self-healing path)
- Given `--shortname TESTHEAL --system 1` (no `--cif`).
- When the command runs.
- Then the metadata service's CIF self-healing kicks in (since
  trigger.cif is None) — RVABREP.index2 supplies the CIF.
- And the CMIS upload's `BAC_CIF` property carries the healed
  value.

### 4.9 CLI rejects mismatched kind
- Given a YAML with `kind: csv`.
- When `cmcourier single-doc run --config <yaml> --shortname X
  --system Y`.
- Then exit 2; stderr names the mismatch.

### 4.10 Doctor SKIPs sample_dry_run for single_doc kind
- Given a YAML with `kind: single_doc`.
- When `cmcourier doctor --config <yaml>` runs.
- Then the `sample_dry_run` check returns SKIP with
  `reason="trigger_kind_single_doc_requires_cli_args"`.

---

## 5. Non-functional requirements

- **NFR-001** `cmcourier --help` MUST list SIX commands after 017:
  the four pipeline groups + `doctor` + `single-doc`. (The
  `single-doc` is a top-level command, not a group, because there's
  only one sub-action.)
- **NFR-002** Branch coverage on
  `services/triggers/single_doc.py` MUST be ≥ 90%.
- **NFR-003** Method length cap: every new method ≤ 50 lines.

---

## 6. Tooling expectations

- `ruff check`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean.
- `pre-commit run --all-files`: clean.
- `pytest`: full suite passes; ~11 net new tests.
- Smoke: `cmcourier single-doc --help` lists the flags.

---

## 7. Open questions / risks

- **Risk**: operators may try to use `single-doc run` against a
  `kind=csv` config out of habit. The exit-2-on-mismatch path
  surfaces this loudly. No silent fallback.
- **Risk**: `build_pipeline(config, secrets, *, trigger_strategy_override=...)`
  is a public function used by tests (wiring tests, doctor tests).
  Adding a keyword-only parameter is backwards-compatible.
- **Open question**: should the kind tag be `"single_doc"` or
  `"diagnostic"` or `"adhoc"`? **Resolved**: `single_doc` matches
  the spec's naming.
- **Open question**: should the command be `cmcourier single-doc
  run` (sub-command) or just `cmcourier single-doc <args>`?
  **Resolved**: sub-command for consistency with the other
  pipelines (`csv-trigger-pipeline run`, `rvabrep-pipeline run`,
  etc.). Single-doc-as-group also leaves room for future
  sub-commands (e.g., `single-doc inspect`).

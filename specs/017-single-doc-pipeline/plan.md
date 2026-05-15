# Plan — 017-single-doc-pipeline

**Status**: Draft
**Spec**: `specs/017-single-doc-pipeline/spec.md`

---

## 1. Architecture in one paragraph

One small strategy module + one schema member + one CLI command +
two narrow refactors (`build_pipeline` keyword arg,
`_check_sample_dry_run` SKIP branch). The strategy carries the
single trigger constructed from CLI args; the wiring layer accepts
a pre-built strategy via `trigger_strategy_override` to skip the
discriminator dispatch. The pipeline's stage chain runs unchanged.

---

## 2. Module layout

```
src/cmcourier/services/triggers/single_doc.py     # NEW
src/cmcourier/services/triggers/__init__.py        # re-export
src/cmcourier/config/schema.py                     # +SingleDocTriggerConfig
src/cmcourier/config/wiring.py                     # +override kwarg, +raise for single_doc
src/cmcourier/cli/app.py                           # +single-doc group + run command
src/cmcourier/cli/doctor.py                        # +SKIP branch in sample_dry_run
```

---

## 3. Public API contracts

### 3.1 `SingleDocTriggerStrategy`

```python
class SingleDocTriggerStrategy(S0Strategy):
    """the spec single-doc pipeline.

    Yields exactly one TriggerRecord built from caller-provided
    shortname, system_id, and optional cif.
    """

    def __init__(
        self,
        shortname: str,
        system_id: str,
        cif: str | None = None,
    ) -> None: ...

    def acquire(self, source_descriptor: str = "") -> Iterator[TriggerRecord]: ...
```

### 3.2 `SingleDocTriggerConfig`

```python
class SingleDocTriggerConfig(BaseModel):
    model_config = _STRICT
    kind: Literal["single_doc"]
```

### 3.3 `build_pipeline`

```python
def build_pipeline(
    config: PipelineConfig,
    secrets: Secrets,
    *,
    trigger_strategy_override: S0Strategy | None = None,
) -> StagedPipeline:
    ...
    rvabrep_src = TabularDataSource(config.indexing.csv_path)
    ...
    indexing_service = IndexingService(rvabrep_src, ...)
    trigger_strategy = (
        trigger_strategy_override
        or _build_trigger_strategy(config, secrets, rvabrep_src, indexing_service)
    )
    ...
```

### 3.4 CLI

```python
@main.group(name="single-doc")
def single_doc_group() -> None:
    """single-doc subcommands (the spec — debug / ad-hoc)."""


@single_doc_group.command(name="run")
@click.option("--config", "config_path", type=click.Path(...), required=True)
@click.option("--shortname", type=str, required=True)
@click.option("--system", type=str, required=True)
@click.option("--cif", type=str, default=None)
@click.option("--batch-id", type=str, default=None)
@click.option("--from-stage", type=click.IntRange(1, 5), default=1)
@click.option("--batch-size", type=click.IntRange(min=1), default=None)
@click.option("--log-level", type=click.Choice(_LOG_LEVELS, case_sensitive=False), default="INFO")
def single_doc_run_command(...): ...
```

Body extracts a private helper if it grows past 50 lines.

---

## 4. Algorithm sketches

### 4.1 Strategy

```python
class SingleDocTriggerStrategy(S0Strategy):
    def __init__(self, shortname, system_id, cif=None):
        self._trigger = TriggerRecord(
            shortname=shortname,
            cif=cif if cif else None,
            system_id=system_id,
        )

    def acquire(self, source_descriptor=""):
        del source_descriptor
        yield self._trigger
```

### 4.2 CLI command body

```python
def single_doc_run_command(config_path, shortname, system, cif, ...):
    configure_logging(log_level)
    try:
        config = load_config(config_path)
        secrets = load_secrets()
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

    actual_kind = getattr(config.trigger, "kind", "<unknown>")
    if actual_kind != "single_doc":
        click.echo(
            f"ConfigurationError: single-doc run expects trigger.kind='single_doc'; "
            f"config has kind={actual_kind!r}",
            err=True,
        )
        sys.exit(2)

    strategy = SingleDocTriggerStrategy(
        shortname=shortname,
        system_id=system,
        cif=cif or None,
    )
    try:
        pipeline = build_pipeline(config, secrets, trigger_strategy_override=strategy)
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)

    config = _apply_overrides(config, triggers_override=None, batch_size=batch_size)
    try:
        report = pipeline.run(
            source_descriptor="",
            batch_size=config.batch_size,
            batch_id=batch_id,
            from_stage=from_stage,
        )
    except Exception:
        _log.exception("single-doc run failed unexpectedly")
        sys.exit(3)

    _emit_summary(report)
    sys.exit(0 if report.s5_failed == 0 else 1)
```

### 4.3 Doctor SKIP

In `_check_sample_dry_run`, before constructing the pipeline:

```python
def _check_sample_dry_run(config, secrets):
    if isinstance(config.trigger, SingleDocTriggerConfig):
        return _skip(
            "sample_dry_run",
            "trigger_kind_single_doc_requires_cli_args",
        )
    ...existing logic...
```

---

## 5. Test plan

### 5.1 `tests/unit/services/test_trigger_strategies.py` (~5 new tests)

A `TestSingleDocStrategy` class:
- yields exactly one trigger with the configured fields
- cif=None propagates correctly
- empty-string cif → None (treated same as None)
- is an S0Strategy
- shortname empty → TriggerRecord raises (existing dataclass
  validation kicks in)

### 5.2 `tests/unit/config/test_schema.py` (~2 new tests)

- kind=single_doc loads to SingleDocTriggerConfig
- extra fields under kind=single_doc rejected

### 5.3 `tests/integration/config/test_wiring.py` (~2 new tests)

- build_pipeline(config, secrets) raises for kind=single_doc
  without override
- build_pipeline(config, secrets, trigger_strategy_override=...)
  succeeds with single_doc kind

### 5.4 `tests/integration/cli/test_pipeline_kinds.py` (~3 new tests)

A `TestSingleDocPipeline` class:
- `single-doc run --help` lists flags
- happy path with mocked CMIS
- mismatched kind exits 2

### 5.5 `tests/integration/cli/test_doctor.py` (~1 new test)

- Doctor's sample_dry_run check returns SKIP when
  `trigger.kind="single_doc"`.

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..004 (strategy) | §3.1, §4.1 | TestSingleDocStrategy |
| REQ-005..007 (schema) | §3.2 | test_schema |
| REQ-008..009 (wiring) | §3.3 | test_wiring |
| REQ-010..012 (CLI) | §3.4, §4.2 | TestSingleDocPipeline |
| REQ-013 (doctor SKIP) | §4.3 | test_doctor |
| REQ-014 (logging) | §4.1 | implicit; visual review |

---

## 7. Files touched

```
NEW   src/cmcourier/services/triggers/single_doc.py
EDIT  src/cmcourier/services/triggers/__init__.py
EDIT  src/cmcourier/config/schema.py
EDIT  src/cmcourier/config/wiring.py
EDIT  src/cmcourier/cli/app.py
EDIT  src/cmcourier/cli/doctor.py
EDIT  tests/unit/services/test_trigger_strategies.py
EDIT  tests/unit/config/test_schema.py
EDIT  tests/integration/config/test_wiring.py
EDIT  tests/integration/cli/test_pipeline_kinds.py
EDIT  tests/integration/cli/test_doctor.py
EDIT  CHANGELOG.md
EDIT  README.md
NEW   specs/017-single-doc-pipeline/{spec,plan,tasks}.md
```

No new dependencies. No new test fixtures.

---

## 8. Risks

- **Risk**: `build_pipeline(config, secrets, *, trigger_strategy_override=...)`
  is called from `tests/integration/config/test_wiring.py` and from
  `cli/doctor.py`'s `_check_sample_dry_run`. Adding a keyword-only
  parameter with a default doesn't break callers. Verified.
- **Risk**: the CLI command must NOT pass `triggers_override` to
  `_apply_overrides` because single-doc has no CSV override
  concept. The helper handles `triggers_override=None` correctly
  (existing behavior).
- **Risk**: the doctor's sample_dry_run currently builds the
  pipeline via `build_pipeline(config, secrets)` (no override).
  For `kind=single_doc` this would raise. The new SKIP branch
  short-circuits BEFORE the build, preventing the FAIL.

---

## 9. Estimated effort

- Spec / plan / tasks: done
- Phase 1 (strategy + schema + ~7 tests): 60 min
- Phase 2 (wiring + CLI + doctor + ~6 tests): 60 min
- Phase 3 (verification + smoke): 20 min
- Phase 4 (docs + commit + merge): 20 min
- **Total**: ~2 h 40 min

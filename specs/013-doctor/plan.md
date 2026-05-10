# Plan — 013-doctor

**Status**: Draft
**Spec**: `specs/013-doctor/spec.md`

---

## 1. Architecture in one paragraph

One new module `cmcourier/cli/doctor.py` houses `CheckStatus`,
`CheckResult`, `DoctorReport`, and `run_doctor(config, secrets)`. Each
of the 6 checks is a private function `_check_<name>` returning a
`CheckResult`. `run_doctor` runs them in a fixed order and catches any
exception each function emits — none propagate. The CLI adds one
top-level command at `cmcourier.cli.app` that wires the report to
stdout and exits 0/1/2/3. The `IUploader` port gains
`get_type_definition`; `CmisUploader` implements it as a single GET
that bypasses the retry loop (pre-flight prefers fail-loud).

---

## 2. Module layout

```
src/cmcourier/cli/doctor.py
├── CheckStatus            # enum.StrEnum
├── CheckResult            # frozen+slots dataclass
├── DoctorReport           # frozen+slots dataclass with summary props
├── run_doctor(config, secrets) -> DoctorReport
├── _check_cmis_connectivity(config, secrets) -> CheckResult
├── _check_tracking_openable(config) -> CheckResult
├── _check_mapping_completeness(config) -> CheckResult
├── _check_metadata_sources(config) -> CheckResult
├── _check_cm_type_alignment(config, secrets, uploader) -> CheckResult
└── _check_sample_dry_run(config, secrets) -> CheckResult
```

Plus edits to `cmcourier/cli/app.py` (new `@main.command("doctor")`)
and `cmcourier/domain/ports.py` (new abstract method) and
`cmcourier/adapters/upload/cmis_uploader.py` (new implementation).

---

## 3. Public API contracts

### 3.1 `CheckStatus`

```python
class CheckStatus(enum.StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"
```

### 3.2 `CheckResult` / `DoctorReport`

```python
@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    details: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}),
    )


@dataclass(frozen=True, slots=True)
class DoctorReport:
    results: tuple[CheckResult, ...]
    elapsed_seconds: float

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.FAIL)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.PASS)

    @property
    def warn_count(self) -> int: ...

    @property
    def skip_count(self) -> int: ...

    @property
    def has_failures(self) -> bool:
        return self.failed_count > 0
```

### 3.3 `IUploader.get_type_definition`

```python
class IUploader(ABC):
    ...
    @abstractmethod
    def get_type_definition(self, object_type_id: str) -> Mapping[str, Any]:
        """Return the CMIS typeDefinition for *object_type_id*.

        Raises:
            CMISClientError: 4xx (typically 404 for missing types).
            CMISServerError: 5xx.
        """
```

### 3.4 `CmisUploader.get_type_definition`

```python
def get_type_definition(self, object_type_id: str) -> Mapping[str, Any]:
    if not self._warm:
        self._warmup_session()
    url = f"{self._cfg.base_url}/{self._cfg.repo_id}"
    resp = self._session.get(
        url,
        params={"cmisselector": "typeDefinition", "typeId": object_type_id},
        timeout=self._cfg.timeout_seconds,
    )
    body = _truncate(resp.text)
    if resp.status_code >= 500:
        raise CMISServerError(status_code=resp.status_code, response_body=body)
    if resp.status_code >= 400:
        raise CMISClientError(status_code=resp.status_code, response_body=body)
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
```

---

## 4. Algorithm sketches

### 4.1 `run_doctor`

```python
def run_doctor(config, secrets):
    start = time.monotonic()
    results: list[CheckResult] = []
    results.append(_check_cmis_connectivity(config, secrets))
    results.append(_check_tracking_openable(config))
    results.append(_check_mapping_completeness(config))
    results.append(_check_metadata_sources(config))
    # The two next checks need a working uploader. If connectivity
    # failed, we SKIP them instead of crashing.
    cmis_ok = results[0].status == CheckStatus.PASS
    if cmis_ok:
        uploader = _build_uploader(config, secrets)
        results.append(_check_cm_type_alignment(config, uploader))
    else:
        results.append(_skip("cm_type_alignment", "cmis_connectivity FAILed"))
    results.append(_check_sample_dry_run(config, secrets))
    return DoctorReport(
        results=tuple(results),
        elapsed_seconds=time.monotonic() - start,
    )
```

### 4.2 Each `_check_*` shape

```python
def _check_cmis_connectivity(config, secrets):
    try:
        uploader = _build_uploader(config, secrets)
        info = uploader.test_connection()
        if not info.get("repository_id"):
            return CheckResult(
                name="cmis_connectivity",
                status=CheckStatus.FAIL,
                message="CMIS returned empty repository_id",
                details=_frozen({"base_url": config.cmis.base_url}),
            )
        return CheckResult(
            name="cmis_connectivity",
            status=CheckStatus.PASS,
            message=f"CMIS reachable at {config.cmis.base_url}",
            details=_frozen({"repository_id": info["repository_id"]}),
        )
    except Exception as exc:  # noqa: BLE001 — doctor catches all
        return _fail("cmis_connectivity", exc, {"base_url": config.cmis.base_url})
```

Same shape for the other checks. `_fail(name, exc, base_details)` is a
helper that builds the FAIL CheckResult with `exc_type` and `error`
in `details`.

### 4.3 `_check_sample_dry_run`

```python
def _check_sample_dry_run(config, secrets):
    # Build only the services we need; don't construct the full pipeline.
    try:
        adapters = _build_dry_run_adapters(config, secrets)
    except Exception as exc:
        return _fail("sample_dry_run", exc, {"stage": "construction"})

    try:
        triggers = list(adapters.trigger_strategy.acquire(str(config.trigger.csv_path)))
    except Exception as exc:
        return _fail("sample_dry_run", exc, {"stage": "S0"})
    if not triggers:
        return CheckResult(
            name="sample_dry_run",
            status=CheckStatus.SKIP,
            message="trigger CSV is empty — nothing to dry-run",
            details=_frozen({"reason": "no_triggers"}),
        )

    trigger = triggers[0]
    docs = _try("S1", lambda: adapters.indexing.find_documents(trigger))
    if isinstance(docs, CheckResult):
        return docs
    if not docs:
        return CheckResult(
            name="sample_dry_run",
            status=CheckStatus.SKIP,
            message="first trigger had no documents",
            details=_frozen({"reason": "no_docs", "trigger": trigger.shortname}),
        )

    doc = docs[0]
    mapping = _try("S2", lambda: adapters.mapping.get_mapping(doc.index7))
    if isinstance(mapping, CheckResult):
        return mapping
    resolution = _try("S3", lambda: adapters.metadata.resolve(trigger, doc, mapping))
    if isinstance(resolution, CheckResult):
        return resolution
    staged = _try("S4", lambda: adapters.assembler.assemble(doc))
    if isinstance(staged, CheckResult):
        return staged
    # Clean up the staged PDF so doctor leaves no artifacts.
    try:
        staged.path.unlink(missing_ok=True)
    except OSError:
        pass
    return CheckResult(
        name="sample_dry_run",
        status=CheckStatus.PASS,
        message=f"S1-S4 dry-run OK for {doc.txn_num}",
        details=_frozen({"txn_num": doc.txn_num, "stages": "S1,S2,S3,S4"}),
    )
```

`_try(stage_name, fn)` is a helper that runs `fn()` and returns either
the result OR a `CheckResult(FAIL)` carrying the stage name + exception.

`_build_dry_run_adapters` is a tiny helper that opens only the
services / adapters needed for stages S1-S4 — it does NOT open the
tracking store (already checked) or the uploader (S5 is out of scope).

### 4.4 CLI command body

```python
@main.command(name="doctor")
@click.option("--config", "config_path", type=click.Path(...), required=True)
@click.option("--log-level", type=click.Choice([...]), default="INFO")
def doctor_command(config_path, log_level):
    configure_logging(log_level)
    try:
        config = load_config(Path(config_path))
        secrets = load_secrets()
    except ConfigurationError as exc:
        click.echo(f"ConfigurationError: {exc}", err=True)
        sys.exit(2)
    try:
        report = run_doctor(config, secrets)
    except Exception:
        _log.exception("doctor crashed unexpectedly")
        sys.exit(3)
    _emit_report(report)
    sys.exit(1 if report.has_failures else 0)


def _emit_report(report):
    for result in report.results:
        click.echo(f"[{result.status.value}] {result.name} — {result.message}")
        for key, value in result.details.items():
            click.echo(f"    {key}={value}")
    click.echo(
        f"{report.passed_count} passed, {report.failed_count} failed, "
        f"{report.warn_count} warnings, {report.skip_count} skipped "
        f"in {report.elapsed_seconds:.2f}s"
    )
```

---

## 5. Test plan

### 5.1 Tests in `tests/integration/cli/test_doctor.py`

~12 tests:

| Group | Tests | Acceptance scenarios |
|-------|-------|----------------------|
| `TestRunDoctorHappyPath` | 2 | 4.1, 4.12 (order stable) |
| `TestCmisFailures` | 1 | 4.2 |
| `TestTrackingFailures` | 1 | 4.3 |
| `TestMappingWarn` | 1 | 4.4 |
| `TestMetadataWarn` | 1 | 4.5 |
| `TestCmTypeMissing` | 1 | 4.6 |
| `TestSampleDryRun` | 2 | 4.7, 4.8 |
| `TestCli` | 3 | 4.9, 4.10, 4.11 |

### 5.2 Tests in `tests/integration/adapters/test_cmis_uploader.py`

~3 new tests for `get_type_definition`:
- 200 → returns the parsed dict.
- 404 → raises `CMISClientError(status_code=404)`.
- 500 → raises `CMISServerError(status_code=500)`.

### 5.3 Tests in `tests/unit/domain/test_ports.py`

- Update `TestIUploaderContract` to include `get_type_definition` in
  the abstract-method set.

### 5.4 Helpers

Reuse the YAML builder from the existing CLI tests
(`tests/integration/cli/test_cli.py`). Extract a shared helper into
`tests/integration/cli/conftest.py` if duplicated.

`responses` stubs: each test registers:
- GET repositoryInfo (warmup) → 200
- GET typeDefinition?typeId=X → 200/404 as needed
- (For dry-run S4 tests: nothing — S4 is local filesystem.)

---

## 6. Verification matrix

| Spec REQ | Plan section | Test(s) |
|----------|--------------|---------|
| REQ-001..003 (port + uploader) | §3.3, §3.4 | test_cmis_uploader, test_ports |
| REQ-004..008 (doctor types) | §3.1, §3.2, §4.1 | TestRunDoctorHappyPath |
| REQ-009..014 (checks) | §4.2, §4.3 | all check tests |
| REQ-015..018 (CLI) | §4.4 | TestCli |
| REQ-019..020 (logging) | §4.2 (helpers strip secrets) | implicit |
| NFR-002 (coverage) | — | `pytest --cov` |
| NFR-003 (50-line cap) | — | visual review |

---

## 7. Files touched

```
NEW   src/cmcourier/cli/doctor.py
EDIT  src/cmcourier/cli/app.py                # +doctor command
EDIT  src/cmcourier/domain/ports.py           # +get_type_definition
EDIT  src/cmcourier/adapters/upload/cmis_uploader.py  # +method
EDIT  tests/unit/domain/test_ports.py         # +abstract name
EDIT  tests/integration/adapters/test_cmis_uploader.py  # +3 tests
NEW   tests/integration/cli/test_doctor.py
EDIT  tests/integration/cli/conftest.py       # shared YAML builder
EDIT  CHANGELOG.md                            # [0.15.0]
EDIT  README.md                               # Status checklist
NEW   specs/013-doctor/{spec,plan,tasks}.md
```

No new dependencies.

---

## 8. Risks

- **Risk**: doctor invocations during integration tests that import
  `responses` MUST register the typeDefinition endpoint per type;
  forgetting one causes a `ConnectionError` mid-check. Mitigation:
  the harness's `_register_cmis_for_doctor()` helper registers
  every distinct type up front, mirroring the prod CMIS contract.
- **Risk**: the CM type alignment check is O(N) HTTP calls per
  unique type in mapping. For the existing fixture (~7 distinct types
  after dedup) this is ~7 calls per doctor run — fast. For prod with
  hundreds of types, doctor takes seconds. Acceptable.
- **Risk**: dry-run S4 writes a PDF to disk, then deletes it. If the
  test's `temp_dir` is not under `tmp_path`, leftover files
  accumulate. Mitigation: every test uses `tmp_path` as `temp_dir`;
  the unlink in the check is best-effort cleanup.
- **Risk**: `_warmup_session` is called from both `test_connection`
  and `get_type_definition`. Both pass through the same idempotency
  flag (`_warm`). Concurrent doctor invocations on the same uploader
  would race — but doctor is sequential, so no contention.

---

## 9. Estimated effort

- Spec / plan / tasks: done
- Phase 1 (port amendment + uploader method + 3 tests): 40 min
- Phase 2 (doctor module + 6 checks + ~10 tests): 90 min
- Phase 3 (CLI command + 3 tests): 30 min
- Phase 4 (verification + docs + commit + merge): 25 min
- **Total**: ~3 h 25 min

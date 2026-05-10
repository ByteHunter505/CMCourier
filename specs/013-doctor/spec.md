# Spec — 013-doctor

**Status**: Draft
**Command**: `cmcourier doctor --config <yaml>` (REBIRTH §10.5).
**Constitution alignment**: V (config validated upfront), VIII
(credentials read once, never echoed), III (single-responsibility per
check function).

---

## 1. Intent

Ship `cmcourier doctor` — the operator's pre-flight check that
validates a configuration before the first real `csv-trigger-pipeline
run`. Today, a mis-configured pipeline fails 5-30 seconds in, after
side effects have started. Doctor moves every reachable failure to the
front: an exit code in under 5 seconds, with a structured report
naming the specific check that failed.

REBIRTH §10.5 lists 5 check classes. 013 ships all 5 (per user
direction):

1. **Connectivity** — CMIS reachable, repo_id valid, JSESSIONID
   warmup OK. (AS400 reachability deferred — no adapter yet.)
2. **Mapping completeness** — Modelo Documental has at least one row,
   and every `cm_object_type` it references corresponds to a real CMIS
   type (check 5 below covers this).
3. **CM type alignment** — for every distinct `cm_object_type` in the
   Modelo Documental, the CMIS server returns a valid
   `getTypeDefinition` response.
4. **Metadata source health** — every CSV metadata source has at
   least one row; every field's `default_value` (if set) passes its
   own validation regex.
5. **Sample dry-run** — exercise S1→S4 on the first trigger that
   resolves to a doc, without uploading. Surfaces missing page files /
   broken assembly early.

Plus structural checks not in §10.5 but free to add:

6. **Tracking store openable** — `SQLiteTrackingStore(...)` can open
   the configured `db_path` (creates parent dir if needed).

---

## 2. Scope

### In scope

- `cmcourier.cli.doctor` module with:
  - `CheckStatus` (`enum.StrEnum`): `PASS`, `FAIL`, `WARN`, `SKIP`.
  - `CheckResult` (frozen): `name`, `status`, `message`, optional
    `details` dict.
  - `DoctorReport` (frozen): `results: tuple[CheckResult, ...]`,
    `elapsed_seconds: float`. Properties `failed_count`, `passed_count`,
    `has_failures`.
  - `run_doctor(config, secrets) -> DoctorReport` — runs every check
    in order, returns the report.
- **`IUploader.get_type_definition(object_type_id: str) -> Mapping[str, Any]`**
  — new abstract method. `CmisUploader` implements via
  `GET {base_url}/{repo_id}?cmisselector=typeDefinition&typeId=<id>`.
  Returns the parsed JSON dict on 2xx. Raises `CMISClientError` on
  404 (type missing) or other 4xx; raises `CMISServerError` on 5xx.
- **CLI command** `cmcourier doctor --config <yaml> [--log-level X]`.
  Output: text report with one line per check (`[PASS] check_name —
  message`), a summary line (`N passed, M failed, K warnings, L
  skipped`), and exit code 0 (all PASS/WARN/SKIP) or 1 (any FAIL).
- 6 checks per §1 above, each implemented as a private function
  `_check_<name>(config, secrets, ...) -> CheckResult`.
- ~10 integration tests covering the happy path + at least one failure
  per check.

### Out of scope

- AS400 connectivity (no adapter yet — check 1 reports SKIP for AS400).
- JSON output flag (text-only for MVP; CI integrators can parse the
  summary line).
- `cmcourier <pipeline> run --skip-doctor` flag (deferred — the run
  command doesn't auto-invoke doctor; operators run them separately).
- Per-batch doctor (REBIRTH §10.5 mentions doctor can run against an
  arbitrary batch; 013 only runs against the config, not a specific
  trigger CSV). Per-trigger CMIS getTypeDefinition iteration is covered
  by check 3 across the full mapping.
- Caching `getTypeDefinition` responses (each check is one-shot —
  doctor runs in seconds either way).
- Verbose / quiet flags (one verbosity level via `--log-level`).

---

## 3. Functional requirements (RFC 2119)

### Port amendment

- **REQ-001** `IUploader` MUST gain an abstract method
  `get_type_definition(self, object_type_id: str) -> Mapping[str, Any]`.
  `CmisUploader` MUST implement it; `tests/unit/domain/test_ports.py`
  MUST be updated to include the new abstract method.
- **REQ-002** `CmisUploader.get_type_definition` MUST:
  - Run `_warmup_session()` first if not already warm.
  - Issue `GET {base_url}/{repo_id}?cmisselector=typeDefinition&typeId=<id>`.
  - Use the session's existing timeout.
  - On 2xx with JSON body: return the parsed dict (or `{}` if the
    body is not a dict).
  - On 404: raise `CMISClientError(status_code=404, response_body=...)`.
  - On other 4xx: raise `CMISClientError` with the status.
  - On 5xx: raise `CMISServerError` with the status.
- **REQ-003** `CmisUploader.get_type_definition` MUST NOT participate
  in the retry loop. Doctor calls it once per type — retries are not
  necessary for a pre-flight check (a transient 5xx is worth surfacing
  as a FAIL, not silently retrying).

### Doctor module

- **REQ-004** `CheckStatus` MUST be `enum.StrEnum` with values
  `PASS`, `FAIL`, `WARN`, `SKIP`.
- **REQ-005** `CheckResult` MUST be a `frozen=True, slots=True`
  dataclass with `name: str`, `status: CheckStatus`, `message: str`,
  `details: Mapping[str, str] = MappingProxyType({})`. The `details`
  default MUST be an immutable mapping.
- **REQ-006** `DoctorReport` MUST be a `frozen=True, slots=True`
  dataclass with `results: tuple[CheckResult, ...]` and
  `elapsed_seconds: float`. Properties: `failed_count` (count of FAIL),
  `passed_count` (count of PASS), `has_failures` (any FAIL).
- **REQ-007** `run_doctor(config, secrets) -> DoctorReport` MUST
  invoke the 6 checks in the order listed in §1, capturing
  `time.monotonic()` deltas around the whole flow.
- **REQ-008** Every check function MUST handle its own exceptions and
  return a FAIL `CheckResult` with the exception type + message in
  `details`. No exception MUST propagate out of `run_doctor`.

### Checks

- **REQ-009** **`_check_cmis_connectivity`**: build the `CmisUploader`
  from `(config.cmis, secrets)`, call `uploader.test_connection()`.
  PASS if the returned mapping has `repository_id` non-empty. FAIL if
  any exception. `details` includes the resolved `base_url` (NOT
  credentials).
- **REQ-010** **`_check_tracking_openable`**: open
  `SQLiteTrackingStore(config.tracking.db_path)` and immediately close.
  PASS if no exception. FAIL otherwise. `details` includes
  `db_path`.
- **REQ-011** **`_check_mapping_completeness`**: load
  `MappingService` from `config.mapping`, assert `count() >= 1`.
  PASS if ≥1 mappings. WARN with `mapping_count=0` if zero (no
  pipeline could run, but a fresh project might still be valid).
- **REQ-012** **`_check_metadata_sources`**: for each
  `MetadataSourceConfig` in `config.metadata.sources`, open a
  `TabularDataSource` and call `count()`. PASS if every source has
  ≥1 rows; WARN with the empty-source aliases listed if any source
  has 0 rows. FAIL if any source raises on `count()`.
- **REQ-013** **`_check_cm_type_alignment`**: iterate every mapping
  via `MappingService.get_all()`; collect the distinct
  `cm_object_type`s; for each, call
  `uploader.get_type_definition(...)`. PASS if every type resolves.
  FAIL listing each missing type. The check MUST short-circuit at
  the first missing type? — no, surface ALL missing types so the
  operator fixes them in one round-trip. `details` carries the list
  of missing types.
- **REQ-014** **`_check_sample_dry_run`**: build the full adapter
  graph via `build_pipeline`, take the FIRST trigger from the
  trigger CSV, manually walk S1 (`indexing.find_documents`) → S2
  (`mapping.get_mapping`) → S3 (`metadata.resolve`) → S4
  (`assembler.assemble`). PASS if all four stages succeed for the
  first emitted doc. SKIP if the trigger CSV emits zero docs (the
  doctor cannot dry-run nothing). FAIL with the failing stage name
  and exception detail otherwise. The S4 staged PDF MUST be deleted
  on success to avoid leaving artifacts behind.

### CLI command

- **REQ-015** The Click root group MUST gain a `doctor` command at
  the top level (sibling of `csv-trigger-pipeline`).
- **REQ-016** Flags: `--config PATH` (required),
  `--log-level [DEBUG|INFO|WARNING|ERROR]` (default INFO).
- **REQ-017** The command MUST:
  1. `configure_logging(log_level)`.
  2. `load_config(config_path)` / `load_secrets()`, exit 2 on
     `ConfigurationError`.
  3. Call `run_doctor(config, secrets)`.
  4. Print each `CheckResult` as `[STATUS] name — message` to
     stdout; if `details` is non-empty, print indented key=value lines.
  5. Print a summary line `N passed, M failed, K warnings, L skipped
     in T.TTs`.
  6. Exit 0 if `report.has_failures` is False, else exit 1.
- **REQ-018** Any unhandled exception MUST be caught, logged at ERROR
  (with stack), and the command MUST exit 3.

### Logging discipline (Constitution VIII)

- **REQ-019** No `CheckResult.message` or `details` MUST contain
  resolved property VALUES (CIF, Nombre_Cliente). Operational keys
  (`base_url`, `db_path`, mapping counts, missing type ids) are OK.
- **REQ-020** Credentials MUST NOT appear in any check output — not
  even the `cmis_username` (which is `Secrets.cmis_username`, kept
  out of `details`).

---

## 4. Acceptance scenarios

### 4.1 Happy path — all checks pass
- Given a valid config + secrets + CMIS mocked to return 200 on
  warmup and typeDefinition.
- When `run_doctor(config, secrets)` is called.
- Then every `CheckResult` is `PASS` or `SKIP`. `report.has_failures
  is False`.

### 4.2 CMIS unreachable
- Given CMIS warmup returns 503.
- When `run_doctor` is called.
- Then `_check_cmis_connectivity` is FAIL; `details["status_code"] ==
  "503"`. Subsequent checks that depend on the uploader (type
  alignment, dry-run) MUST also FAIL or SKIP — not crash.

### 4.3 Tracking store db dir missing
- Given `config.tracking.db_path` points at a non-creatable path
  (e.g., `/dev/null/x/tracking.db`).
- When `run_doctor` is called.
- Then `_check_tracking_openable` is FAIL with the I/O error.

### 4.4 Empty mapping
- Given a Modelo Documental CSV with header only (zero data rows).
- When `run_doctor` is called.
- Then `_check_mapping_completeness` is WARN, `details["mapping_count"]
  == "0"`. `has_failures` remains False (warnings don't fail the
  doctor).

### 4.5 Metadata source empty
- Given one metadata source CSV with header only.
- When `run_doctor` is called.
- Then `_check_metadata_sources` is WARN with the empty-source alias
  in `details`.

### 4.6 CM type missing
- Given a mapping that references `cm_object_type=X`; CMIS mock
  returns 404 for typeId=X.
- When `run_doctor` is called.
- Then `_check_cm_type_alignment` is FAIL with the missing type in
  `details["missing_types"]`.

### 4.7 Sample dry-run S4 failure
- Given a config whose first trigger resolves to a doc whose page
  files are not on disk.
- When `run_doctor` is called.
- Then `_check_sample_dry_run` is FAIL with `details["stage"] == "S4"`.

### 4.8 Empty trigger CSV
- Given a trigger CSV with header only.
- When `run_doctor` is called.
- Then `_check_sample_dry_run` is SKIP with
  `details["reason"] == "no_triggers"`.

### 4.9 CLI `doctor` exit 0 happy path
- Given a valid config + mocked CMIS.
- When `cli_runner.invoke(main, ["doctor", "--config", str(yaml)])`.
- Then exit code 0; stdout contains a `[PASS]` line per check; the
  summary line ends with "0 failed".

### 4.10 CLI `doctor` exit 1 on any failure
- Given a config that triggers a check FAIL.
- When `cli_runner.invoke(main, ["doctor", "--config", str(yaml)])`.
- Then exit code 1; stdout contains at least one `[FAIL]` line.

### 4.11 CLI `doctor` exit 2 on bad config
- Given a missing config file.
- When the CLI is invoked.
- Then exit code 2 (Click's path-exists check).

### 4.12 Order of checks is stable
- Given a valid config.
- When `run_doctor` returns the report.
- Then `report.results` lists the 6 checks in the documented order:
  cmis_connectivity, tracking_openable, mapping_completeness,
  metadata_sources, cm_type_alignment, sample_dry_run.

---

## 5. Non-functional requirements

- **NFR-001** `cmcourier doctor` against a healthy config MUST
  complete in under 5 seconds on the developer's machine (informal —
  no automated SLO). The dominant cost is per-type CMIS calls; with
  the test fixture's 7 mappings, each call is ~1 ms via `responses`.
- **NFR-002** Branch coverage on `cmcourier/cli/doctor.py` MUST be
  ≥ 85%.
- **NFR-003** Method length cap (Constitution III): every `_check_*`
  function ≤ 50 lines.

---

## 6. Tooling expectations

- `ruff check src/ tests/`, `ruff format --check`: clean.
- `mypy --strict on cmcourier.*`: clean.
- `pre-commit run --all-files`: clean.
- `pytest`: full suite passes; net positive test count (~12 new).

---

## 7. Open questions / risks

- **Risk**: `get_type_definition` per-mapping iteration is O(N) HTTP
  calls. Healthy CMIS handles this fine (each ~1-5 ms); a slow CMIS
  amplifies. Mitigation: deferred — when production CMIS proves
  slow, switch to batched type queries OR cache.
- **Risk**: the sample dry-run depends on `build_pipeline` which
  constructs every adapter — including the assembler and the
  tracking store. The tracking store opens its WAL DB. We must NOT
  call `tracking_store.complete_batch` from doctor (no batch was
  started). Mitigation: dry-run manually walks S1-S4 without
  touching tracking.
- **Risk**: `CmisUploader.get_type_definition` doesn't go through
  `_post_with_retries`. The hand-rolled GET could grow inconsistent
  with the retry policy. Mitigation: explicitly documented — doctor
  prefers fail-loud over retry-quietly.
- **Open question**: should `--quiet` flag suppress per-check lines
  and emit only the summary + failures? **Resolved**: no — adds
  ~15 LOC and another test, and `grep` on the verbose output achieves
  the same end. Defer.
- **Open question**: doctor as a pre-step inside `run`?
  **Resolved**: not in 013. Adds coupling between commands and forces
  operators to opt-out instead of opt-in. The operator runs `doctor`
  themselves before the first real run; subsequent invocations skip
  it.

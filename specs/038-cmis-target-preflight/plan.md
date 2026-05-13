# 038 — Plan

Five phases, ~10-12h total. RED→GREEN per phase, commit per phase,
FF on the last commit.

The phases are ordered so each one is independently mergeable:
phase 1 lands schema + service plumbing without behavior change,
phase 2 lands the port refactor in isolation, phase 3 lands the
two doctor checks on top of phases 1+2, phase 4 lands observability,
phase 5 docs + bump.

## Phase 1 — `CMISFolder` + `CMISPropertyId` columns through the stack (~2.5h)

### Files

- `src/cmcourier/config/schema.py`
  - `MappingConfig.rvi_cm_cmis_folder_column: str = "CMISFolder"`.
  - `MappingConfig.metadatos_cmis_property_id_column: str = "CMISPropertyId"`.
  - Frozen, no env override — these are file-shape choices.
- `src/cmcourier/domain/models.py`
  - `CMMapping.cmis_folder: str | None = None`.
- `src/cmcourier/services/mapping.py`
  - When the CSV has the configured `CMISFolder` column, populate
    `cmis_folder` (None for empty cells). Otherwise leave None.
  - Backward-compat: missing column is a no-op.
- `src/cmcourier/services/metadata.py`
  - `MetadataService` reads `metadatos_cmis_property_id_column`
    from the joined `MetadatosCM` rows. When present and
    non-empty, `resolve_properties` keys the output dict by the
    CMIS property ID; otherwise by the friendly name (existing
    behavior).
- `src/cmcourier/orchestrators/staged.py`
  - S5 URL builder consumes `mapping.cmis_folder`:
    `f"{base}/{repo}/root/{cmis_folder}"` when set,
    `f"{base}/{repo}/root"` when None. **No call to ensure_folder
    is added or modified in this phase** (that's phase 2).

### Tests

- `tests/unit/config/test_schema.py`
  - Defaults: both column names default to the spec values.
- `tests/unit/services/test_mapping.py`
  - CSV with `CMISFolder` populated → `cmis_folder` carries through.
  - CSV with empty `CMISFolder` cell → `cmis_folder is None`.
  - CSV without the `CMISFolder` column → `cmis_folder is None` for
    every row (no exception).
- `tests/unit/services/test_metadata.py`
  - With `CMISPropertyId` populated → resolved property dict keys
    are CMIS IDs.
  - With `CMISPropertyId` empty → falls back to friendly names.
  - Column missing → falls back globally.
- `tests/integration/orchestrators/test_staged_pipeline.py`
  - Existing tests pass unchanged.
  - New test: mapping row with `cmis_folder="$type/X"` produces an
    upload URL containing `/$type/X`.

### Commit

```
feat(config,mapping,metadata,pipeline): CMISFolder + CMISPropertyId columns (038 Phase 1)
```

## Phase 2 — `IUploader.verify_folder_exists` + remove creation surface (~2h)

### Files

- `src/cmcourier/domain/ports.py`
  - Rename `ensure_folder` → `verify_folder_exists`.
  - Return `bool`. Docstring: returns True iff the folder exists
    AND has `cmis:baseTypeId == cmis:folder`.
- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - Replace `ensure_folder` body with a verify-only implementation
    that does `GET ?cmisselector=object&objectId=<path>`.
  - Map response:
    - 200 + baseTypeId folder → True
    - 200 + baseTypeId not-folder → False
    - 404 → False
    - other → raise connectivity / auth exception (existing classes)
  - Delete `_create_folder_segment` private method.
- `src/cmcourier/orchestrators/staged.py`
  - Remove the existing `uploader.ensure_folder(...)` call from S5
    (the one inside the per-doc upload). The new behavior is:
    S5 trusts the operator ran `doctor --check cm-targets`.

### Tests

- `tests/integration/adapters/test_cmis_uploader.py`
  - Replace `ensure_folder_creates_when_missing` and similar with
    `verify_folder_exists_returns_true_for_existing`,
    `verify_folder_exists_returns_false_on_404`,
    `verify_folder_exists_returns_false_when_not_folder`.
  - Delete any test that relied on `_create_folder_segment`.
- `tests/integration/orchestrators/test_staged_pipeline.py`
  - Add assertion: a 10-doc pipeline run on a stub uploader records
    **zero** `verify_folder_exists` calls on the happy path
    (S5 no longer touches folder verification — that's doctor's
    job).

### Commit

```
refactor(uploader,pipeline): verify_folder_exists (read-only) + remove S5 folder-creation surface (038 Phase 2)
```

## Phase 3 — `cmis_folders_exist` + `cmis_properties_alignment` doctor checks (~2.5h)

### Files

- `src/cmcourier/cli/doctor.py`
  - `_check_cmis_folders_exist(config, secrets) -> CheckResult`:
    - Build mapping service, collect unique non-empty `cmis_folder`.
    - Build uploader once (existing `_build_uploader` helper).
    - For each folder, call `verify_folder_exists`; collect missing.
    - SKIP if no `cmis_folder` populated anywhere.
    - FAIL with `missing_folders` detail; instruction in message.
  - `_check_cmis_properties_alignment(config, secrets) -> CheckResult`:
    - Build mapping + metadata services.
    - For each unique `(cm_object_type, cmis_property_id)` pair
      (skipping rows where either is None), call
      `get_type_definition(cm_object_type)` (memoized per type).
    - Collect pairs whose `cmis_property_id` is not in the type's
      `propertyDefinitions`.
    - SKIP if no `cmis_property_id` populated anywhere.
    - FAIL grouping missing properties by type.
  - `_CHECK_GROUPS["cm-targets"] = frozenset({"cm_type_alignment",
    "cmis_folders_exist", "cmis_properties_alignment"})`.
  - `run_doctor` invokes the new checks when the active group
    includes them.

### Tests

- `tests/unit/cli/test_doctor.py`
  - `cmis_folders_exist`: PASS path (all exist), FAIL path
    (some missing, deterministic listing), SKIP path (column
    empty).
  - `cmis_properties_alignment`: PASS, FAIL grouped, SKIP.
  - `_CHECK_GROUPS["cm-targets"]` membership.
- `tests/integration/cli/test_doctor_cm_targets.py` (new)
  - Against a stub uploader that returns predictable
    `verify_folder_exists` / `get_type_definition` responses,
    exercise full `run_doctor(config, secrets, group="cm-targets")`
    and assert the 3 checks come back in order.

### Commit

```
feat(doctor): cmis_folders_exist + cmis_properties_alignment + cm-targets group (038 Phase 3)
```

## Phase 4 — `s5_upload_attempt` / `s5_upload_failed` events + `unmask_pii` (~2h)

### Files

- `src/cmcourier/config/schema.py`
  - `ObservabilityConfig.unmask_pii: bool = Field(default=False)`.
- `src/cmcourier/observability/pii.py`
  - Confirm `mask_value(field_name, value)` exists and covers the
    fields we emit (CIF, Nombre_Cliente, NUM_CUENTA_TARJETA,
    NUM_CUENTA, NUM_PRESTAMO, NUM_AFILIADO, Short_Name).
  - Add `mask_dict(properties: Mapping[str, str], *, unmask: bool)`
    convenience.
- `src/cmcourier/adapters/upload/cmis_uploader.py`
  - Before each POST attempt, emit `s5_upload_attempt` via the
    structured logger:
    - url, object_type_id, masked properties, attempt index,
      content_bytes, mime_type.
  - On non-201 response, emit `s5_upload_failed` extending the
    attempt event with status_code, truncated response_body,
    and `curl_equivalent` string. Build the curl with the
    **masked** values unless `observability.unmask_pii=True`.
- `src/cmcourier/cli/doctor.py`
  - On startup, when `unmask_pii=True`, append a `WARNING` line
    to the doctor summary (separate from the check results).

### Tests

- `tests/unit/observability/test_pii.py`
  - Round-trip: known field names masked, unknowns pass through,
    unmask flag returns raw.
  - `mask_dict` behavior.
- `tests/integration/adapters/test_cmis_uploader.py`
  - Mock 201 response → `s5_upload_attempt` written once.
  - Mock 400 response → `s5_upload_attempt` + `s5_upload_failed`
    written; failed event has `curl_equivalent` with masking applied.
  - `unmask_pii=True` → values appear raw in the events.
- `tests/integration/cli/test_doctor_warnings.py` (new)
  - With `observability.unmask_pii=True`, doctor output contains
    the unmask warning line.

### Commit

```
feat(observability,uploader): s5_upload_attempt + s5_upload_failed events + unmask_pii toggle (038 Phase 4)
```

## Phase 5 — Docs + CHANGELOG 0.41.0 + FF (~1h)

### Files

- `docs/how-to/cmis-target-preflight.md` (new) — operator runbook:
  - Filling `CMISFolder` and `CMISPropertyId` in the sample CSVs.
  - Running `cmcourier doctor --check cm-targets` and reading the
    output.
  - The unmask-pii toggle and when to use it.
- `docs/how-to/validation-checklist.md` — append a new §X
  "Pre-flight CMIS target" with the 3 checks.
- `scripts/staging/README.md` — add the doctor-then-run section
  to the quick start.
- `CHANGELOG.md` — `[0.41.0]` entry. Sections:
  - Added: CMISFolder + CMISPropertyId columns; cm-targets doctor
    group + 2 new checks; s5_upload_attempt + s5_upload_failed
    events; unmask_pii toggle.
  - Changed: `IUploader.ensure_folder` → `verify_folder_exists`
    (BREAKING for adapter implementers).
  - Removed: `CmisUploader._create_folder_segment`; S5 folder
    auto-creation.
- `README.md` — tick the relevant feature row.
- `pyproject.toml` — bump `version = "0.41.0"`.

### Tests

- Full suite green.
- `mypy --strict src/cmcourier/{domain,services,orchestrators}` clean.
- `ruff check` + `ruff format --check` clean.
- Smoke against the staging Alfresco:
  - `cmcourier doctor --check cm-targets` PASS after pre-creating
    `/cmcourier-staging/CN01`.
  - `cmcourier csv-trigger-pipeline run --total 5 --no-tui` writes
    5 `s5_upload_attempt` events.

### Commit

```
docs(038): cmis-target-preflight how-to + CHANGELOG 0.41.0 + IUploader contract bump (038 Phase 5)
```

### FF merge + branch delete.

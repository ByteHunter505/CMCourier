# 038 — CMIS target pre-flight + upload payload trace

## Why

Today CMCourier discovers CMIS-target problems **mid-run**: a
missing folder, a typo in a property name, a CMISType the operator
forgot to populate — all of these surface as 4xx errors on S5
attempt N out of thousands. The operator finds out hours into the
batch, the tracking DB fills with `S5_FAILED`, and the postmortem
is a grep through HTTP responses with no context on what was sent.

Two failure modes drove this change:

1. **Folder hierarchy is governed by the bank, not CMCourier.**
   The current `CmisUploader.ensure_folder` creates folders on demand
   (it iterates path segments and POSTs `cmisaction=createFolder`
   for each missing one). This was inherited from the legacy
   uploader and is wrong for our operational model: in production
   the folder tree is owned by the bank's CMIS administrators; we
   only deposit documents. An `ensure_folder` call that succeeds
   silently can mask a configuration bug (CSV typo) by creating a
   folder in the wrong place. We need verify-only semantics.

2. **Pre-flight type alignment exists but is incomplete.** The
   existing `cm_type_alignment` check (013) only validates that
   the CMISType resolves on the CM server. It does not check that
   the **folder destinations** exist, nor that the **per-field
   CMIS property IDs** (now configurable via `MetadatosCM`) are
   declared on those types. The operator can pass `doctor` with a
   green output and still hit 100% failure rate on S5 because the
   target folder doesn't exist.

3. **No wire-level visibility on the failure path.** When S5
   POSTs a multipart and the server replies 400, the existing
   error log records HTTP status and a truncated body. It does
   not record the property bag we sent — so the operator cannot
   tell whether the problem is a bad value, a bad property ID, a
   bad type ID, or an ordering issue. PII discipline (Principle
   VIII) plus structured `metrics.jsonl` give us the tools to fix
   this without leaking customer data into logs.

This change closes all three gaps under one cm-targets pre-flight
umbrella and adds an upload payload event to `metrics.jsonl` so
post-mortems are deterministic.

## What

### 1. New `MapeoRVI_CM.CMISFolder` column

`MappingConfig` (config/schema.py):

```python
rvi_cm_cmis_folder_column: str = "CMISFolder"
```

`CMMapping` (domain/models.py) gains:

```python
cmis_folder: str | None  # None when the CSV cell is empty / column missing
```

`MappingService` populates `cmis_folder` from the configured column.
When the column is absent (backward-compat for the consolidated
`ClaseDocumentalCM.csv` mode), the field is always `None`.

The pipeline S5 uses `cmis_folder` to build the upload URL:
- `cmis_folder` set → POST to `{base}/{repo}/root/{cmis_folder}`
- `cmis_folder` None → POST to `{base}/{repo}/root` (existing
  flat-root behavior, used by the consolidated-mapping mode and
  by tests).

### 2. New `MetadatosCM.CMISPropertyId` column

`MappingConfig`:

```python
metadatos_cmis_property_id_column: str = "CMISPropertyId"
```

`MetadataService.resolve_properties()` returns the per-field CMIS
property ID instead of the friendly name when the column is populated:

```
friendly Metadato           "CIF"
CMISPropertyId (if set)     "clbNonGroup.BAC_CIF"      ← wire
                            (or "cmcourier:BAC_CIF" in staging)
```

When `CMISPropertyId` is empty for a field, the service falls back
to the friendly name verbatim (preserves current behavior). When
the column is absent from the file, every field falls back. This is
fully additive — existing configs do not need updates.

### 3. `IUploader.ensure_folder` → `IUploader.verify_folder_exists`

Port rename (domain/ports.py):

```python
def verify_folder_exists(self, folder_path: str) -> bool: ...
```

Returns `True` if the folder exists in the CMIS repository and is
a `cmis:folder` base type. Returns `False` on 404 or on a 200
response whose `cmis:baseTypeId` is not `cmis:folder`. Raises only
on connectivity / auth failures.

Implementation (`adapters/upload/cmis_uploader.py`):
- Uses `GET ?cmisselector=object&objectId=workspace://SpacesStore/<folder>`
  or the path-based equivalent the CM REST API exposes. No POST.
- `_create_folder_segment` private helper is removed.

Pipeline (`orchestrators/staged.py`, S5):
- The current `uploader.ensure_folder(...)` call inside S5 is
  **removed**. S5's URL builder simply consumes `cmis_folder` from
  the CMMapping if set.
- Verification is delegated entirely to the doctor checks defined
  in §4. If the operator skips doctor and the folder is missing,
  the first S5 attempt fails with a 4xx whose payload trace
  (event from §5) makes the diagnostic obvious.

### 4. Two new doctor checks + `cm-targets` group

`cli/doctor.py`:

```python
_CHECK_GROUPS["cm-targets"] = frozenset({
    "cm_type_alignment",        # existing — kept
    "cmis_folders_exist",       # new
    "cmis_properties_alignment", # new
})
```

The existing `cm-types` group is kept (aliasing to the single
`cm_type_alignment` check) for backward compatibility with any
operator scripts; `cm-targets` is the new umbrella.

#### `_check_cmis_folders_exist`

- Iterates the unique non-empty `cmis_folder` values across the
  mapping rows.
- Calls `IUploader.verify_folder_exists` for each.
- PASS when all return `True`.
- FAIL listing the missing paths with the instruction
  "create these folders in CMIS before running the pipeline".
- SKIP when no row has `cmis_folder` populated (graceful for the
  consolidated-mapping mode where folders aren't yet declared).

#### `_check_cmis_properties_alignment`

For each unique `(cm_object_type, cmis_property_id)` pair derived
by joining `MapeoRVI` and `MetadatosCM` on `IDCM`:
- Calls `IUploader.get_type_definition(cm_object_type)`.
- Verifies `cmis_property_id` is present in
  `propertyDefinitions` of that type.
- FAIL groups missing pairs by type:
  `BAC_01_01_02_04_01_15 missing 2: clbNonGroup.Fvenc_Inicio, clbNonGroup.Fvenc_Fin`.
- SKIP when no row has `cmis_property_id` populated.

Both checks honor `cmis.test_connection_timeout_seconds` from the
existing config (no new knobs).

### 5. Upload payload trace events

`adapters/upload/cmis_uploader.py` emits two structured events
through the existing `observability` channel into `metrics.jsonl`.

#### `s5_upload_attempt` — every POST attempt

```jsonc
{
  "event": "s5_upload_attempt",
  "ts": "2026-05-13T03:42:11.812Z",
  "batch_id": "B-20260513-0001",
  "txn_num": "FB01.0001234",
  "attempt": 1,
  "url": "http://.../root/$type/BAC_01_01_02_04_01_15",
  "object_type_id": "$t!-2_BAC_01_01_02_04_01_15v-1",
  "properties": {
    "cmis:name": "0AAAUPUP.pdf",
    "cmis:contentStreamMimeType": "application/pdf",
    "clbNonGroup.BAC_CIF":         "00****56",
    "clbNonGroup.Nombre_Cliente":  "J***** P**********",
    "clbNonGroup.NUM_CUENTA":      "4111-****-****-1234"
  },
  "content_bytes": 2456712,
  "mime_type": "application/pdf"
}
```

#### `s5_upload_failed` — only on non-201 responses

Superset of `s5_upload_attempt` with three extra fields:

```jsonc
{
  "event": "s5_upload_failed",
  ...all of s5_upload_attempt...,
  "status_code": 400,
  "response_body": "{\"exception\":\"constraint\",\"message\":\"Property cm:foo unknown\"}",
  "curl_equivalent": "curl -u admin:*** -F 'cmisaction=createDocument' -F 'propertyId[0]=cmis:objectTypeId' ... '-F content=@<path>' 'http://.../'"
}
```

#### PII masking

`observability/pii.py` already exists. Both events route every
property value through `pii.mask_value(field_name, value)` before
emission. The friendly-name → masking-rule map lives in
`observability/pii.py` (existing); fields not in the map are
emitted verbatim.

#### Configuration

`ObservabilityConfig` (config/schema.py) gains:

```python
unmask_pii: bool = Field(default=False)
```

When `true`, both events emit unmasked values. Surfaced only via
config file (no CLI flag) to avoid accidental enables in PRD
batches. A doctor `WARNING` is emitted at startup when
`unmask_pii=true` is detected, reminding the operator.

## Out of scope

- **Auto-provisioning CMIS folders.** Explicit non-goal — the
  bank's team owns the folder tree.
- **Generating `MetadatosCM.CMISPropertyId` from CMIS typeDefinition
  reflection.** Operator fills the column manually with the wire-level
  property ID per environment (`cmcourier:*` in staging,
  `clbNonGroup.*` in PRD). A future spec could automate this.
- **Curl-equivalent dump on the success path.** Only the failure
  path emits it; success events have enough context already.
- **Changes to `observability/pii.py` masking rules.** Reused as-is.
- **Backporting `verify_folder_exists` semantics to existing
  staging integration tests that depended on auto-creation.** Those
  tests are rewritten to pre-create the folder via the staging
  Alfresco container directly (or via the CMM upload sample we
  already have).

## Acceptance criteria

- All 9 existing doctor checks continue to PASS on a healthy
  staging Alfresco.
- `doctor --check cm-targets` after `register-model.sh` plus
  pre-creating `/cmcourier-staging/CN01` reports **3 PASS**
  (cm_type_alignment, cmis_folders_exist, cmis_properties_alignment).
- Deleting the folder makes `cmis_folders_exist` FAIL and the
  pipeline `doctor` exits non-zero.
- Setting a `CMISPropertyId` on `CN01.CIF` that does not exist
  on `D:cmcourier:bacDoc` makes `cmis_properties_alignment`
  FAIL with the missing property listed.
- Running `cmcourier csv-trigger-pipeline run --total 10` on the
  staging stack writes 10 `s5_upload_attempt` events into
  `logs/<batch_id>/metrics.jsonl`.
- Injecting a bad property name into MetadatosCM and re-running
  produces at least one `s5_upload_failed` event with status
  `400`, a truncated `response_body`, and a `curl_equivalent` whose
  property values are PII-masked.
- Setting `observability.unmask_pii: true` and re-running yields
  the same events with raw values, and `doctor` startup emits a
  WARNING about the unmasked-PII mode.
- `CmisUploader._create_folder_segment` is removed and no test
  references it. Pipeline S5 makes zero folder-creation requests
  in a full run.
- Existing tests pass without modification except those that
  explicitly rely on auto-folder-creation (those are rewritten to
  pre-create).
- mypy --strict clean on `domain/`, `services/`, `orchestrators/`.
- Ruff clean.
- CHANGELOG entry `[0.41.0]`, POST-MVP roadmap unchanged (this is
  not a POST-MVP item — it's a hardening / operability change).

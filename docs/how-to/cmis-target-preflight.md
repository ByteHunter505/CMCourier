# How-to: CMIS target pre-flight (038)

> Status: `[0.41.0]` and later. Covers the new doctor checks under the
> `cm-targets` group, the `CMISFolder` / `CMISPropertyId` columns of
> the split mapping CSVs, the upload payload trace events, and the
> `unmask_pii` debugging knob.

Before any production batch you want answered: **does my CMIS target
actually accept what CMCourier is about to send?** Mid-batch 4xx errors
mean wasted hours and a tracking DB full of `S5_FAILED` rows. This
runbook walks the three pre-flight pieces 038 ships so you find the
problem **before** the first POST.

## TL;DR

```bash
# Fill the new optional columns in the split CSVs (one row to start):
#   MapeoRVI_CM.CMISFolder        = the CMIS folder path under root
#   MetadatosCM.CMISPropertyId    = the wire-level CMIS property id

# Then, against any CMIS endpoint (staging Alfresco or the bank's CM):
cmcourier doctor --config config.yaml --check cm-targets
```

You want three green PASSes:

- `cm_type_alignment` — every `CMISType` resolves on the server.
- `cmis_folders_exist` — every `CMISFolder` is a `cmis:folder` on the server.
- `cmis_properties_alignment` — every `(CMISType, CMISPropertyId)` pair from
  MetadatosCM is declared in that type's `propertyDefinitions`.

If any one is FAIL, fix it in your config or in CMIS before running the
pipeline. The doctor exits non-zero so any CI / cron wrapper aborts.

## §1 — The two new CSV columns

### `MapeoRVI_CM.CMISFolder`

| Column | Behavior when set | Behavior when blank / absent |
| --- | --- | --- |
| `CMISFolder` | S5's upload URL becomes `{base}/{repo}/root/{CMISFolder}`. The doctor's `cmis_folders_exist` check verifies every unique non-empty value is a folder on the CMIS server. | S5 falls back to the derived `cm_folder` (`/$type/BAC_<clase_id>` per the spec). `cmis_folders_exist` SKIPs the check entirely. |

The column is **fully additive** — pre-038 CSVs work unchanged.

Sample row (split mode, `MapeoRVI_CM.csv`):

```csv
IDSistema,IDRVI,IDCM,IDClaseDocumental,CMISType,CMISFolder
,FB01,CN01,01.01.01.01.01,D:cmcourier:bacDoc,/cmcourier-staging/CN01
```

### `MetadatosCM.CMISPropertyId`

The "property catalog" — the friendly-name → wire-level CMIS property
id translation per `IDCorto`.

| Column | Behavior when set | Behavior when blank / absent |
| --- | --- | --- |
| `CMISPropertyId` | `MetadataService.resolve` rewrites the resolved property key from the canonical alias (`BAC_CIF`) to the wire-level CMIS id (`clbNonGroup.BAC_CIF` in PRD, `cmcourier:BAC_CIF` in staging). The doctor's `cmis_properties_alignment` check cross-references each pair with the CMIS type's `propertyDefinitions`. | The resolved property key stays canonical — pre-038 behavior. `cmis_properties_alignment` SKIPs. |

Sample rows (split mode, `MetadatosCM.csv`):

```csv
IDCorto,Metadato,Requerido,CMISPropertyId
CN01,CIF,Yes,cmcourier:BAC_CIF
CN01,Nombre_Cliente,Yes,cmcourier:Nombre_Cliente
CN01,Short_Name,Yes,cmcourier:Short_Name
```

> Partial catalogs are valid — a blank cell for one metadato keeps that
> property's key canonical while the rest get translated.

## §2 — Reading `doctor --check cm-targets`

```bash
cmcourier doctor --config config.yaml --check cm-targets
```

You will see (in order):

1. `cm_type_alignment` — every unique `cm_object_type` (from MapeoRVI's
   `CMISType` if set, otherwise the derived form) resolves via
   `GET ?cmisselector=typeDefinition`.
2. `cmis_folders_exist` (038) — every unique non-empty `CMISFolder` is a
   `cmis:folder` on the server. Read-only — never creates anything.
3. `cmis_properties_alignment` (038) — every `(CMISType,
   CMISPropertyId)` pair is in the type's `propertyDefinitions`.

### What FAIL looks like

```
cmis_folders_exist
  status: FAIL
  message: 2 CMIS folder(s) missing on the server. Create them in CMIS before running the pipeline.
  details:
    missing_folders: /cmcourier-staging/CN02,/cmcourier-staging/CN03
    checked_count: 5
```

```
cmis_properties_alignment
  status: FAIL
  message: 1 property gap(s): D:cmcourier:bacDoc missing 1: cmcourier:DoesNotExist
  details:
    missing: D:cmcourier:bacDoc missing 1: cmcourier:DoesNotExist
    checked_pairs: 6
```

Fix the listed items in CMIS (folders) or in your MetadatosCM
(`CMISPropertyId` typo) before continuing.

## §3 — Upload payload trace events

Every successful S5 POST now writes one `s5_upload_attempt` event to
`logs/<batch_id>/metrics.jsonl`. Every failing POST adds an
`s5_upload_failed` event with the response status, body excerpt, and a
runnable `curl_equivalent` reproducing the failure.

### Reading attempts

```bash
jq -c 'select(.event=="s5_upload_attempt")' logs/<batch_id>/metrics.jsonl | head -3
```

Each record carries `url`, `object_type_id`, `document_name`, `mime_type`,
`content_bytes`, and a `properties_json` blob with the property bag we
were about to send. **PII values are masked by default** (`cif`,
`customer_name`, `account_number`, `phone`, `email`, `dni`, etc., plus
their wire-level variants `clbNonGroup.BAC_CIF`, `cmcourier:Nombre_Cliente`,
etc.).

### Reading failures

```bash
jq -c 'select(.event=="s5_upload_failed")' logs/<batch_id>/metrics.jsonl
```

Each failure record carries everything the attempt does plus:

- `status_code`: the HTTP status (typically 4xx — see Property gaps below).
- `response_body`: truncated to 1024 chars.
- `curl_equivalent`: a runnable curl that reproduces the failing POST
  (with `-u admin:***` and masked property values per the toggle below).

## §4 — `observability.unmask_pii` — when you actually need raw values

```yaml
observability:
  unmask_pii: true   # debugging only — NEVER in PRD batches
```

When this knob is true:

- `s5_upload_attempt` and `s5_upload_failed` emit raw values in
  `properties_json`.
- `curl_equivalent` carries raw values too.
- Doctor emits a `WARN` named `unmask_pii_active` at the top of every
  report, so a stray PRD batch never runs without you seeing the deviation.

Auth credentials (`-u user:pass`) are **never** unmasked — they are
always rendered as `-u admin:***` regardless of this flag.

## §5 — Operational discipline

- **The bank's CMIS administrators own the folder tree.** The
  `verify_folder_exists` adapter primitive is read-only — CMCourier no
  longer creates folders on demand. If a folder is missing, the doctor
  tells you which one and you provision it manually in CMIS.
- **Run `doctor --check cm-targets` after any CSV edit.** A typo in
  `CMISPropertyId` is a wire-level mistake the bank's server will
  reject — better to find it in 30 seconds with the doctor than after
  9 000 documents.
- **PII default is masked. Keep it that way in PRD.** The `unmask_pii`
  toggle exists for active debugging on staging or a controlled test
  batch only.

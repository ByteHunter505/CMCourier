# How-to: Local staging simulation (Alfresco + Docker)

End-to-end validate CMCourier **before** the bank exposes their real
CMIS staging. Run cmcourier on your dev machine, point it at a local
Alfresco Community 23.x running in Docker on a second host, feed it
synthetic data. **No bank credentials needed**.

> Last updated for `[0.42.0]`. Incorporates the 037 cross-batch cache,
> 038 cm-targets pre-flight + payload trace, and 039 RVABREP synthetic
> generator. The generic runbook in `staging-dry-run.md` covers the
> non-simulation case (real bank staging or anything not docker-based).

## Architecture

```
┌─────────────────────────┐         ┌───────────────────────────┐
│   Compu A (dev)         │         │   Compu B (LAN host)      │
│                         │         │                           │
│  cmcourier              │  HTTP   │  Docker                   │
│   ├── mock rvabrep      │ ──────► │   └── Alfresco Community  │
│   ├── mock generate     │  :8080  │        23.4.1             │
│   ├── doctor cm-targets │         │        (admin/admin)      │
│   └── pipeline run      │         │                           │
│                         │         │  Custom Content Model:    │
│                         │         │   cmcourierBacModel       │
└─────────────────────────┘         └───────────────────────────┘
```

Everything on Compu A: source files, RVABREP CSV, mapping CSVs,
tracking DB, logs. Compu B runs only Alfresco + its sidecars
(Postgres, Solr, ActiveMQ).

## Prerequisites

**Compu A**:
- CMCourier installed (`uv sync`).
- A directory for synthetic data — sized per the dataset (50k rows
  + tiny files ≈ 1-2 GB; with 2 MB-mean files ≈ 25 GB).
- Network reachability to Compu B on port 8080.

**Compu B**:
- Linux (the scripts under `scripts/staging/` are bash-only).
- Docker + Docker Compose v2.
- ≥6 GB free RAM (Alfresco minimum), ≥15 GB free disk for image +
  contentstore.
- LAN IP / Tailscale hostname known to Compu A (referenced below as
  `<compu-b>`).

---

## Step 1 — Bring up Alfresco on Compu B

Copy the contents of `scripts/staging/` to Compu B (rsync, scp,
`git clone`). On Compu B, from inside that directory:

```bash
# 1a. Generate the JCEKS metadata keystore once. Alfresco 23.x
#     Community does NOT ship one in the WAR — without this the
#     repo crashes on bootstrap and the CMIS endpoint returns 404
#     forever. Idempotent — safe to re-run.
bash generate-keystore.sh

# 1b. Pull images + start the stack. First boot: ~3-5 min pulling
#     (~3 GB total), then ~1-2 min Alfresco bootstrap.
docker compose -f alfresco-compose.yml up -d

# 1c. Poll the repositoryInfo endpoint until it returns 200. The
#     dictionary takes 60-120s post-startup to be queryable.
until curl -fsS -u admin:admin \
  "http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=repositoryInfo" \
  > /dev/null; do
  echo "waiting for Alfresco..."; sleep 15
done
```

Note the `repositoryId` from the JSON — typically `-default-`. You
plug it into `cmis.repo_id` in Step 4.

## Step 2 — Register the custom content model

Alfresco rejects upload requests carrying properties that the type
does not declare. We ship a minimal model that declares
`cmcourier:bacDoc` plus the staging metadata properties.

```bash
# 2a. Idempotent — uploads the XML zipped via /alfresco/service/api/cmm/upload,
#     then activates the model. No-ops if the model is already ACTIVE.
#     The Alfresco container must be reachable on localhost:8080.
bash register-model.sh
```

Verify the type is registered (mind the `D:` prefix — Alfresco
exposes document types under that namespace):

```bash
curl -u admin:admin \
  "http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=typeDefinition&typeId=D:cmcourier:bacDoc" \
  | python3 -m json.tool | head -20
```

Expect a JSON definition listing the six `cmcourier:*` properties.

### Pre-create the CMIS folders

CMCourier (038) does **not** create folders on demand any more —
operators own the folder hierarchy. For the staging exemplar:

```bash
# Create /cmcourier-staging/CN01 — the folder MapeoRVI_CM points
# CN01 at by default. Repeat for every additional CMISFolder you
# plan to use.
curl -u admin:admin -X POST \
  -F "cmisaction=createFolder" \
  -F "propertyId[0]=cmis:objectTypeId" -F "propertyValue[0]=cmis:folder" \
  -F "propertyId[1]=cmis:name" -F "propertyValue[1]=cmcourier-staging" \
  "http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser/root"

curl -u admin:admin -X POST \
  -F "cmisaction=createFolder" \
  -F "propertyId[0]=cmis:objectTypeId" -F "propertyValue[0]=cmis:folder" \
  -F "propertyId[1]=cmis:name" -F "propertyValue[1]=CN01" \
  "http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser/root/cmcourier-staging"
```

## Step 3 — Generate the synthetic dataset (Compu A)

```bash
# 3a. Synthetic RVABREP CSV (50k rows, ~4 MB, ~3-5s). Seed is
#     deterministic — same seed = byte-identical output.
cmcourier mock rvabrep \
  --rows 50000 \
  --output sample/rvabrep-50k.csv \
  --seed 50000 \
  --idrvi-top 20

# 3b. Materialize the 50k physical files. Time + disk depend on the
#     size bounds. Conservative choice for a first run:
#     pdf 10kb-100kb, img 5kb-50kb → ~1.5 GB total, ~3-5 min.
cmcourier mock generate \
  --rvabrep-csv sample/rvabrep-50k.csv \
  --root sample/files \
  --pdf-min 10kb --pdf-max 100kb \
  --img-min 5kb --img-max 50kb \
  --seed 1
```

### Mapping CSVs

Two CSVs the pipeline needs are already shipped in the repo:
- `docs/samples/csv/MapeoRVI_CM.csv` — the bank's MapeoRVI with 282
  IDRVIs. The `CN01` row carries the staging exemplar
  (`CMISType=D:cmcourier:bacDoc`, `CMISFolder=/cmcourier-staging/CN01`).
- `docs/samples/csv/MetadatosCM.csv` — corresponding metadata. The
  five `CN01` rows carry the `cmcourier:*` property catalog.

For your synthetic batch you'll most likely **need to point every
IDRVI in the generated CSV at the same `D:cmcourier:bacDoc` type**,
otherwise the `cm-targets` pre-flight in Step 5 fails for the other
19 types. Either:

- (a) Drop `--idrvi-top 1` in Step 3a so only one IDRVI is used.
- (b) Copy `docs/samples/csv/MapeoRVI_CM.csv` to
  `sample/MapeoRVI_CM.csv` and set
  `CMISType=D:cmcourier:bacDoc` +
  `CMISFolder=/cmcourier-staging/<idrvi>` on every row your
  RVABREP touches (use the IDRVI distribution from
  `cmcourier mock rvabrep`'s output to know which 20 you need).

### Trigger CSV

Triggers are NOT auto-generated by 039 yet — derive them from the
RVABREP. Quick shell:

```bash
echo "ShortName,CIF,SystemID" > sample/triggers.csv
tail -n +2 sample/rvabrep-50k.csv \
  | awk -F, -v OFS=, '!seen[$1]++{print $1, $5, $2}' \
  >> sample/triggers.csv
```

## Step 4 — Wire the config

Copy `scripts/staging/config-staging.yaml.template` to
`sample/config-staging.yaml`. Edit:

```yaml
trigger:
  csv_path: sample/triggers.csv

indexing:
  csv_path: sample/rvabrep-50k.csv

mapping:
  rvi_cm_csv_path: sample/MapeoRVI_CM.csv      # or docs/samples/csv/...
  metadatos_csv_path: sample/MetadatosCM.csv   # or docs/samples/csv/...

assembly:
  source_root: sample/files
  temp_dir:    sample/tmp

tracking:
  db_path: sample/tracking.db

cmis:
  base_url: "http://<compu-b>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser"
  repo_id: ""                       # 040: Alfresco wants empty here, NOT "-default-"
  workers: 4
  max_bandwidth_mbps: 20.0   # LAN; remove the cap on Tailscale.

observability:
  log_dir: sample/logs
  unmask_pii: false          # 038 — keep false outside active debugging.
```

Env vars (Constitution V — credentials only via env):

```bash
export CMIS_USERNAME=admin
export CMIS_PASSWORD=admin
```

## Step 5 — Pre-flight against Alfresco

Two gates, in order. Stop and fix on any FAIL.

```bash
# 5a. Connections + types + dry-run on the first doc.
cmcourier doctor -c sample/config-staging.yaml

# 5b. cm-targets group (038) — verifies every distinct CMISType has
#     a typeDefinition, every distinct CMISFolder exists, and every
#     (CMISType, CMISPropertyId) pair aligns with the type's
#     propertyDefinitions.
cmcourier doctor -c sample/config-staging.yaml --check cm-targets
```

Common failures and fixes:

| Check | Failure | Fix |
| --- | --- | --- |
| `cm_type_alignment` | type `D:cmcourier:bacDoc` unknown | rerun `register-model.sh` on Compu B |
| `cm_type_alignment` | type `$t!-...v-1` unknown | you forgot to set `CMISType=D:cmcourier:bacDoc` on the mapping row |
| `cmis_folders_exist` | folder missing | Step 2 — pre-create it in CMIS |
| `cmis_properties_alignment` | property missing on type | typo in `MetadatosCM.CMISPropertyId` |

## Step 6 — Run the pipeline

Conservative first run — small batch with TUI off so you can read
the metrics:

```bash
cmcourier csv-trigger-pipeline run \
  -c sample/config-staging.yaml \
  --total 100 \
  --no-tui
```

What to watch:

- Exit code 0; tracking DB shows 100 `S5_DONE`.
- `sample/logs/<batch_id>/metrics.jsonl` contains 100
  `s5_upload_attempt` events (038). Run:
  ```bash
  jq -c 'select(.event=="s5_upload_attempt") | {txn_num, object_type_id}' \
    sample/logs/<batch_id>/metrics.jsonl | head -5
  ```
- No `s5_upload_failed` events. If any appear, the structured event
  carries `status_code`, truncated `response_body`, and a runnable
  `curl_equivalent` you can paste into a terminal to reproduce.

Scale up once the smoke is green:

```bash
cmcourier csv-trigger-pipeline run \
  -c sample/config-staging.yaml \
  --total 50000           # the full synthetic batch
```

### Running with TUI (0.44.0+)

Drop `--no-tui` and the Textual dashboard launches in the same
terminal. As of 0.44.0 the dashboard no longer competes with
``log.info()`` for the screen — the stderr handler is detached
for the lifetime of the TUI, so the dashboard frame stays clean.
Logs still flow to ``sample/logs/app-YYYY-MM-DD.log``; tail that
file in a second terminal if you want to follow them live.

What to watch in the TUI:

- **UPLOAD tab** — progress bar shows docs (``9 / 22``) with
  ``MB uploaded / MB planned`` on the right of the same line; the
  next line shows ``chunk elapsed HH:MM:SS   avg X.XX MB/s   est
  remaining HH:MM:SS``. ETA hides until the chunk crosses 5 %
  completion.
- **CHUNKS tab** (multi-batch only — ``batches_in_flight=2``) —
  per-chunk row with docs, MB, ``PREP done/skip/fail (elapsed)``,
  ``UPLOAD done/skip/fail (elapsed)`` and a ``TOTAL`` aggregate
  row at the bottom. QUEUED chunks render ``—/—/—`` in the stage
  columns so a glance can tell "not yet" from "zero outcomes".

## Step 7 — Verify in Alfresco

```bash
# 7a. Count docs of the custom type on the server.
curl -s -u admin:admin -G \
  --data-urlencode "q=SELECT COUNT(*) AS n FROM cmcourier:bacDoc" \
  --data "cmisselector=query" \
  "http://<compu-b>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser" \
  | python3 -m json.tool

# 7b. Sample 3 docs with their custom properties (raw values appear
#     in the CMIS query response — this is direct CMIS, not the
#     cmcourier event stream).
curl -s -u admin:admin -G \
  --data-urlencode "q=SELECT cmis:objectId, cmis:name, cmcourier:BAC_CIF, cmcourier:Nombre_Cliente FROM cmcourier:bacDoc" \
  --data "cmisselector=query" \
  "http://<compu-b>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser" \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
for row in d.get('results', [])[:3]:
    props = row.get('properties', {})
    print({k: v.get('value') for k, v in props.items()})
"
```

## Step 8 — Tear down

```bash
# Compu A
rm -rf sample/

# Compu B
docker compose -f alfresco-compose.yml down -v   # -v wipes Postgres + contentstore
```

The Alfresco image stays cached (~3 GB) so the next setup runs Step 1
in ~30s. The keystore at `alfresco-extension/keystore/keystore` is
preserved across `down -v` — re-generation isn't needed.

The custom content model lives in Postgres — `down -v` drops it.
Re-run `register-model.sh` in Step 2 after a wipe.

## Caveats

- **Alfresco is not IBM CM.** Browser binding 1.1 is the same protocol
  but auth schemes, error response bodies, type id syntax, and
  `cmisselector` support differ. Notably, Alfresco 23.4.1 does NOT
  support `cmisselector=object` or `cmisselector=properties` —
  fetching a specific document needs `cmisselector=query` with a
  CMIS-SQL `WHERE cmis:objectId = '...'` clause.
- **The content model is a fixture**, not a faithful copy of the
  bank's. If the bank declares 200 types in production, this
  simulation runs with 1. The 039 generator's `--idrvi-top 20` will
  generate 20 distinct IDRVIs, all of which need to point at the
  one staging type via `CMISType=D:cmcourier:bacDoc` in the
  mapping (see Step 3 (b)).
- **PII masking default is ON.** The `s5_upload_attempt` /
  `s5_upload_failed` events in `metrics.jsonl` will not carry raw
  CIF / Nombre_Cliente / NUM_CUENTA values. To unmask for active
  debugging set `observability.unmask_pii: true` in the config —
  the doctor emits an `unmask_pii_active` WARN at startup so you
  cannot forget to flip it back.
- **Memory budget**: Alfresco 23.x defaults to 4 GB JVM. If Compu B
  has 8 GB total, leave 2 GB headroom. Edit `JAVA_OPTS` in
  `alfresco-compose.yml` to tighten if needed.
- **Synthetic shortname cardinality**: the 039 generator's lexicon
  is 15 names × 100 numeric suffixes = 1500 unique shortnames. With
  `--clients 5000` and 50k rows you actually see ≈1500 distinct
  clients (avg ~33 docs/client). This is realistic enough for
  staging — power-users in real data look similar.

## Cross-references

- Generic runbook: `docs/how-to/staging-dry-run.md`.
- Synthetic RVABREP generator (039): `docs/how-to/mock-rvabrep-generator.md`.
- CMIS target pre-flight (038): `docs/how-to/cmis-target-preflight.md`.
- Doctor: `cmcourier doctor --help`.
- Cross-batch metadata cache (037): `docs/how-to/document-cache.md`.
- Heavy/light lanes (036): `docs/how-to/heavy-light-lanes.md`.
- Multi-batch orchestrator (028): `docs/how-to/multi-batch.md`.
- Offline log analyzer: `docs/how-to/log-analysis.md`.
- Staging scaffolding scripts: `scripts/staging/README.md`.

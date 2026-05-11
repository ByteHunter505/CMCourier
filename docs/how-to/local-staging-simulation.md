# How-to: Local staging simulation (Alfresco + Docker)

End-to-end validate CMCourier **before** the bank exposes their real
CMIS staging. Run cmcourier on your dev machine, point it at a local
Alfresco Community 23.x running in Docker on a second host, feed it
synthetic data. **No bank credentials needed**.

The runbook in `staging-dry-run.md` is generic; **this one is
specific to the simulation setup**.

## Architecture

```
┌─────────────────────────┐         ┌───────────────────────────┐
│   Compu A (dev)         │         │   Compu B (LAN host)      │
│                         │         │                           │
│  cmcourier              │  HTTP   │  Docker                   │
│   ├── reads CSVs        │ ──────► │   └── Alfresco Community  │
│   │     locally         │  :8080  │        23.x               │
│   ├── reads mock files  │         │        (admin/admin)      │
│   │     locally         │         │                           │
│   └── uploads to CMIS   │         │  Custom Content Model:    │
│                         │         │   cmcourier-model.xml     │
└─────────────────────────┘         └───────────────────────────┘
```

Everything else (triggers, RVABREP rows, mapping CSVs, source files)
lives on Compu A.

## Prerequisites

**Compu A**:
- CMCourier installed (`uv sync`).
- A directory for synthetic data (~500 MB to a few GB depending on
  sample size).
- Network reachability to Compu B on port 8080.

**Compu B**:
- Docker + Docker Compose.
- ≥6 GB free RAM (Alfresco minimum), ≥10 GB disk for the image +
  data volume.
- LAN IP known to Compu A (set as `<compu-b-ip>` below).

## Step 1 — Bring up Alfresco on Compu B

Copy `scripts/staging/alfresco-compose.yml` to Compu B, then:

```bash
cd /wherever/you/dropped/it
docker compose up -d
```

First boot pulls ~3 GB of images and takes 3-5 minutes. Watch the
logs until you see `Startup ... completed`:

```bash
docker compose logs -f alfresco | grep "completed"
```

Verify the CMIS endpoint:

```bash
curl -u admin:admin \
  "http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=repositoryInfo"
```

Expect a JSON blob with `productName: Alfresco`. Note the
`repositoryId` — you'll plug it into config.

## Step 2 — Deploy the Content Model

Alfresco rejects upload requests with properties that are not
declared in its content model. We ship a minimal one at
`scripts/staging/cmcourier-model.xml` that declares the type
`cmcourier:bacDoc` plus the metadata properties CMCourier emits.

Two ways to deploy:

**Quick (volume mount)**: drop the XML into the
`./alfresco-extension/alfresco/extension/` directory on Compu B (the
compose file mounts it). Restart Alfresco:

```bash
docker compose restart alfresco
```

**Full (Admin Console)**: log in to
`http://<compu-b-ip>:8080/share` as `admin/admin`, go to Admin Tools
→ Model Manager → Import. Upload `cmcourier-model.xml`. Activate the
model.

Verify the type registered:

```bash
curl -u admin:admin \
  "http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=typeDefinition&typeId=cmcourier:bacDoc" \
  | python -m json.tool
```

Expect a JSON definition with the properties listed.

## Step 3 — Synthetic dataset on Compu A

You generate the sample yourself (your call on size and shape). The
shape you need:

**Triggers** (`/sample/triggers.csv`):
```csv
ShortName,CIF,SystemID
CLIENT001,123456,1
CLIENT002,234567,1
...
```

**RVABREP rows** (`/sample/rvabrep.csv`): columns are
`shortname`, `system_id`, `txn_num`, `index1..index7`, `image_type`,
`image_path`, `file_name`, `creation_date`, `last_view_date`,
`total_pages`, `delete_code`. The
`tests/fixtures/pipeline/rvabrep.csv` is a good template.

**MapeoRVI_CM** (`/sample/MapeoRVI_CM.csv`): standard 035 split format.
**For staging, set `CMISType=cmcourier:bacDoc` on every row** so the
039 override targets the type we just declared.

**MetadatosCM** (`/sample/MetadatosCM.csv`): same format as
`docs/samples/csv/MetadatosCM.csv`. Use the property names declared
in the Content Model.

**Source files**: generate with `cmcourier mock generate` (031). It
produces deterministic PDFs/TIFFs/JPEGs sized to your config.

## Step 4 — Wire the config

Copy `scripts/staging/config-staging.yaml.template` to
`config-staging.yaml`. Edit the paths to match your `/sample/...`
layout and the CMIS section:

```yaml
cmis:
  base_url: "http://<compu-b-ip>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser"
  repo_id: "-default-"        # use the id from Step 1's curl
  workers: 4                   # start conservative
  max_bandwidth_mbps: 20.0     # LAN, can go higher
```

Set env vars:

```bash
export CMIS_USERNAME=admin
export CMIS_PASSWORD=admin
```

## Step 5 — Run the dry-run

Now follow `docs/how-to/staging-dry-run.md` from Step 0 (`cmcourier
doctor`) through Step 7. **Every check** should pass against
Alfresco. If a check fails:

- `cm_type_alignment` fails on `cmcourier:bacDoc` → the model didn't
  load. Recheck Step 2.
- `cm_type_alignment` fails on the IBM CM `$t!...` pattern → you
  forgot to set `CMISType` on the mapping CSV.
- Upload 400 "property not declared" → a metadata property your
  pipeline emits is missing from the Content Model. Either add it to
  `cmcourier-model.xml` and redeploy, or strip it from the mapping.

## Step 6 — Tear down

When the dry-run is done:

```bash
# Compu A
rm -rf /sample /path/to/logs /path/to/tracking.db

# Compu B
docker compose down -v   # -v wipes the alfresco data volume
```

The Alfresco image stays cached (3 GB) so the next setup is faster.

## Caveats

- **Alfresco is not IBM CM**. The protocol is the same (CMIS 1.1
  Browser Binding) but auth schemes, error response bodies, and edge
  cases differ. The simulation validates *workflow* fidelity, not
  exact IBM-CM-isms.
- **The Content Model is a fixture**, not a faithful copy of the
  bank's. If the bank declares 200 types in production, this
  simulation runs with 1. That gap is intentional — declaring 200
  Alfresco types is a separate exercise that buys little for the
  end-to-end dry-run.
- **Memory budget**: Alfresco 23.x defaults to 4 GB JVM. If Compu B
  has 8 GB total, leave 2 GB headroom. Edit `JAVA_OPTS` in
  `alfresco-compose.yml` to tighten.

## Cross-references

- Generic runbook: `docs/how-to/staging-dry-run.md`.
- Mock file generator: `docs/how-to/` (TODO; see 031 spec).
- Doctor command: `cmcourier doctor --help`.
- CMIS type override (039): release notes in `CHANGELOG.md [0.40.0]`.

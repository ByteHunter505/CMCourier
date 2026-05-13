# `scripts/staging/`

Staging dry-run scaffolding. **Not used in production** — only when
validating CMCourier against a non-production CMIS (the bank's
staging or our own Alfresco simulation).

## Files

| File | Purpose | Lives on |
| --- | --- | --- |
| `alfresco-compose.yml` | Docker Compose for Alfresco Community 23.x + Postgres + Solr + ActiveMQ. | Staging host |
| `generate-keystore.sh` | One-shot, idempotent. Generates the JCEKS metadata keystore Alfresco needs to bootstrap. Run BEFORE the first `docker compose up`. | Staging host |
| `register-model.sh` | One-shot, idempotent. Uploads `cmcourier-model.xml` to Alfresco via the CMM upload webscript and activates it, so `D:cmcourier:bacDoc` shows up in CMIS. Run AFTER Alfresco is healthy. | Staging host |
| `cmcourier-model.xml` | Alfresco custom content model declaring `cmcourier:bacDoc` (extends `cm:content`) plus the staging metadata properties. Registered via `register-model.sh`. | Staging host |
| `alfresco-purge-watchdog.sh` | Optional. Cron-friendly script that purges the Alfresco contentstore when it grows past a threshold. Only activate during sustained stress runs. | Staging host |
| `config-staging.yaml.template` | CMCourier YAML template with every staging-specific knob marked. Copy + edit before running. | CMCourier client machine |

## Quick start

```bash
# On the staging host, in this directory:

# 1. One-time keystore bootstrap (Alfresco 23.x Community needs a writable
#    JCEKS keystore at alfresco-extension/keystore/keystore — see the header
#    comment in alfresco-compose.yml for the WHY).
bash generate-keystore.sh

# 2. Bring the stack up. First boot takes ~3-5 min image pull + ~1-2 min
#    Alfresco bootstrap. Poll the CMIS endpoint until it returns 200.
docker compose -f alfresco-compose.yml up -d
until curl -fsS -u admin:admin \
  "http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=repositoryInfo" \
  >/dev/null; do echo "waiting for Alfresco..."; sleep 15; done

# 3. Register the custom content model so D:cmcourier:bacDoc exists in CMIS.
#    Idempotent — safe to re-run; no-op if the model is already ACTIVE.
bash register-model.sh
```

```bash
# On the CMCourier client machine:
cp config-staging.yaml.template config-staging.yaml
$EDITOR config-staging.yaml
export CMIS_USERNAME=admin CMIS_PASSWORD=admin
cmcourier doctor -c config-staging.yaml
```

## What this does NOT cover

- Generating the synthetic dataset (CSVs + source files). You generate
  that yourself per `docs/how-to/local-staging-simulation.md §3`.
- Network setup between the staging host and the CMCourier client.
  Whatever LAN/VPN/Tailscale reachability you have on port 8080 is
  your responsibility.
- Backups of the Alfresco data volume. `docker compose down -v` wipes
  Postgres + the contentstore — no persistence across teardown. The
  keystore at `alfresco-extension/keystore/keystore` IS persistent
  (it's a bind-mounted file on the host), so you don't need to
  regenerate it after a `down -v`. The custom content model, however,
  lives in Postgres — re-run `register-model.sh` after every wipe.

## Notes on Alfresco 23.x quirks

- **Custom models cannot use Spring bootstrap from `shared/classes`.**
  In Alfresco 23.x Community, dropping `cmcourier-model.xml` plus a
  Spring context XML into the extension mount does NOT register the
  model — the shared classpath is no longer scanned for
  `dictionaryModelBootstrap` beans. Use `register-model.sh` (which
  hits the `/alfresco/service/api/cmm/upload` webscript) instead.
  Worse: leaving a model XML in the mount silently pre-registers the
  namespace prefix/URI and blocks `register-model.sh` with HTTP 409.
- **CMIS exposes the type with a `D:` prefix.** The model declares
  `<type name="cmcourier:bacDoc">` but CMIS clients see it as
  `D:cmcourier:bacDoc` (the `D:` marks it as a `cmis:document` subtype).
  Pass `D:cmcourier:bacDoc` for `cmis:objectTypeId` in createDocument;
  use plain `cmcourier:bacDoc` only inside CMIS-SQL `FROM` clauses.
- **`cmisselector=object` and `=properties` are NOT supported in 23.4.1
  Browser binding** — both return HTTP 405 "Unknown operation". Fetch
  properties via `cmisselector=query` + a CMIS-SQL `SELECT`.

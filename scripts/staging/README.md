# `scripts/staging/`

Staging dry-run scaffolding. **Not used in production** — only when
validating CMCourier against a non-production CMIS (the bank's
staging or our own Alfresco simulation).

## Files

| File | Purpose | Lives on |
| --- | --- | --- |
| `alfresco-compose.yml` | Docker Compose for Alfresco Community 23.x + Postgres + Solr + ActiveMQ. | Compu B (the LAN host) |
| `cmcourier-model.xml` | Alfresco Custom Content Model declaring the `cmcourier:bacDoc` type + the metadata properties we emit. Deployed via volume mount or Admin Console. | Compu B |
| `config-staging.yaml.template` | CMCourier YAML template with every staging-specific knob marked. Copy + edit before running. | Compu A (dev machine) |

## Quick start

Full procedure: `docs/how-to/local-staging-simulation.md`.

```bash
# Compu B — bring Alfresco up
docker compose -f alfresco-compose.yml up -d

# Copy the model XML into the extension mount + restart
mkdir -p alfresco-extension/alfresco/extension/
cp cmcourier-model.xml alfresco-extension/alfresco/extension/
docker compose restart alfresco

# Compu A — edit config and run
cp config-staging.yaml.template config-staging.yaml
$EDITOR config-staging.yaml
export CMIS_USERNAME=admin CMIS_PASSWORD=admin
cmcourier doctor -c config-staging.yaml
```

## What this does NOT cover

- Generating the synthetic dataset (CSVs + source files). You generate
  that yourself per `docs/how-to/local-staging-simulation.md §3`.
- Network setup between Compu A and Compu B. Whatever LAN
  reachability you have on port 8080 is your responsibility.
- Backups of the Alfresco data volume. The compose file uses
  `docker compose down -v` to wipe — no persistence across teardown.

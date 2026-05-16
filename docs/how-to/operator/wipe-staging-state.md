# Wipear el estado de staging

> [← Volver al índice](../../INDEX.md) · [How-to](../README.md) · [Operador](README.md)

Entre smoke-runs deterministas necesitás dejar tanto Alfresco como el tracking DB en blanco para que la idempotency no corte uploads y el backend no rechace por `contentAlreadyExists`. Hay tres scripts en `scripts/staging/` que hacen el trabajo. Esta receta es el orden recomendado.

## Cuándo usarlo

- Vas a re-correr un smoke determinista (mismo `cmcourier mock rvabrep` seed → mismos `cmis:name` → Alfresco rechaza con HTTP 409).
- Querés validar throughput desde estado limpio, sin S1_SKIPPED enmascarando docs ya subidos.
- Tu staging Alfresco se está comiendo el disco y querés purgar contentstore agresivamente.

**Nunca** uses estos scripts contra prod ni contra un staging compartido cuyo contenido alguien más necesite. Borran todo de manera idempotente y silenciosa.

## Pre-requisitos

- `bash`, `curl`, `python3` instalados.
- Para `alfresco-purge-watchdog.sh`: `sudo` (toca `/var/lib/docker/volumes/`).
- Alfresco accesible (Tailscale up si tu host está detrás de Tailscale).
- Variables de ambiente Alfresco por defecto: `testserver:8080`, `admin:admin`. Overrideá si tu staging es distinto.

## Los tres scripts en una tabla

| Script | Qué borra | Cuándo |
|--------|-----------|--------|
| `wipe-alfresco-docs.sh` | Documentos bajo `/cmcourier-staging/<IDRVI_FOLDER>` vía CMIS Browser Binding. Deja las carpetas para no romper `doctor cm-targets`. | Entre smoke-runs deterministas |
| `wipe-local-state.sh` | Tracking SQLite (+WAL+SHM), logs de observability, temp PDFs de S4 | Entre smoke-runs deterministas, **siempre pareado con el anterior** |
| `alfresco-purge-watchdog.sh` | Blobs en `contentstore/` del docker volume — file-level delete, deja orphans en postgres+Solr | Loops largos de throughput donde el contentstore se llena |

## Pasos

### 1. Wipe Alfresco docs

```bash
bash scripts/staging/wipe-alfresco-docs.sh
```

Output esperado:

```
→ Probing http://testserver:8080/.../browser ...
  reachable (HTTP 200).
→ Escaneando archivos para borrar...
→ Se encontraron 1247 documentos.
→ Iniciando borrado (Paralelismo: 10 hilos)...
   [##################################################] 100% (1247/1247)

✓ ¡Limpieza completada!
```

Overrides por env var si tu staging no es el default:

```bash
ALFRESCO_HOST=otro-host \
ALFRESCO_PORT=8080 \
ALFRESCO_USER=admin ALFRESCO_PASS=admin \
STAGING_PARENT=cmcourier-staging \
bash scripts/staging/wipe-alfresco-docs.sh
```

Exit codes: `0` wipe completado (puede ser 0 deletes si todo estaba vacío), `1` Alfresco inalcanzable.

### 2. Wipe estado local (tracking + logs + temp)

```bash
bash scripts/staging/wipe-local-state.sh
```

Output:

```
→ Wiping local CMCourier staging state

  ✓ sample/*.db                              removed
  ✓ sample/*.db-wal                          removed
  ✓ sample/*.db-shm                          removed
  ✓ sample/logs/network-2026-05-15.jsonl     removed
  ...
  ✓ sample/staging_tmp                       removed

✓ Local state wiped. Next pipeline run starts from a clean tracking DB.
```

Dry-run primero si dudás:

```bash
bash scripts/staging/wipe-local-state.sh --dry-run
```

Overrides:

- `TRACKING_DB` — default `sample/*.db`
- `LOG_DIR` — default `sample/logs`
- `STAGING_TMP` — default `sample/staging_tmp`

```bash
TRACKING_DB=sample/mi-otro-tracking.db \
LOG_DIR=sample/logs-alt \
bash scripts/staging/wipe-local-state.sh
```

**Orden importa**: si wipeás local sin wipear Alfresco, la próxima corrida re-sube docs y Alfresco rechaza con 409 por `cmis:name` duplicado. Si wipeás Alfresco sin wipear local, la pipeline ve `S5_DONE` en tracking y mete `S1_SKIPPED` — no re-sube nada, contradiciendo tu intento de smoke.

### 3. (Opcional) Watchdog de contentstore para loops largos

Si vas a correr múltiples ciclos sin tocar Alfresco entre cada uno, el contentstore se infla aunque borres docs vía CMIS (Alfresco solo soft-deletea inicialmente). Lanzá el watchdog en background:

```bash
sudo nohup bash scripts/staging/alfresco-purge-watchdog.sh > /tmp/purge-watchdog.log 2>&1 &
```

Defaults:

- `VOLUME_NAME=staging_alfresco-data`
- `THRESHOLD_GB=30` — sobre eso, purga
- `INTERVAL_S=30` — chequea cada 30 s
- `DRY_RUN=0` — `1` para logear sin borrar

Override:

```bash
sudo VOLUME_NAME=mi-volumen THRESHOLD_GB=10 INTERVAL_S=15 \
  bash scripts/staging/alfresco-purge-watchdog.sh
```

**Trade-off importante**: el watchdog borra a nivel filesystem dentro del contentstore. Es rápido (~ms) pero deja filas huérfanas en postgres y refs colgadas en Solr. Alfresco las tolera silenciosamente en write paths — **no uses esto contra un repo cuyo contenido necesites leer de vuelta**. Para reset metadata+index completo:

```bash
docker compose -f scripts/staging/alfresco-compose.yml down -v
docker compose -f scripts/staging/alfresco-compose.yml up -d
```

Detenerlo:

```bash
# Si está en foreground
Ctrl-C

# Si está en background
sudo pkill -f alfresco-purge-watchdog
```

## Verificación

```bash
# Alfresco vacío: doctor debería pasar cm-targets sin errores
cmcourier doctor --config sample/config-staging.yaml --check cm-targets

# Tracking borrado
ls -la sample/*.db 2>&1
# → "No such file or directory"

# Smoke run desde cero
cmcourier csv-trigger-pipeline run \
    --config sample/config-staging.yaml \
    --batch-id smoke-clean-001 \
    --total 100
echo $?   # esperás 0
```

## Si algo sale mal

| Síntoma | Causa | Acción |
|---------|-------|--------|
| `wipe-alfresco-docs.sh` exit 1 con HTTP 000 | Tailscale caído / Alfresco no levantó | `tailscale status`, `docker compose ps` |
| HTTP 409 `contentAlreadyExists` en próxima corrida | Wipeaste local pero no Alfresco | Re-corré `wipe-alfresco-docs.sh` |
| `S1_SKIPPED` masivo en próxima corrida | Wipeaste Alfresco pero no local | Re-corré `wipe-local-state.sh` |
| `alfresco-purge-watchdog.sh` no encuentra el volume | `VOLUME_NAME` mal | `docker volume ls` para ver el nombre real |
| Alfresco devuelve errores raros después del watchdog | Postgres/Solr inconsistentes | `docker compose down -v` + `up -d` (reset total) |

## Ver también

- [`run-a-migration-from-csv.md`](run-a-migration-from-csv.md) — corrida canónica post-wipe
- [`run-a-streaming-load-against-staging.md`](run-a-streaming-load-against-staging.md) — carga grande post-wipe
- [`../local-staging-simulation.md`](../local-staging-simulation.md) — montar el staging local desde cero
- [`recover-from-a-corrupted-tracking-db.md`](recover-from-a-corrupted-tracking-db.md) — recovery, no wipe (cuando querés preservar estado)

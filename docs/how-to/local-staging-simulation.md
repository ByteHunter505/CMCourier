# How-to: Simulación de staging local (Alfresco + Docker)

> [← Volver al índice](../INDEX.md) · [How-to](README.md)

Validá CMCourier de punta a punta **antes** de que el banco exponga
su CMIS staging real. Corré cmcourier en tu máquina de dev, apuntalo a
un Alfresco Community 23.x local corriendo en Docker en un segundo
host, alimentalo con datos sintéticos. **Sin credenciales del banco**.

> Última actualización para `[0.42.0]`. Incorpora el cache cross-batch de
> 037, el pre-flight cm-targets + trace de payload de 038, y el generador
> sintético RVABREP de 039. El runbook genérico en `staging-dry-run.md`
> cubre el caso no-simulación (staging real del banco o cualquier cosa
> no basada en docker).

## Arquitectura

```
┌─────────────────────────┐         ┌───────────────────────────┐
│   Compu A (dev)         │         │   Compu B (host de LAN)   │
│                         │         │                           │
│  cmcourier              │  HTTP   │  Docker                   │
│   ├── mock rvabrep      │ ──────► │   └── Alfresco Community  │
│   ├── mock generate     │  :8080  │        23.4.1             │
│   ├── doctor cm-targets │         │        (admin/admin)      │
│   └── pipeline run      │         │                           │
│                         │         │  Modelo de Contenido      │
│                         │         │  custom:                  │
│                         │         │   cmcourierBacModel       │
└─────────────────────────┘         └───────────────────────────┘
```

Todo en Compu A: archivos fuente, CSV RVABREP, CSVs de mapping,
DB de tracking, logs. Compu B corre solo Alfresco + sus sidecars
(Postgres, Solr, ActiveMQ).

## Prerrequisitos

**Compu A**:
- CMCourier instalado (`uv sync`).
- Un directorio para datos sintéticos — dimensionado según el dataset
  (50k filas + archivos chiquitos ≈ 1-2 GB; con archivos de media 2 MB
  ≈ 25 GB).
- Alcance de red a Compu B en el puerto 8080.

**Compu B**:
- Linux (los scripts bajo `scripts/staging/` son solo bash).
- Docker + Docker Compose v2.
- ≥6 GB libres de RAM (mínimo de Alfresco), ≥15 GB libres de disco para
  imagen + contentstore.
- IP LAN / hostname Tailscale conocido a Compu A (referenciado abajo
  como `<compu-b>`).

---

## Paso 1 — Levantar Alfresco en Compu B

Copiá el contenido de `scripts/staging/` a Compu B (rsync, scp,
`git clone`). En Compu B, desde adentro de ese directorio:

```bash
# 1a. Generar el keystore JCEKS de metadatos una vez. Alfresco 23.x
#     Community NO shippea uno en el WAR — sin esto el repo
#     crashea en el bootstrap y el endpoint CMIS devuelve 404
#     para siempre. Idempotente — seguro de re-correr.
bash generate-keystore.sh

# 1b. Pull de imágenes + arrancar el stack. Primer boot: ~3-5 min de pull
#     (~3 GB total), después ~1-2 min de bootstrap de Alfresco.
docker compose -f alfresco-compose.yml up -d

# 1c. Pollear el endpoint repositoryInfo hasta que devuelva 200. El
#     dictionary tarda 60-120s post-startup en ser querable.
until curl -fsS -u admin:admin \
  "http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=repositoryInfo" \
  > /dev/null; do
  echo "esperando Alfresco..."; sleep 15
done
```

Notá el `repositoryId` del JSON — típicamente `-default-`. Lo
enchufás en `cmis.repo_id` en el Paso 4.

## Paso 2 — Registrar el modelo de contenido custom

Alfresco rechaza requests de upload que llevan propiedades que el tipo
no declara. Shippeamos un modelo mínimo que declara
`cmcourier:bacDoc` más las propiedades de metadatos de staging.

```bash
# 2a. Idempotente — uploadea el XML zippeado vía /alfresco/service/api/cmm/upload,
#     después activa el modelo. No-op si el modelo ya está ACTIVE.
#     El container Alfresco debe ser alcanzable en localhost:8080.
bash register-model.sh
```

Verificá que el tipo está registrado (cuidado con el prefijo `D:` —
Alfresco expone los tipos de documento bajo ese namespace):

```bash
curl -u admin:admin \
  "http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=typeDefinition&typeId=D:cmcourier:bacDoc" \
  | python3 -m json.tool | head -20
```

Esperá una definición JSON listando las seis propiedades `cmcourier:*`.

### Pre-crear las carpetas CMIS

CMCourier (038) **no** crea carpetas on demand más — los
operadores poseen la jerarquía de carpetas. Para el ejemplar de staging:

```bash
# Crear /cmcourier-staging/CN01 — la carpeta a la que MapeoRVI_CM
# apunta CN01 por default. Repetí para cada CMISFolder adicional
# que planeés usar.
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

## Paso 3 — Generar el dataset sintético (Compu A)

```bash
# 3a. CSV RVABREP sintético (50k filas, ~4 MB, ~3-5s). La semilla
#     es determinista — misma semilla = output byte-idéntico.
cmcourier mock rvabrep \
  --rows 50000 \
  --output sample/rvabrep-50k.csv \
  --seed 50000 \
  --idrvi-top 20

# 3b. Materializar los 50k archivos físicos. Tiempo + disco dependen
#     de los límites de tamaño. Elección conservadora para una primera
#     corrida: pdf 10kb-100kb, img 5kb-50kb → ~1.5 GB total, ~3-5 min.
cmcourier mock generate \
  --rvabrep-csv sample/rvabrep-50k.csv \
  --root sample/files \
  --pdf-min 10kb --pdf-max 100kb \
  --img-min 5kb --img-max 50kb \
  --seed 1
```

### CSVs de mapping

Dos CSVs que el pipeline necesita ya están shippeados en el repo:
- `reference-data/csv/MapeoRVI_CM.csv` — el MapeoRVI del banco con 282
  IDRVIs. La fila `CN01` lleva el ejemplar de staging
  (`CMISType=D:cmcourier:bacDoc`, `CMISFolder=/cmcourier-staging/CN01`).
- `reference-data/csv/MetadatosCM.csv` — metadatos correspondientes.
  Las cinco filas `CN01` llevan el catálogo de propiedades `cmcourier:*`.

Para tu batch sintético probablemente vas a **necesitar apuntar cada
IDRVI en el CSV generado al mismo tipo `D:cmcourier:bacDoc`**, si no
el pre-flight `cm-targets` en el Paso 5 falla para los otros 19 tipos.
O:

- (a) Bajar `--idrvi-top 1` en el Paso 3a así solo se usa un IDRVI.
- (b) Copiar `reference-data/csv/MapeoRVI_CM.csv` a
  `sample/MapeoRVI_CM.csv` y setear
  `CMISType=D:cmcourier:bacDoc` +
  `CMISFolder=/cmcourier-staging/<idrvi>` en cada fila que
  tu RVABREP toca (usá la distribución de IDRVI del output
  de `cmcourier mock rvabrep` para saber cuáles 20 necesitás).

### CSV de trigger

Los triggers NO se auto-generan por 039 todavía — derivalos del
RVABREP. Shell rápido:

```bash
echo "ShortName,CIF,SystemID" > sample/triggers.csv
tail -n +2 sample/rvabrep-50k.csv \
  | awk -F, -v OFS=, '!seen[$1]++{print $1, $5, $2}' \
  >> sample/triggers.csv
```

## Paso 4 — Cablear la config

Copiá `scripts/staging/config-staging.yaml.template` a
`sample/config-staging.yaml`. Editá:

```yaml
trigger:
  csv_path: sample/triggers.csv

indexing:
  source:
    kind: csv
    csv_path: sample/rvabrep-50k.csv

mapping:
  rvi_cm_csv_path: sample/MapeoRVI_CM.csv      # o reference-data/csv/...
  metadatos_csv_path: sample/MetadatosCM.csv   # o reference-data/csv/...

assembly:
  source_root: sample/files
  temp_dir:    sample/tmp

tracking:
  db_path: sample/tracking.db

cmis:
  base_url: "http://<compu-b>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser"
  repo_id: ""                       # 040: Alfresco quiere vacío acá, NO "-default-"
  workers: 4
  max_bandwidth_mbps: 20.0   # LAN; remover el cap en Tailscale.

observability:
  log_dir: sample/logs
  unmask_pii: false          # 038 — mantener false fuera de debugging activo.
```

Env vars (Constitución V — credenciales solo vía env):

```bash
export CMIS_USERNAME=admin
export CMIS_PASSWORD=admin
```

## Paso 5 — Pre-flight contra Alfresco

Dos gates, en orden. Stop y arreglar en cualquier FAIL.

```bash
# 5a. Conexiones + tipos + dry-run del primer doc.
cmcourier doctor -c sample/config-staging.yaml

# 5b. Grupo cm-targets (038) — verifica que cada CMISType distinto tenga
#     una typeDefinition, cada CMISFolder distinto exista, y cada
#     par (CMISType, CMISPropertyId) se alinee con el
#     propertyDefinitions del tipo.
cmcourier doctor -c sample/config-staging.yaml --check cm-targets
```

Fallos comunes y fixes:

| Check | Fallo | Fix |
| --- | --- | --- |
| `cm_type_alignment` | tipo `D:cmcourier:bacDoc` desconocido | re-correr `register-model.sh` en Compu B |
| `cm_type_alignment` | tipo `$t!-...v-1` desconocido | te olvidaste de setear `CMISType=D:cmcourier:bacDoc` en la fila del mapping |
| `cmis_folders_exist` | carpeta faltante | Paso 2 — pre-crearla en CMIS |
| `cmis_properties_alignment` | propiedad faltante en el tipo | typo en `MetadatosCM.CMISPropertyId` |

## Paso 6 — Correr el pipeline

Primera corrida conservadora — batch chico con TUI off así podés
leer las métricas:

```bash
cmcourier csv-trigger-pipeline run \
  -c sample/config-staging.yaml \
  --total 100 \
  --no-tui
```

Qué mirar:

- Exit code 0; la DB de tracking muestra 100 `S5_DONE`.
- `sample/logs/<batch_id>/metrics.jsonl` contiene 100 eventos
  `s5_upload_attempt` (038). Correr:
  ```bash
  jq -c 'select(.event=="s5_upload_attempt") | {txn_num, object_type_id}' \
    sample/logs/<batch_id>/metrics.jsonl | head -5
  ```
- Sin eventos `s5_upload_failed`. Si aparece alguno, el evento
  estructurado lleva `status_code`, `response_body` truncado, y un
  `curl_equivalent` ejecutable que podés pegar en una terminal para
  reproducir.

Escalá una vez que el smoke esté verde:

```bash
cmcourier csv-trigger-pipeline run \
  -c sample/config-staging.yaml \
  --total 50000           # el batch sintético completo
```

### Corriendo con TUI (0.44.0+)

Quitá `--no-tui` y el dashboard Textual lanza en la misma
terminal. A partir de 0.44.0 el dashboard ya no compite con
``log.info()`` por la pantalla — el handler de stderr queda
desconectado por la vida del TUI, así que el frame del dashboard
queda limpio. Los logs siguen fluyendo a ``sample/logs/app-YYYY-MM-DD.log``;
tail-eá ese archivo en una segunda terminal si querés seguirlos live.

Qué mirar en el TUI:

- **Tab UPLOAD** — la barra de progreso muestra docs (``9 / 22``) con
  ``MB uploaded / MB planned`` a la derecha de la misma línea; la
  línea siguiente muestra ``chunk elapsed HH:MM:SS   avg X.XX MB/s   est
  remaining HH:MM:SS``. El ETA se oculta hasta que el chunk cruza
  5 % de completitud.
- **Tab CHUNKS** (solo multi-batch — ``batches_in_flight=2``) —
  fila por-chunk con docs, MB, ``PREP done/skip/fail (elapsed)``,
  ``UPLOAD done/skip/fail (elapsed)`` y una fila agregada ``TOTAL``
  abajo. Chunks QUEUED renderean ``—/—/—`` en las columnas de stage
  para que de un vistazo se distinga "todavía no" de "cero outcomes".

## Paso 7 — Verificar en Alfresco

```bash
# 7a. Contar docs del tipo custom en el servidor.
curl -s -u admin:admin -G \
  --data-urlencode "q=SELECT COUNT(*) AS n FROM cmcourier:bacDoc" \
  --data "cmisselector=query" \
  "http://<compu-b>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser" \
  | python3 -m json.tool

# 7b. Samplear 3 docs con sus propiedades custom (valores crudos aparecen
#     en la respuesta de query CMIS — esto es CMIS directo, no el
#     stream de eventos de cmcourier).
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

## Paso 8 — Tear down

```bash
# Compu A
rm -rf sample/

# Compu B
docker compose -f alfresco-compose.yml down -v   # -v borra Postgres + contentstore
```

La imagen de Alfresco queda cacheada (~3 GB) así el próximo setup corre
el Paso 1 en ~30s. El keystore en `alfresco-extension/keystore/keystore`
se preserva entre `down -v` — no se necesita re-generarlo.

El modelo de contenido custom vive en Postgres — `down -v` lo dropea.
Re-correr `register-model.sh` en el Paso 2 después de un wipe.

## Caveats

- **Alfresco no es IBM CM.** El browser binding 1.1 es el mismo protocolo
  pero los esquemas de auth, los bodies de respuestas de error, la sintaxis
  de id de tipo, y el soporte de `cmisselector` difieren. Notablemente,
  Alfresco 23.4.1 NO soporta `cmisselector=object` o `cmisselector=properties` —
  fetchear un documento específico necesita `cmisselector=query` con una
  cláusula CMIS-SQL `WHERE cmis:objectId = '...'`.
- **El modelo de contenido es un fixture**, no una copia fiel del
  del banco. Si el banco declara 200 tipos en producción, esta
  simulación corre con 1. El `--idrvi-top 20` del generador 039 va a
  generar 20 IDRVIs distintos, todos los cuales necesitan apuntar al
  único tipo de staging vía `CMISType=D:cmcourier:bacDoc` en el
  mapping (ver Paso 3 (b)).
- **El default de enmascaramiento PII está ON.** Los eventos
  `s5_upload_attempt` / `s5_upload_failed` en `metrics.jsonl` no van
  a llevar valores crudos de CIF / Nombre_Cliente / NUM_CUENTA. Para
  desenmascarar para debugging activo setear
  `observability.unmask_pii: true` en la config — el doctor emite un
  WARN `unmask_pii_active` al startup así no te olvidás de revertirlo.
- **Presupuesto de memoria**: Alfresco 23.x defaultea a 4 GB JVM. Si Compu B
  tiene 8 GB total, dejá 2 GB de headroom. Editá `JAVA_OPTS` en
  `alfresco-compose.yml` para apretarlo si hace falta.
- **Cardinalidad de shortname sintético**: el lexicon del generador 039
  es 15 nombres × 100 sufijos numéricos = 1500 shortnames únicos. Con
  `--clients 5000` y 50k filas en realidad ves ≈1500 clientes distintos
  (avg ~33 docs/cliente). Esto es lo suficientemente realista para
  staging — power-users en datos reales lucen similar.

## Cross-references

- Runbook genérico: `docs/how-to/staging-dry-run.md`.
- Generador sintético RVABREP (039): `docs/how-to/mock-rvabrep-generator.md`.
- Pre-flight de destino CMIS (038): `docs/how-to/cmis-target-preflight.md`.
- Doctor: `cmcourier doctor --help`.
- Cache cross-batch de metadatos (037): `docs/how-to/document-cache.md`.
- Lanes heavy/light (036): `docs/how-to/heavy-light-lanes.md`.
- Orquestador multi-batch (028): `docs/how-to/multi-batch.md`.
- Analizador offline de logs: `docs/how-to/log-analysis.md`.
- Scripts de scaffolding staging: `scripts/staging/README.md`.

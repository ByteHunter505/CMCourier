# How-to: Validation Checklist (full E2E, cross-platform)

Checklist comprensivo para validar que **CMCourier funciona en todos sus
modos** contra una instancia local de Alfresco staging. Cubre setup
inicial (config + env vars + dataset), conexiones, los 5 pipelines,
orquestación, observabilidad, y validación post-upload en Alfresco.

**Plataformas soportadas**: Linux, macOS, Windows. Cuando un comando
difiere por plataforma vas a ver bloques separados **Bash (Linux/macOS)**
y **PowerShell (Windows)**. Lo demás corre igual en todas.

> **Alcance**: este doc asume que el stack de Alfresco local (per
> `local-staging-simulation.md`) ya está corriendo en una IP accesible
> con admin/admin. Si no, levantalo primero. NO cubre AS400 real ni el
> CMIS productivo de IBM CM (ver §N — "lo que NO podés testear acá").
>
> **Filosofía**: cada test tiene **comando exacto**, **qué esperar**, y
> **cómo verificar**. Si algo falla, no avances al siguiente test —
> arreglá y reintentá. Los problemas en escala son problemas en N=1
> escondidos.

---

## §0. Setup inicial — leé esto SIEMPRE primero

### §0.1 — Pre-requisitos del sistema

| Item | Linux/macOS | Windows |
| --- | --- | --- |
| Python 3.11+ | `python3 --version` | `python --version` |
| Git | `git --version` | `git --version` |
| curl (HTTP probes) | viene con el SO | Windows 10 1803+ ya lo trae como `curl.exe`. Confirmá con `curl.exe --version` |
| ODBC driver IBM i Access (solo si vas a tocar AS400 real) | `odbcinst -j` lista los drivers | Panel de Control → "Administrador de orígenes de datos ODBC" → pestaña Drivers |

> **Importante en Windows (PowerShell):** `curl` es un alias de
> `Invoke-WebRequest` por defecto. Para los probes de CMIS de abajo
> usá **`curl.exe`** (la herramienta real) o `Invoke-RestMethod`. Si
> escribís `curl` a secas, PowerShell ejecuta otra cosa.

### §0.2 — Instalar CMCourier en modo editable

**Bash (Linux/macOS):**

```bash
git clone <repo> CMCourier
cd CMCourier
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

**PowerShell (Windows):**

```powershell
git clone <repo> CMCourier
cd CMCourier
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

> Si PowerShell bloquea la activación del venv con un mensaje de
> ExecutionPolicy, corré una vez: `Set-ExecutionPolicy -Scope
> CurrentUser -ExecutionPolicy RemoteSigned`.

Verificá la instalación:

```bash
cmcourier --version
```

### §0.3 — Crear el archivo de configuración

Partís del template incluido en `scripts/staging/`:

**Bash:**

```bash
cp scripts/staging/config-staging.yaml.template config-staging.yaml
${EDITOR:-nano} config-staging.yaml
```

**PowerShell:**

```powershell
Copy-Item scripts\staging\config-staging.yaml.template config-staging.yaml
notepad config-staging.yaml
```

Editá cada marcador `<...>` del template. Mínimo a reemplazar:

| Campo | Qué poner |
| --- | --- |
| `trigger.csv_path` | Ruta absoluta a `sample/triggers.csv` (lo genera §C) |
| `indexing.csv_path` | Ruta absoluta a `sample/rvabrep.csv` |
| `mapping.rvi_cm_csv_path` | Ruta absoluta a `sample/MapeoRVI_CM.csv` |
| `mapping.metadatos_csv_path` | Ruta absoluta a `sample/MetadatosCM.csv` |
| `metadata.sources[].csv_path` | Ruta absoluta a `sample/clients.csv` |
| `assembly.source_root` | Ruta absoluta a `sample/source_files` |
| `assembly.temp_dir` | Ruta absoluta a un dir de staging (ej. `sample/staging_tmp`) |
| `tracking.db_path` | Ruta absoluta al SQLite tracking (ej. `sample/staging-tracking.db`) |
| `observability.log_dir` | Ruta absoluta al dir de logs (ej. `sample/logs`) |
| `cmis.base_url` | URL del Alfresco staging (ej. `http://192.168.1.50:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser`) |
| `cmis.repo_id` | Valor de `repositoryId` que devuelve Alfresco en `repositoryInfo` (típicamente `-default-`) |

> **Windows — paths absolutos:** en YAML los backslashes son literales
> dentro de scalars plain (sin comillas). Tanto `C:\Users\me\sample\triggers.csv`
> como `C:/Users/me/sample/triggers.csv` funcionan; las barras normales
> son más portables si copiás el config entre equipos.

### §0.4 — Setear variables de entorno (credenciales)

Las credenciales **NUNCA** van en el YAML (Constitution Principle V).

**Bash (solo para la sesión actual):**

```bash
export CMIS_USERNAME=admin
export CMIS_PASSWORD=admin
# Solo si vas a usar AS400 real (no aplica al staging local):
# export AS400_USERNAME=...
# export AS400_PASSWORD=...
```

Para persistir entre sesiones agregalas a `~/.bashrc` o `~/.zshrc`.

**PowerShell (solo para la sesión actual):**

```powershell
$env:CMIS_USERNAME = "admin"
$env:CMIS_PASSWORD = "admin"
# Solo si vas a usar AS400 real (no aplica al staging local):
# $env:AS400_USERNAME = "..."
# $env:AS400_PASSWORD = "..."
```

**PowerShell (persistente — sobrevive reinicios):**

```powershell
[Environment]::SetEnvironmentVariable("CMIS_USERNAME", "admin", "User")
[Environment]::SetEnvironmentVariable("CMIS_PASSWORD", "admin", "User")
# Tenés que abrir una nueva terminal para que se carguen.
```

Verificá:

**Bash:**

```bash
echo "$CMIS_USERNAME / $CMIS_PASSWORD"   # debe imprimir admin / admin
```

**PowerShell:**

```powershell
"$env:CMIS_USERNAME / $env:CMIS_PASSWORD"
```

### §0.5 — Confirmar que Alfresco responde

Reemplazá `<HOST>` por la IP/host del Alfresco staging.

**Bash:**

```bash
curl -fsS -u admin:admin \
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=repositoryInfo" \
  | head -c 200
```

**PowerShell:**

```powershell
curl.exe -fsS -u admin:admin `
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=repositoryInfo" `
  | Select-Object -First 1
```

**Espera:** JSON con `repositoryId`. Si tira 401 → credenciales mal.
Si tira "connection refused" → Alfresco no está levantado.

### §0.6 — Verificación final del setup

```bash
cmcourier --version
cmcourier doctor -c config-staging.yaml --check connections
```

**Espera:**
- `cmcourier --version` imprime versión X.Y.Z
- `doctor --check connections` termina con `exit code: 0`, todos los
  checks de conexión en `PASS` (excepto AS400 en `SKIP` si no usás AS400)

Si esto pasa, **el setup está completo**. Pasá a §A.

---

## §A. Smoke tests (≤ 5 min)

Si algo de acá falla, no tiene sentido seguir.

### A.1 — CLI viva

```bash
cmcourier --version
cmcourier --help
```

**Espera**: lista de subcomandos (`doctor`, `csv-trigger-pipeline`,
`rvabrep-pipeline`, `as400-trigger-pipeline`, `local-scan-pipeline`,
`single-doc`, `batch`, `inspect`, `as400-query`, `background`,
`analyze`, `completion`, `sync`, `mock`, `cache`).

### A.2 — Shell completion

> **Solo Linux/macOS por ahora.** `cmcourier completion` emite scripts
> para `bash | zsh | fish`. **PowerShell no está soportado** (gap
> conocido); en Windows salteá este test.

**Bash:**

```bash
cmcourier completion bash > "$HOME/.cmc-completion.bash"
source "$HOME/.cmc-completion.bash"
cmcourier <TAB><TAB>      # debe autocompletar
```

**Espera**: el TAB completa los subcomandos. Si querés que persista,
agregá `source ~/.cmc-completion.bash` a tu `~/.bashrc`.

### A.3 — Help en cada grupo

```bash
cmcourier doctor --help
cmcourier rvabrep-pipeline run --help
cmcourier mock generate --help
cmcourier inspect --help
cmcourier analyze --help
cmcourier cache --help
```

**Espera**: cada help imprime sus opciones sin estallar.

---

## §B. Conexiones — `cmcourier doctor`

`doctor` corre nueve checks agrupados en cuatro categorías. Los podés
correr todos o filtrar uno solo:

```bash
cmcourier doctor --config config-staging.yaml                       # todos (default)
cmcourier doctor --config config-staging.yaml --check connections   # solo connections
cmcourier doctor --config config-staging.yaml --check mapping
cmcourier doctor --config config-staging.yaml --check metadata
cmcourier doctor --config config-staging.yaml --check cm-types
```

### Los nueve checks

| Check | Qué valida | Categoría |
| --- | --- | --- |
| `log_dir_writable` | `observability.log_dir` se puede crear/escribir | connections |
| `cmis_connectivity` | `cmis.base_url` responde 200 con admin/admin | connections |
| `as400_connectivity` | `as400.*` configurado y JDBC responde (SKIP si no hay AS400) | connections |
| `tracking_openable` | SQLite `tracking.db_path` abre en WAL mode | connections |
| `as400_sync` | NIARVILOG accesible (SKIP si no hay AS400) | connections |
| `mapping_completeness` | `MapeoRVI_CM.csv` + `MetadatosCM.csv` cargan ≥1 row | mapping |
| `metadata_sources` | cada `metadata.sources[].csv_path` carga ≥1 row | metadata |
| `cm_type_alignment` | cada `cm_object_type` derivado existe vía CMIS `getTypeDefinition` | cm-types |
| `sample_dry_run` | corre S1→S4 sobre el primer doc del primer trigger | mapping |

**Estado esperado en local staging**:

- `log_dir_writable` = ✅ PASS
- `cmis_connectivity` = ✅ PASS
- `as400_connectivity` = ⏭️ SKIP (no hay AS400 acá)
- `tracking_openable` = ✅ PASS
- `as400_sync` = ⏭️ SKIP
- `mapping_completeness` = ✅ PASS
- `metadata_sources` = ✅ PASS
- `cm_type_alignment` = ✅ PASS — el bootstrap del stack staging
  registra el modelo `cmcourier:bacDoc` vía
  `scripts/staging/register-model.sh` (POST a `/alfresco/service/cmm/<modelName>`
  + extension keystore mount). Si fallás acá, el bootstrap del
  Alfresco no quedó completo — re-correr el script.
- `sample_dry_run` = ✅ PASS

Exit code: `0` si nada falla, `1` si hay FAILs.

**Si `cm_type_alignment` falla pese al bootstrap**: editá
MapeoRVI_CM.csv y poné `CMISType=cm:content` en las rows del tipo
afectado como fallback (perdés las propiedades custom pero el
upload pasa).

---

## §C. Dataset sintético — `cmcourier mock generate`

Genera un árbol RVABREP con CSVs y archivos fuente. El comando es
idéntico en todas las plataformas.

### C.1 — Crear el directorio destino

**Bash:**

```bash
mkdir -p sample
```

**PowerShell:**

```powershell
New-Item -ItemType Directory -Force -Path sample | Out-Null
```

### C.2 — Dataset chico (smoke, ~10 docs)

```bash
cmcourier mock generate --output-root sample --pdf-min 50kb --pdf-max 200kb --img-min 10kb --img-max 100kb --limit 10 --seed 42
```

**Espera al final**:
```
Planned X files (Y.Z MB) under sample/...
Wrote sample/triggers.csv (10 rows)
Wrote sample/rvabrep.csv (10 rows)
Wrote sample/MapeoRVI_CM.csv + MetadatosCM.csv + clients.csv
```

**Verificar** (cross-platform Python one-liner):

```bash
python -c "import pathlib; root=pathlib.Path('sample'); [print(p.name.ljust(20), p.stat().st_size, 'bytes') for p in sorted(root.glob('*.csv'))]"
python -c "import pathlib; print('source_files entries:', sum(1 for _ in pathlib.Path('sample/source_files').rglob('*') if _.is_file()))"
```

### C.3 — Dataset mediano (100 docs, mezcla pesado/liviano para §F.3)

```bash
cmcourier mock generate --output-root sample-100 --pdf-min 100kb --pdf-max 5mb --img-min 20kb --img-max 200kb --limit 100 --seed 100
```

### C.4 — Dataset heavy (para validar lanes pesado/liviano del §F.3)

```bash
cmcourier mock generate --output-root sample-heavy --pdf-min 8mb --pdf-max 30mb --img-min 50kb --img-max 200kb --limit 50 --seed 200
```

> **Tip**: el flag `--seed` hace la generación **determinista**. Mismo
> seed = mismo árbol, mismos hashes. Útil para reproducir resultados
> entre runs.

> **Importante**: después de generar el dataset, **volvé al §0.3 y
> actualizá las rutas absolutas** en `config-staging.yaml` apuntando
> al `sample/` que acabás de crear.

---

## §D. Inspección sin correr la pipeline — `cmcourier inspect`

Permite consultar mapping/triggers SIN tocar Alfresco. Ideal para
debuggear configs. Todos los comandos son cross-platform.

### D.1 — Stats del mapping

```bash
cmcourier inspect mapping-stats --config config-staging.yaml
```

**Espera**: histograma de `cm_object_type` distintos, conteo de rows,
campos requeridos, etc.

### D.2 — Inspeccionar un mapping específico

```bash
cmcourier inspect mapping --config config-staging.yaml <ID_RVI>
```

Reemplazá `<ID_RVI>` con un valor real de la columna `IDDoc` (o lo que
use tu MapeoRVI_CM).

### D.3 — Inspeccionar un trigger

```bash
cmcourier inspect trigger --config config-staging.yaml --limit 10
```

Lista los primeros 10 triggers con su `ShortName/CIF/SystemID`.

### D.4 — Inspeccionar lo que el RVABREP scanner ve para un doc

```bash
cmcourier inspect rvabrep --config config-staging.yaml <SHORTNAME> <SYSTEM_ID>
```

Útil para ver qué archivos físicos resuelve el scanner para un doc en
particular.

---

## §E. Pipelines — uno por uno, escala creciente

CMCourier tiene **5 pipelines**. Validá cada uno con escala 1 → 10 → 100
docs antes de meterte con uno nuevo. Todos los comandos `cmcourier` son
cross-platform.

### E.1 — `csv-trigger-pipeline` (CSV-driven)

Pipeline canónico: lee triggers de un CSV, scannea RVABREP, ensambla,
sube.

#### Smoke (1 doc)

```bash
cmcourier csv-trigger-pipeline run --config config-staging.yaml --total 1 --no-tui
```

**Espera**:
- `S0_LOADED ... 1 trigger`
- `S5_DONE ... cmis_id=<uuid>`
- exit code 0
- `logs/<batch_id>/metrics.jsonl` creado

**Verificar en Alfresco**:

**Bash:**

```bash
curl -s -u admin:admin \
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=object&objectId=<uuid>" \
  | python -m json.tool
```

**PowerShell:**

```powershell
curl.exe -s -u admin:admin `
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=object&objectId=<uuid>" `
  | python -m json.tool
```

#### Mediano (10 docs, sin TUI)

```bash
cmcourier csv-trigger-pipeline run --config config-staging.yaml --total 10 --no-tui
```

#### Mediano con TUI (validar la UI tipo dashboard)

```bash
cmcourier csv-trigger-pipeline run --config config-staging.yaml --total 10
# (TUI default ON — tabs S0→S5, métricas en vivo)
```

**Espera en TUI**:
- Tab "stages" muestra S0..S5 con counters
- Tab "metrics" muestra throughput, latencias p50/p95
- Sale solo cuando termina

#### Full (100 docs)

```bash
cmcourier csv-trigger-pipeline run --config config-staging.yaml --total 100
```

### E.2 — `rvabrep-pipeline` (no CSV trigger, scanner directo)

Pipeline para cuando NO hay un CSV trigger — escanea el árbol RVABREP
directamente.

```bash
cmcourier rvabrep-pipeline run --config config-staging.yaml --total 10 --no-tui
```

**Espera**: similar a E.1 pero S0 reporta "scanner-driven" en vez de
"csv-driven".

### E.3 — `as400-trigger-pipeline`

⚠️ **No la podés probar localmente** sin AS400. Si tenés acceso a un
AS400 staging:

```bash
cmcourier as400-trigger-pipeline run --config config-staging-as400.yaml --total 5 --no-tui
```

Sino, salteá esto.

### E.4 — `local-scan-pipeline`

Pipeline para escenarios donde los archivos ya fueron extraídos a un
directorio local. El trigger ES el archivo: cada `.PDF` / `.001` en
`scan_path` se cross-referencia contra RVABREP por nombre de archivo
y produce **exactamente un doc** (modelo polimórfico de trigger, 046).

```bash
cmcourier local-scan-pipeline run --config config-staging-localscan.yaml --total 5 --no-tui
```

(Necesita una sección `trigger.kind: local_scan` + `trigger.scan_path`
en el YAML.)

**Espera (0.49.0+)**: `total_triggers == total_docs == N` donde N es
la cantidad de archivos escaneados (capada por `--total`). Pre-046 el
modelo de trigger expandía cada archivo a TODOS los docs del cliente
dueño — un pool de 100 archivos subía ~1800 docs. Post-046: 100
archivos → 100 docs, uno por archivo.

### E.5 — `single-doc run` (un doc a mano)

Útil para reproducir un doc específico sin trigger.

```bash
cmcourier single-doc run --config config-staging.yaml --shortname ACME-001 --system PROD --cif 12345678 --no-tui
```

**Espera**: corre S0→S5 para EXACTAMENTE ese doc. Útil para reproducir
bugs reportados.

---

## §F. Orchestration features

### F.1 — TUI on/off

```bash
# default ON
cmcourier rvabrep-pipeline run --config config-staging.yaml --total 5

# explicit off (para CI / cron / Task Scheduler / si no hay TTY)
cmcourier rvabrep-pipeline run --config config-staging.yaml --total 5 --no-tui
```

### F.2 — Multi-batch (N=2 producer-consumer)

YAML: `processing.batches_in_flight: 2` (default). Override CLI:

```bash
# forzar single-batch (legacy)
cmcourier rvabrep-pipeline run --config config-staging.yaml --total 50 --batches-in-flight 1 --no-tui

# forzar N=2 (default) — un batch S5 mientras otro hace S0-S4
cmcourier rvabrep-pipeline run --config config-staging.yaml --total 50 --batches-in-flight 2 --no-tui
```

**Comparar tiempos**: ver §K.2 (`analyze compare`).

### F.3 — Heavy/light lanes

En `config-staging.yaml`:

```yaml
processing:
  heavy_light_lanes:
    enabled: true
    heavy_threshold_bytes: 10485760    # 10 MB
    heavy_lane_min_batch: 50
    heavy_initial_ratio: 0.25
    rebalance_interval_s: 10.0
    idle_threshold_s: 15.0
```

Validá con el dataset heavy del §C.4:

```bash
# corrida sin lanes
cmcourier rvabrep-pipeline run --config config-no-lanes.yaml --total 50 --no-tui
# corrida con lanes
cmcourier rvabrep-pipeline run --config config-with-lanes.yaml --total 50 --no-tui
```

**Espera con lanes ON**: throughput global mayor + p95 más bajo, porque
los archivos chicos no quedan head-of-line bloqueados detrás de un PDF
de 30 MB.

### F.4 — AIMD auto-tune (S5 worker pool)

```yaml
cmis:
  workers: 4
  auto_tune:
    enabled: true
    min_threads: 2
    max_threads: 16
    target_p95_ms: 3000.0
    adjustment_interval_s: 15
    timeout_auto_adjust: true
```

Corré con suficiente carga para que el auto-tune adapte:

```bash
cmcourier rvabrep-pipeline run --config config-staging.yaml --total 200 --no-tui
```

**Verificar convergencia** (post-run, cross-platform). El controller
emite `auto_tune_decision` records en el **app log** (NO en
metrics.jsonl):

```bash
python -c "import json,sys,pathlib; p=pathlib.Path(sys.argv[1]); [print(json.dumps(json.loads(l),indent=2)) for l in p.read_text().splitlines() if '\"msg\":\"auto_tune_decision\"' in l][:50]" sample/logs/app-$(date +%F).log
```

**Espera**: events cada `adjustment_interval_s` (default 15s). Cada
record carry `action`, `p95_observed_ms`, `p95_target_ms`,
`workers_before`, `workers_after`, `timeout_before_s`,
`timeout_after_s`. Acciones canónicas:

- `warmup` — primeros ticks antes del primer ajuste real.
- `+1` — additive increase (p95 < target).
- `halve` — multiplicative decrease (p95 > target).
- `noop` — dentro de la banda de tolerancia.

⚠️ Antes de 0.46.0 (spec 043), en multi-batch (`batches_in_flight≥2`)
el `p95_observed_ms` siempre reportaba `0.0` porque el controller
estaba bound al recorder del pipeline en vez del del chunk en S5.
Si vés p95=0 en toda la corrida y workers que sólo crecen, asegurate
de estar en 0.46.0+.

---

## §G. Metadata pipeline

### G.1 — Field aliases

En `metadata.field_aliases` mapeás un nombre lógico a otro:

```yaml
metadata:
  field_aliases:
    CIF: BAC_CIF
```

**Test**: corré `inspect mapping <ID>` y verificá que la columna
resuelva al nombre aliaseado.

### G.2 — Metadata sources

```yaml
metadata:
  sources:
    - kind: csv
      alias: clients
      csv_path: /abs/path/clients.csv
  field_sources:
    Nombre_Cliente:
      sources:
        - source_type: "csv:clients"
          lookup_key_column: CIF
          lookup_value_column: Nombre_Cliente
```

**Validar**:
1. `cmcourier doctor --check metadata` — debe PASS.
2. `cmcourier inspect mapping <ID>` — el campo `Nombre_Cliente` debe
   resolver al valor del CSV `clients`.

### G.3 — Prefetch ON

```yaml
metadata:
  prefetch_enabled: true
```

**Efecto esperado**: el `MetadataResolver` precarga el(los) CSV(s)
declarados en `metadata.sources` en un `dict[(alias,key_col,val_col,key), value]`
**al construir el resolver**, una sola vez por run. S3 metadata
resolution se vuelve un dict-lookup en lugar de un csv-scan por doc.

**Verificar** (no hay event explícito — el prefetch es silencioso):

1. `cmcourier doctor --check metadata` reporta `[PASS] metadata_sources
   — N metadata sources, all non-empty` con la cardinalidad de cada
   CSV cargado.
2. Después de cualquier corrida, las latencias S3 del batch_summary
   en `metrics.jsonl` deben estar en **microsegundos**, no
   milisegundos: `S3.p50_ms < 0.1` indica prefetch activo
   (sin prefetch sería 100-500µs por lookup csv).

### G.4 — Cross-batch cache (037)

```yaml
metadata:
  cache:
    enabled: true
    ttl_minutes: 60
```

**Test**:
```bash
# Run 1 — cold cache
cmcourier rvabrep-pipeline run --config config-staging.yaml --total 50 --no-tui
# Run 2 — warm cache (mismo dataset)
cmcourier rvabrep-pipeline run --config config-staging.yaml --total 50 --no-tui
```

**Verificar speedup**:
```bash
cmcourier cache stats --config config-staging.yaml
```

**Espera**: el cache se llena en run 1 (`document_cache rows : N`
en `cache stats` ≈ docs procesados). Run 2 ve un speedup operacional
**enorme** (~100× en nuestro staging: 283s → 2.6s) — pero el
speedup NO viene del cache S3, viene de la idempotencia
**cross-batch** a nivel S1 (`is_uploaded(txn)` short-circuita
antes de llegar a S3). El cache es secundario: ayuda en escenarios
"crash entre S3 y S5 + resume del mismo batch", donde los docs ya
resolvieron metadata pero no se uploadearon.

Para ver hit-rate efectivo del cache S3, hace falta forzar un
escenario donde los docs NO estén ya `S5_DONE` en la tracking DB
pero sí en el cache — por ejemplo, wipear sólo `migration_log`
preservando `document_cache` entre runs. Esto es un test de
debugging, no parte del happy path.

**Limpiar cache**:
```bash
cmcourier cache clear --config config-staging.yaml
```

---

## §H. Resume + idempotency

### H.1 — Resume tras corte

**Bash:**

```bash
# Run 1 — kill mid-batch
cmcourier rvabrep-pipeline run --config config-staging.yaml \
  --batch-id RESUME-TEST --total 100 --no-tui &
RUN_PID=$!
sleep 30 && kill -9 $RUN_PID

# Run 2 — resume
cmcourier rvabrep-pipeline run --config config-staging.yaml \
  --batch-id RESUME-TEST --resume --no-tui
```

**PowerShell:**

```powershell
# Run 1 — kill mid-batch
$proc = Start-Process -FilePath cmcourier `
  -ArgumentList 'rvabrep-pipeline','run','--config','config-staging.yaml','--batch-id','RESUME-TEST','--total','100','--no-tui' `
  -PassThru -NoNewWindow
Start-Sleep -Seconds 30
Stop-Process -Id $proc.Id -Force

# Run 2 — resume
cmcourier rvabrep-pipeline run --config config-staging.yaml `
  --batch-id RESUME-TEST --resume --no-tui
```

**Espera**: el run 2 detecta el batch existente, lee el último stage
completado, y arranca desde ahí sin re-subir docs ya marcados
`S5_DONE`.

**Verificar** (cross-platform — Python stdlib sqlite3):

```bash
python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); [print(r) for r in c.execute(\"SELECT status, COUNT(*) FROM migration_log WHERE batch_id='RESUME-TEST' GROUP BY status\")]" sample/staging-tracking.db
```

### H.2 — `--from-stage` (saltear stages)

Para reprocesar solo desde una etapa específica (después de cambiar
una config, por ejemplo):

```bash
cmcourier rvabrep-pipeline run --config config-staging.yaml \
  --batch-id RESUME-TEST --from-stage 3 --no-tui
```

**Espera**: arranca desde S3 (metadata) reusando el work de S0-S2.

---

## §I. Background runner

Cron-friendly en Linux, Task Scheduler-friendly en Windows. Lock file
por config, quiet on success.

```bash
# Foreground primero, para validar que no estalla
cmcourier background --pipeline rvabrep --config config-staging.yaml
```

### I.1 — Lock file behavior

Abrí dos terminales.

**Terminal 1:**

```bash
cmcourier background --pipeline rvabrep --config config-staging.yaml
```

**Terminal 2 (mientras corre la 1):**

```bash
cmcourier background --pipeline rvabrep --config config-staging.yaml
# Espera: "another instance is running" + exit code 75 (EX_TEMPFAIL)
```

Verificar el exit code:

**Bash:** `echo $?`
**PowerShell:** `$LASTEXITCODE`

### I.2 — Agendar corrida recurrente

**Linux/macOS — cron:**

```bash
crontab -l > current-cron.txt 2>/dev/null
echo '*/15 * * * * /full/path/to/.venv/bin/cmcourier background --pipeline rvabrep --config /abs/config-staging.yaml' >> current-cron.txt
crontab current-cron.txt
crontab -l   # verificar
```

**Windows — Task Scheduler:**

```powershell
# Tarea cada 15 minutos, usuario actual, no requiere admin
$action = New-ScheduledTaskAction `
  -Execute "C:\path\to\.venv\Scripts\cmcourier.exe" `
  -Argument "background --pipeline rvabrep --config C:\abs\config-staging.yaml"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 15) `
  -RepetitionDuration (New-TimeSpan -Days 365)
Register-ScheduledTask -TaskName "CMCourierBackground" `
  -Action $action -Trigger $trigger -Description "CMCourier background runner"

# Verificar:
Get-ScheduledTask -TaskName "CMCourierBackground"

# Quitar cuando termines:
# Unregister-ScheduledTask -TaskName "CMCourierBackground" -Confirm:$false
```

---

## §J. Observabilidad runtime

### J.1 — Tier-5 system metrics (psutil)

En `config-staging.yaml`:

```yaml
observability:
  system_metrics:
    enabled: true
    sample_interval_s: 5.0
```

**Espera durante el run**: el daemon `cmcourier-syssampler` thread
toma snapshots cada 5s. Los samples viven en
**`sample/logs/system-YYYY-MM-DD.jsonl`** (NO en `metrics.jsonl`)
y son raw records con shape directa — sin campo `event`. Cada
record carry `ts_iso`, `cpu_pct`, `ram_used_mb`, `ram_total_mb`,
`disk_read_mbps`, `disk_write_mbps`, `net_in_mbps`, `net_out_mbps`,
`process_pid`, `process_threads`, `process_cpu_pct`, `process_rss_mb`,
`active_workers`.

**Verificar** (cross-platform):

```bash
python -c "import json,sys,pathlib; lines=[l for l in pathlib.Path(sys.argv[1]).read_text().splitlines() if l.strip()]; print(f'system samples: {len(lines)}'); print(f'first: {json.loads(lines[0])[\"ts_iso\"]}'); print(f'last:  {json.loads(lines[-1])[\"ts_iso\"]}')" sample/logs/system-$(date +%F).jsonl
```

### J.2 — Estructura real de los logs

CMCourier emite events distribuidos en **5 archivos por tier**
(REBIRTH §17.4 + spec 027). La pestaña abajo lista cada archivo,
los msg/event canónicos que aparecen, y cómo grepearlos. Los
records son JSON-line (jsonl) excepto `app-*.log` que es JSON
sobre líneas también.

| Archivo | Logger | Records canónicos | Notas |
|---|---|---|---|
| `app-YYYY-MM-DD.log` | `cmcourier.*` (root) | `stage_complete` (cada S0..S5 lo emite con `stage=Sn` + `duration_ms` + `outcome`), `auto_tune_decision` (043+ si AIMD ON), `doctor_pass`, `document_cache hit/miss`, `resume_resolved`, `resume_explicit_from_stage`, `background_started`, `background_lock_held` | rotated por día |
| `metrics-YYYY-MM-DD.jsonl` | `cmcourier.metrics.pipeline` | `batch_summary` (uno por batch completado, con `total_docs`, `elapsed_s`, `throughput_docs_per_s`, `stages.S0..S5` con `count/p50_ms/p95_ms/p99_ms/sum_ms`) | rotated por día |
| `network-YYYY-MM-DD.jsonl` | `cmcourier.metrics.network` | `cmis_get`, `cmis_upload`, `s5_upload_attempt` (038+), `s5_upload_failed` (038+), `s5_upload_409_recovery_attempt`/`_recovered`/`_recovery_failed` (045+) | rotated por día |
| `slow-ops-<batch_id>.jsonl` | (file directo) | top-N slow ops del batch (cada uno con `rank`, `kind`, `duration_ms`, `txn_num`, `stage`) — N = `slow_op_top_n` | un archivo por batch |
| `system-YYYY-MM-DD.jsonl` | (file directo, psutil) | snapshots crudos del proceso + host cada `sample_interval_s` | ver J.1 |

**Grep canónico** (Bash):

```bash
# Per-stage timing (S0..S5 individuales)
rg '"stage": "S5"' sample/logs/app-$(date +%F).log | head -5

# Batch summary del batch X
rg "batch_summary" sample/logs/metrics-$(date +%F).jsonl

# AIMD decisions
rg "auto_tune_decision" sample/logs/app-$(date +%F).log

# 409 recoveries (045+)
rg "s5_upload_409_recovered" sample/logs/network-$(date +%F).jsonl
```

---

## §K. Log analysis offline — `cmcourier analyze`

Todos los comandos `analyze` son cross-platform.

### K.1 — Análisis de un batch

```bash
cmcourier analyze batch <BATCH_ID> --config config-staging.yaml
cmcourier analyze batch <BATCH_ID> --config config-staging.yaml --format json
```

**Espera**: throughput, latencias p50/p95/p99 por stage, slow ops top-N,
distribución de fallos.

### K.2 — Comparar dos batches

```bash
cmcourier analyze compare <BATCH_A> <BATCH_B> --config config-staging.yaml
```

Útil para A/B (ej: lanes off vs on, batches_in_flight 1 vs 2).

### K.3 — Tendencias últimos N batches

```bash
cmcourier analyze trends --last 5 --config config-staging.yaml
cmcourier analyze trends --last 10 --pipeline rvabrep-trigger --config config-staging.yaml
```

**Espera**: tabla de los últimos N batches del pipeline con throughput,
errores, duración. Detecta regresiones entre runs.

⚠️ El filter `--pipeline` matchea contra el campo `pipeline` del
`batch_summary` (que es **el nombre completo del pipeline**:
`csv-trigger-pipeline`, `rvabrep-trigger`, `as400-trigger-pipeline`,
`local-scan-pipeline`, `single-doc`). Pasarle el alias corto
(`rvabrep`, `csv`) devuelve una tabla vacía.

---

## §L. Validación post-run en Alfresco

> **Recordá**: en Windows usá `curl.exe` (no `curl` a secas). En Bash
> uses `curl` normal.

### L.1 — Conteo total de docs subidos

**Bash:**

```bash
curl -s -u admin:admin \
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=query&q=SELECT%20COUNT(*)%20FROM%20cmis:document" \
  | python -m json.tool
```

**PowerShell:**

```powershell
curl.exe -s -u admin:admin `
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=query&q=SELECT%20COUNT(*)%20FROM%20cmis:document" `
  | python -m json.tool
```

### L.2 — Listar últimos N docs

**Bash:**

```bash
curl -s -u admin:admin \
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=query&q=SELECT%20cmis:objectId,cmis:name,cmis:contentStreamLength%20FROM%20cmis:document%20ORDER%20BY%20cmis:creationDate%20DESC" \
  | python -c "import json,sys; d=json.load(sys.stdin); rows=d.get('results',[])[:10]; [print(r) for r in rows]"
```

**PowerShell:**

```powershell
curl.exe -s -u admin:admin `
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=query&q=SELECT%20cmis:objectId,cmis:name,cmis:contentStreamLength%20FROM%20cmis:document%20ORDER%20BY%20cmis:creationDate%20DESC" `
  | python -c "import json,sys; d=json.load(sys.stdin); rows=d.get('results',[])[:10]; [print(r) for r in rows]"
```

### L.3 — GET por objectId

⚠️ Conocido: el orchestrator hoy NO persiste el `cm:objectId` en
`migration_log` tras un upload exitoso (la asignación `item.cm_object_id`
sólo vive en memoria). Para obtener un OID válido, walkear una carpeta
del staging via children — es lo que el verifier post-run usa en
producción de todos modos (sin dependencia de Solr lag).

```bash
curl -s -u admin:admin \
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser/root/cmcourier-staging/CA00?cmisselector=children&maxItems=1" \
  | python -c "import json,sys; d=json.load(sys.stdin); print(d['objects'][0]['object']['properties']['cmis:objectId'])"
```

Después, traelo de Alfresco (reemplazá `<OID>` con el valor):

**Bash:**

```bash
curl -s -u admin:admin \
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=object&objectId=<OID>" \
  | python -m json.tool
```

**PowerShell:**

```powershell
curl.exe -s -u admin:admin `
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=object&objectId=<OID>" `
  | python -m json.tool
```

### L.4 — Verificar properties custom

El modelo `cmcourier:bacDoc` se registra automáticamente en Alfresco
durante el bootstrap del stack staging (`scripts/staging/register-model.sh`
+ extension folder mount). Si el doctor `cm_type_alignment` pasa, el
modelo está. Para verificar las propiedades custom de un doc subido:

**Bash:**

```bash
curl -s -u admin:admin \
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=object&objectId=<OID>" \
  | python -c "import json,sys; d=json.load(sys.stdin); props={k:v.get('value') for k,v in d.get('properties',{}).items() if k.startswith('cmcourier:')}; print(json.dumps(props, indent=2))"
```

**PowerShell:**

```powershell
curl.exe -s -u admin:admin `
  "http://<HOST>:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser?cmisselector=object&objectId=<OID>" `
  | python -c "import json,sys; d=json.load(sys.stdin); props={k:v.get('value') for k,v in d.get('properties',{}).items() if k.startswith('cmcourier:')}; print(json.dumps(props, indent=2))"
```

### L.5 — Verificar que el watchdog purgó (Linux/Docker host)

El watchdog es un script bash que corre en el host de Alfresco (Compu B,
típicamente Linux con Docker). Esto va en ESE host, no en la PC de CMCourier.

```bash
# antes de un purge
du -sh /var/lib/docker/volumes/staging_alfresco-data/_data/contentstore 2>/dev/null

# después del purge (esperá a que el watchdog ciclee)
sudo du -sh /var/lib/docker/volumes/staging_alfresco-data/_data/contentstore
```

**Espera**: el size cae a casi 0 después del purge.

---

## §M. Stress tests

### M.1 — 1000+ docs continuos

```bash
# generá un dataset grande
cmcourier mock generate --output-root sample-1k --pdf-min 100kb --pdf-max 5mb --img-min 20kb --img-max 200kb --limit 1000 --seed 1000

# corré con todo activado
cmcourier rvabrep-pipeline run --config config-staging-large.yaml --no-tui
```

Ajustá `config-staging-large.yaml` con:
- `cmis.workers: 8`
- `cmis.auto_tune.enabled: true`
- `processing.batches_in_flight: 2`
- `processing.heavy_light_lanes.enabled: true`

### M.2 — Watchdog bajo presión (en el host de Alfresco — Linux)

Este test es exclusivo del host Linux+Docker que corre Alfresco. NO
aplica a la PC donde corre CMCourier.

```bash
# en una terminal del host de Alfresco
sudo THRESHOLD_GB=2 INTERVAL_S=10 bash scripts/staging/alfresco-purge-watchdog.sh

# en la PC de CMCourier (puede ser Windows o Linux)
cmcourier rvabrep-pipeline run --config config-staging-large.yaml --no-tui
```

**Espera**: el watchdog logea purgas cada vez que el contentstore cruza
2 GB. La pipeline NO debe estallar (Alfresco sigue aceptando uploads;
los blobs purgados son antiguos, los nuevos van a parar a un store
limpio).

### M.3 — Disk pressure recovery

Llená el disco a propósito en la PC de CMCourier y verificá que S5
reporta el error de manera graceful.

**Bash (Linux/macOS):**

```bash
dd if=/dev/zero of=/tmp/filler bs=1M count=20000   # 20 GB de basura
# correr cmcourier; debería reportar errores S5 en metrics.jsonl, no crashear
rm /tmp/filler                                      # liberar
```

**PowerShell (Windows, sesión admin):**

```powershell
fsutil file createnew C:\Temp\filler 21474836480    # 20 GB exactos
# correr cmcourier; debería reportar errores S5 en metrics.jsonl, no crashear
Remove-Item C:\Temp\filler                          # liberar
```

> Si no tenés admin en Windows o `fsutil` no está disponible, usá:
> `$bytes = New-Object byte[] 1073741824; for ($i=0; $i -lt 20; $i++) { [System.IO.File]::WriteAllBytes("C:\Temp\filler-$i.bin", $bytes) }`

---

## §N. Lo que NO podés testear acá (sin extras)

| Test | Por qué no acá | Cómo testearlo |
| --- | --- | --- |
| `as400-trigger-pipeline` end-to-end | Necesita IBM i AS400 con NIARVILOG accesible | Pedí accesos a staging AS400 + ODBC driver instalado |
| AS400 distributed idempotency (034) | Idem | Idem |
| Modelo `cmcourier:bacDoc` properties | NO se registra en Alfresco 23.x Community vía bootstrap classpath (bug #5 en session memory) | Subir XML via Admin Console (`/share` → Admin Tools → Model Manager → Import) |
| CMIS rejection de tipos IBM CM (`$t!-N_BAC_…v-1`) | Alfresco no replica el syntax check de IBM CM | Solo en CMIS productivo |
| Performance "real" de WAN (latencia 50ms+, packet loss) | Vos estás contra LAN, RTT < 1ms | Correr contra el CMIS staging de la red del banco |
| Backups + restore de la DB de tracking | No es parte del pipeline activo | Validar manualmente con `sqlite3 .backup` o `python -c "import sqlite3; con=sqlite3.connect('x.db'); con.backup(sqlite3.connect('x.bak'))"` |
| Shell completion en Windows | `cmcourier completion` solo emite bash/zsh/fish (gap conocido) | Usar desde WSL si querés autocomplete |

---

## §O. Checklist resumen — copiar+pegar

Imprimí esto y andá tachando:

```
SETUP (§0)
[ ] §0.1   Python 3.11+, Git y curl/curl.exe disponibles
[ ] §0.2   venv creado + cmcourier instalado (`cmcourier --version` responde)
[ ] §0.3   config-staging.yaml editado con TODAS las rutas absolutas
[ ] §0.4   CMIS_USERNAME / CMIS_PASSWORD seteados en el shell
[ ] §0.5   curl al Alfresco responde con repositoryInfo
[ ] §0.6   doctor --check connections → todo PASS

SMOKE (§A)
[ ] §A.1   cmcourier --version
[ ] §A.2   completion bash (skip en Windows)
[ ] §A.3   help en cada grupo

CONEXIONES + DATASET (§B + §C)
[ ] §B     doctor --check all → 0 fails (AS400 SKIPped OK)
[ ] §C.2   mock generate (10 docs)
[ ] §C.3   mock generate (100 docs, opcional)

INSPECT (§D)
[ ] §D.1   inspect mapping-stats
[ ] §D.3   inspect trigger --limit 10

PIPELINES (§E)
[ ] §E.1   csv-trigger-pipeline run --total 1
[ ] §E.1   csv-trigger-pipeline run --total 10 --no-tui
[ ] §E.1   csv-trigger-pipeline run --total 10 (con TUI)
[ ] §E.1   csv-trigger-pipeline run --total 100
[ ] §E.2   rvabrep-pipeline run --total 10
[ ] §E.5   single-doc run con un shortname/system real

ORQUESTACIÓN (§F)
[ ] §F.2   batches_in_flight=1 vs 2
[ ] §F.3   heavy/light lanes off vs on (con dataset heavy de §C.4)
[ ] §F.4   AIMD auto-tune adjustments en metrics.jsonl

METADATA (§G)
[ ] §G.4   cache cold vs warm (cache stats hit_rate > 0)

RESUME (§H)
[ ] §H.1   resume tras kill / Stop-Process

BACKGROUND (§I)
[ ] §I.1   background runner + lock file rejection (exit 75)
[ ] §I.2   cron o Task Scheduler agendado

OBSERVABILIDAD (§J)
[ ] §J.1   system_metrics_snapshot events presentes

ANALYZE (§K)
[ ] §K.1   analyze batch <id> imprime stats
[ ] §K.2   analyze compare <a> <b>

ALFRESCO POST-RUN (§L)
[ ] §L.1   conteo Alfresco coincide con tracking.db
[ ] §L.5   watchdog purga cuando supera threshold (solo si tenés Compu B)

STRESS (§M)
[ ] §M.1   1000 docs end-to-end sin estallar
[ ] §M.2   watchdog bajo presión continua (host Linux)
[ ] §M.3   disk pressure recovery
```

Si todo lo anterior verde → CMCourier está validado end-to-end contra
Alfresco staging local. Subí el reporte (`analyze batch <id> --format
json`) y lo evaluamos performance.

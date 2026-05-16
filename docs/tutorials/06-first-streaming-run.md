> [← Volver al índice](../INDEX.md) · [Tutoriales](README.md)

# 06 — Tu Primera Corrida Streaming

En este tutorial corrés `csv-trigger-pipeline run` con `mode: streaming` y la TUI activa. Vas a entender qué muestran las cinco tabs, qué número significa qué, y cómo se ve AIMD escalando workers en vivo.

Apuntamos a una corrida pequeña pero realista: 500 docs sintéticos contra un Alfresco de staging. Si no tenés Alfresco corriendo, el runbook `docs/how-to/local-staging-simulation.md` te guía a levantarlo en Docker.

---

## Pre-requisitos

- Completaste el [tutorial 00](00-getting-started.md) — venv armado, `cmcourier --help` funcionando.
- Leíste el [tutorial 01](01-the-yaml-config.md) — entendés las secciones del YAML.
- Leíste el [tutorial 03](03-execution-modes-batched-vs-streaming.md) — entendés streaming.
- Tenés un Alfresco accesible (local o staging). Las credenciales en env vars.

---

## 1. El config

Guardalo como `staging.yaml`:

```yaml
trigger:
  kind: csv
  csv_path: /tmp/synthetic/triggers.csv

indexing:
  source:
    kind: csv
    csv_path: /tmp/synthetic/rvabrep.csv
  batch_size: 50

mapping:
  csv_path: /tmp/synthetic/MapeoRVI_CM.csv

metadata:
  field_aliases: {}
  field_sources: {}
  sources: []

assembly:
  source_root: /tmp/synthetic/pool
  temp_dir: /tmp/cmcourier-tmp
  image_type_map:
    B: image/tiff
    O: application/pdf

cmis:
  base_url: http://localhost:8080/alfresco/api/-default-/public/cmis/versions/1.1/browser
  repo_id: ""
  workers: 2                                # arrancamos chico para ver AIMD escalar
  max_bandwidth_mbps: 0                     # sin tope
  auto_tune:
    enabled: true
    min_threads: 2
    max_threads: 16                         # techo bajo para que se vea
    warmup_seconds: 30                      # más corto que el default 60

tracking:
  db_path: /tmp/cmcourier-staging.sqlite

observability:
  log_dir: /tmp/cmcourier-logs
  log_format: json

processing:
  mode: streaming
  prep_workers: 4
  streaming:
    bucket_size: 50                         # chico para que se llene/vacíe visiblemente

batch_size: 500
```

Lo que estamos optimizando para el aprendizaje:

- `cmis.workers: 2` + `auto_tune.max_threads: 16` para ver el AIMD escalar desde 2 hacia 16.
- `streaming.bucket_size: 50` para ver el bucket llenarse y vaciarse en la tab `BUCKET`.
- `auto_tune.warmup_seconds: 30` para no esperar 60 segundos antes de la primera decisión.

---

## 2. Generar los datos sintéticos

```bash
mkdir -p /tmp/synthetic/pool /tmp/cmcourier-logs

cmcourier mock rvabrep --count 500 --seed 42 > /tmp/synthetic/rvabrep.csv
cmcourier mock generate --output /tmp/synthetic/pool --count 500 --seed 42
```

Luego un CSV de triggers (un subset del RVABREP es suficiente) y el mapping mínimo. El runbook de `local-staging-simulation.md` tiene los detalles si querés algo más sofisticado.

---

## 3. Pre-flight con doctor

Antes de correr, validá:

```bash
export CMIS_USERNAME=admin
export CMIS_PASSWORD=admin

cmcourier doctor --config staging.yaml --check all
```

Si todo verde, seguí. Si algo falla, leé el [tutorial 05](05-doctor-deep-dive.md) y arreglalo.

---

## 4. Disparar la pipeline

```bash
cmcourier csv-trigger-pipeline run \
  --config staging.yaml \
  --batch-id primer-streaming-run \
  --tui
```

La TUI ocupa la terminal entera. Al arrancar ves:

```
CMCourier · streaming · batch-id=primer-streaming-run
┌─[ P PREP ][ U UPLOAD ][ C CHUNKS ][ B BUCKET ][ D DETAIL ]──────────────────┐
│                                                                            │
│                          PREP tab                                          │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
[Q] quit  · refresh 250ms
```

Las cinco tabs están arriba. Cada una se abre con su tecla.

---

## 5. Navegar las tabs

### Tab `P` — PREP

Stages S0–S4. Renderer: `src/cmcourier/tui/prep_tab.py:render_prep`.

```
PREP — S0..S4
  triggers acquired : 500
  s1_indexed        : 487
  s1_filtered       : 8        (delete code)
  s1_skipped        : 5        (idempotency: already uploaded)
  s2_mapped         : 487
  s3_resolved       : 487
  s4_assembled      : 487   ← cuántos llegaron al bucket
  failed by stage   : S3=0  S4=0
```

Lo que mirás:

- **`s1_filtered` y `s1_skipped`** — antes de 062 los docs filtrados se dropeaban silenciosamente. Ahora son contadores de primera clase.
- **`s4_assembled`** — el "ritmo" de producción hacia el bucket.
- **`failed by stage`** — si algo está fallando, qué stage y cuántos.

### Tab `U` — UPLOAD

Stage S5. Renderer: `src/cmcourier/tui/upload_tab.py:render_upload`.

```
UPLOAD — S5
  s5_done           : 142
  s5_failed         : 0
  throughput        : 11.2 MB/s  (peak 14.8 MB/s)
  ETA               : 32s
  pool              : busy 8 / 16   queue 2

  LANES (heavy/light)              [disabled]
```

Lo que mirás:

- **`throughput`** — desde 069 el `_BandwidthSampler` distribuye los bytes uniformemente sobre la ventana real de transmisión, así que el número refleja throughput sostenido (no aliasing de completion).
- **`pool busy / capacity`** — `busy` es cuántos workers están subiendo ahora; `capacity` es el techo dinámico que AIMD está usando. Si AIMD está escalando, vas a ver `capacity` subir.
- **`LANES`** — si activaste `heavy_light_lanes`, sub-bloque con budget heavy/light, busy, queue depth por lane.

### Tab `C` — CHUNKS

Multi-batch overview. Renderer: `src/cmcourier/tui/chunks_tab.py:render_chunks`. En streaming ves un solo chunk sintético (el run entero):

```
CHUNKS — N=1 in flight
chunk_id   status      docs    s5_done  s5_failed  elapsed   MB/s  docs/s
─────────────────────────────────────────────────────────────────────────
primer..   UPLOAD      500     142      0          14s       11.2  10.1
TOTAL                  500     142      0                          10.1
```

En modo batched verías una fila por chunk activo (hasta 2 con N=2 overlap). En streaming es siempre uno solo.

### Tab `B` — BUCKET (streaming-only)

Renderer: `src/cmcourier/tui/bucket_tab.py:render_bucket`. **La estrella del modo streaming.**

```
BUCKET — streaming pipeline
  fill          : 38 / 50          [████████████░░░░░░]
  peak          : 50 / 50
  PREP rate     : 9.4 docs/s   (5s window)
  S5 rate       : 10.1 docs/s
  in-flight PREP: 4
  S5 workers    : 16 configured

  totals
  S5_DONE       : 142
  S5_FAILED     : 0
  S1_FILTERED   : 8
  S1_SKIPPED    : 5

  LANES (heavy/light)              [disabled]
```

Lo que mirás:

- **`fill / peak`** — el nivel actual del bucket vs el tamaño. Si está siempre cerca de `peak`, S5 es el cuello de botella (los productores tienen que esperar). Si está siempre cerca de 0, PREP es el cuello (S5 espera).
- **`PREP rate` vs `S5 rate`** — ventana deslizante de 5s. Si están parejos, está balanceado. Si PREP > S5, el bucket se llena. Si S5 > PREP, el bucket se vacía.
- **`in-flight PREP`** — cuántos productores están trabajando.

> Si tu config es batched, la tab BUCKET imprime un stub de una línea diciéndote que mires CHUNKS. No es un bug — es a propósito.

### Tab `D` — DETAIL

Drill-down doc por doc. Renderer: `src/cmcourier/tui/detail_tab.py:render_detail`. Lee on-demand del tracking DB para que la memoria del TUI quede acotada (hasta 2000 filas por chunk desde 058).

```
DETAIL — chunk: primer-streaming-run (use [ and ] to navigate)
  txn_num      file_name        status     size     reason
  ─────────────────────────────────────────────────────────────────────
  TXN0001      doc_001.tiff     S5_DONE    1.2 MB
  TXN0002      doc_002.tiff     S5_DONE    0.8 MB
  TXN0003      doc_003.tiff     S1_FILTERED         delete code DLT
  TXN0004      doc_004.pdf      S5_DONE    2.5 MB
  TXN0005      doc_005.tiff     S5_DONE    1.1 MB
  ...
```

Keybinds:

- `[` chunk anterior
- `]` chunk siguiente
- `D` para abrir esta tab desde otra

En streaming hay un solo chunk, así que `[` y `]` no hacen mucho.

---

## 6. Qué pasa cuando AIMD escala

Esto es lo que vas a ver en vivo:

1. **Segundo 0–30**: warmup. `cmis.workers=2`, capacity=2, busy oscila entre 0 y 2. AIMD no toca nada (`warmup_seconds=30`).
2. **Segundo 30**: primera decisión AIMD. Si `p95 < 0.8 × target_p95_ms` (default `target=5000ms`, así que < 4000ms), crecimiento. `capacity = ceil(2 × growth_factor) = ceil(2 × 1.25) = 3`. En la tab UPLOAD ves `busy X / 3`.
3. **Segundo 60**: si p95 sigue bien, `capacity = ceil(3 × 1.25) = 4`. Y así.
4. **Eventualmente**: `capacity` llega a `max_threads: 16`. Ahí se queda.
5. **Si en algún momento un outlier de p95 supera `1.5 × target = 7500ms`**: halve suave. `capacity = ceil(current × 0.75)`. Por ejemplo, de 16 baja a 12.

En la práctica, con un Alfresco local y archivos chicos, vas a ver `capacity` subir bastante rápido. Con un CMIS lento o archivos heavy, vas a ver la curva moviéndose más despacio. Los detalles del algoritmo están en la sección 10 del [dossier](../_internal/dossier.md).

> Pre-068 el crecimiento era lineal +1 por tick — tardaba 44 ticks llegar a 50. Pre-061 un solo outlier podía halvear el pool a /2. Los defaults actuales (068 + 061) corrigen las dos cosas.

---

## 7. Qué pasa cuando algo falla

Si hay errores S5, los vas a ver:

- En la tab UPLOAD: `s5_failed` sube.
- En la tab BUCKET: `S5_FAILED` sube.
- En la tab DETAIL: el doc afectado tiene `status: S5_FAILED` y la columna `reason` te da el mensaje de error.

CMCourier usa retries con backoff exponencial (`retry_max_attempts: 3`, `retry_base_delay_s: 2.0`). Solo después de agotar los retries marca `S5_FAILED`. Errores 4xx (CMISClientError) no se retentan; 5xx + errores de socket sí (CMISServerError).

El circuit breaker de `CmisUploader` corta uploads en cadena si ve patrón consistente de 5xx — eso protege al CMIS de avalancha.

---

## 8. Cerrar el run

Al final del run:

- Si todos los docs son `S5_DONE` (o terminales `S1_SKIPPED` / `S1_FILTERED`): exit code 0.
- Si hay `S{N}_FAILED`: exit code 1.

La TUI sigue mostrando los números finales hasta que apretás `Q`. El `batch_summary` JSON se vuelca a `logs/app-{date}.jsonl` con los percentiles por stage. El Top-N de slow ops va a `slow-ops-{date}.jsonl`.

Para post-mortem:

```bash
cmcourier batch show --config staging.yaml --batch-id primer-streaming-run
cmcourier analyze batch --config staging.yaml --batch-id primer-streaming-run
```

El `analyze batch` te da el breakdown por stage con clasificador de bottleneck — leelo siempre después de un run, así te quedás con la intuición de "esta corrida fue `upload-bound`" o "esta fue `assembly-bound`".

---

## Checklist final

Después de tu primera corrida streaming deberías poder:

- [ ] Navegar las cinco tabs con `P U C B D`
- [ ] Identificar si el bottleneck está en PREP o en UPLOAD mirando el `fill` del bucket
- [ ] Ver el `capacity` del pool S5 escalando si AIMD está activo
- [ ] Distinguir entre `S5_FAILED`, `S1_FILTERED` y `S1_SKIPPED` en DETAIL
- [ ] Saber dónde van los logs y qué te dice `analyze batch`

Si te quedó algo confuso, releé la sección y volvé a correr — los datos sintéticos son baratos y deterministas (mismo `--seed`, mismo resultado).

---

## Siguientes pasos

- [07 — Debugging de un batch fallido](07-debugging-a-failed-batch.md): cuando algo falla, qué hacer
- [`docs/how-to/local-staging-simulation.md`](../how-to/local-staging-simulation.md): staging Docker completo
- [`docs/how-to/heavy-light-lanes.md`](../how-to/heavy-light-lanes.md): activar lanes y ver el sub-bloque LANES
- [`docs/how-to/log-analysis.md`](../how-to/log-analysis.md): integrar `analyze` con CI

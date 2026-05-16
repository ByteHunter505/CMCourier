# How to: analizar los logs de un batch offline (`cmcourier analyze`)

> [← Volver al índice](../INDEX.md) · [How-to](README.md)

> Disponible desde el cambio **027** (2026-05-11). Lee los cinco niveles
> de observabilidad y produce un reporte por-batch, una comparación
> de a pares, o una serie de tendencias.

---

## TL;DR

```bash
# Reporte completo para un batch
cmcourier analyze batch <batch_id> --config prod.yaml

# Delta lado-a-lado
cmcourier analyze compare <batch_a> <batch_b> --config prod.yaml

# Tendencia de throughput + p95 S5 de los últimos 10 batches
cmcourier analyze trends --config prod.yaml --last 10

# Salida JSON en lugar de la legible para humanos
cmcourier analyze batch <batch_id> --config prod.yaml --format json
```

Si no querés apuntar a un YAML, cambiá `--config` por
`--log-dir <path>` y el analizador lee archivos JSONL crudos sin
consultar la config del pipeline. Dos consecuencias:

1. El clasificador pierde el techo `cmis_max_bandwidth_mbps`, así que la
   *razón* `network-bound` de métricas de sistema no puede dispararse —
   pero un bottleneck de upload todavía aparece como `upload-bound` vía
   el breakdown de stage.
2. El clasificador pierde `pool_capacity`, así que la *razón*
   `worker-saturated` nunca dispara. Ninguna pérdida afecta el
   veredicto primario, dirigido por stage.

---

## Qué se lee

El analizador escanea el `log_dir` configurado y tira de cuatro
familias de archivos:

| Patrón de archivo | Nivel | Filtro |
|---|---|---|
| `metrics-{date}.jsonl` | 2 — pipeline | records donde `batch_id` matchea |
| `network-{date}.jsonl` | 3 — network | records dentro de la **ventana temporal** del batch (estos records no llevan `batch_id`) |
| `system-{date}.jsonl` | 5 — system (026) | records dentro de la **ventana temporal** del batch (estos records no llevan `batch_id`) |
| `slow-ops-{batch_id}.jsonl` | 4 — slow ops | archivo-por-batch, elegido por nombre |

Los records `network-*` y `system-*` **no llevan `batch_id`** — solo
un timestamp. El reader deriva la ventana del batch
`[ts − elapsed_s, ts]` del record `batch_summary` (que *sí* es
batch-tagged) y mantiene records cuyo timestamp (`ts` para network,
`ts_iso` para system) cae adentro. Para una corrida single-batch esto
es exacto; para corridas **superpuestas (N=2)** las ventanas de los dos
batches se superponen y un record en el overlap puede caer en
cualquiera de los dos — una limitación conocida (el breakdown por
stage abajo es batch-tagged y exacto, y es la señal primaria). Cuando
un batch no tiene record `batch_summary`, la ventana no puede derivarse
y los niveles network/system vuelven vacíos en lugar de adivinar.

Corridas cross-medianoche se manejan por el glob — tanto
`metrics-2026-05-10.jsonl` como `metrics-2026-05-11.jsonl`
son escaneados si el batch los cruzó.

Líneas JSONL malformadas se loguean WARNING y se saltean; el reporte
sigue produciéndose.

---

## Clasificador de bottleneck

El clasificador responde dos preguntas: *qué stage se comió el tiempo*, y
*el bottleneck está adentro del programa (nuestro para optimizar) o afuera
(el servidor CMIS + la red — solo podemos empujar más concurrencia)*.

### El breakdown por-stage es la señal PRIMARIA

El record `batch_summary` lleva un breakdown de timing por stage
(`sum_ms` = tiempo total entre cada doc en ese stage). Es batch-tagged,
siempre presente, y la señal de bottleneck más directa — así que el
clasificador lidera con ella. Cuando una stage retiene **≥ 45%** del
tiempo total de stage, esa stage **es** el bottleneck:

| Stage dominante | Clase | Locus |
|---|---|---|
| `S5` (upload) | `upload-bound` | **AFUERA** del programa — el servidor CMIS + la red. El cliente solo puede empujar más concurrencia. |
| `S4` (assembly) | `assembly-bound` | ADENTRO — CPU del ensamblado PDF/TIFF. Nuestro. |
| `S3` (metadata) | `metadata-bound` | ADENTRO — resolución de metadatos. |
| `S2` (mapping) | `mapping-bound` | ADENTRO. |
| `S1` (indexing) | `indexing-bound` | ADENTRO. |
| `S0` (trigger) | `trigger-bound` | ADENTRO. |

`confidence` es el share de la stage dominante sobre el tiempo total
de stage, y la línea `reasons` nombra la stage, su share, su p50/p95, y
si está **ADENTRO** o **AFUERA** del programa — así el operador recibe
la respuesta a su pregunta, no solo un label.

### Las métricas de sistema REFINAN, no gatean

Cuando hay samples de sistema presentes, estas señales se agregan como
**razones corroborantes** al veredicto de stage — ya no lo gatean:

| Señal | Regla |
|---|---|
| `cpu-bound` | `process_cpu_pct > 80%` en **≥50%** de los samples |
| `memory-bound` | `ram_used / ram_total > 0.85` en **≥50%** de los samples |
| `disk-bound` | `disk_read + disk_write > 100 Mbps` **y** `cpu_pct < 50%` en **≥50%** de los samples |
| `network-bound` | `(net_in + net_out) > 80% × cmis.max_bandwidth_mbps` en **≥50%** de los samples |
| `worker-saturated` | `active_workers == pool_capacity` en **≥80%** de los samples — un **síntoma** de un downstream lento, no una causa |

Estas se vuelven la *clasificación* **solo cuando ninguna stage domina**.
En ese fallback una causa real de recurso (cpu / mem / disk / network)
siempre supera a `worker-saturated` — la saturación es un síntoma, así que
es el veredicto solo cuando es la única señal que disparó.

`under-utilized` se devuelve solo cuando **ninguna** stage domina **y**
ninguna señal de sistema dispara — una corrida genuinamente idle.

### Leyendo confidence

Para un veredicto dirigido por stage, `confidence` es la fracción de la
stage dominante sobre el tiempo total de stage — `upload-bound` en `0.93`
significa que S5 se comió el 93% del tiempo por-doc. Para un veredicto
fallback dirigido por sistema es la fracción de samples que votaron por
la clase ganadora. Cualquier cosa ≥ 0.75 es de alta señal; 0.45–0.74
es sugerente.

### Limitaciones conocidas

- **Corridas superpuestas (N=2)** — los records network/system se
  asocian por ventana temporal, y las ventanas de los dos batches se
  superponen. El breakdown por stage queda exacto (batch-tagged); las
  *razones* de system/network pueden estar levemente contaminadas.
- **Batches chicos (< 60 s)** con el intervalo default de 5 s del sampler
  producen <12 samples de sistema — las razones corroborantes pueden ser
  ruidosas. Bajá `observability.system_metrics.sample_interval_s` a 1.0
  para mayor resolución en corridas diagnósticas cortas.
- **Sampler deshabilitado** (`system_metrics.enabled: false`) → sin razones
  corroborantes, pero el veredicto dirigido por stage no se afecta.
- **Sin `cmis.max_bandwidth_mbps`** configurado → la razón de métricas de
  sistema `network-bound` se saltea, pero un bottleneck de upload
  todavía aparece como `upload-bound` vía el breakdown de stage.
- El analizador reporta **qué** está saturado, no **por qué**. Un
  veredicto `upload-bound` significa que S5 dominó — podría ser el
  servidor CMIS sobrecargado, tu NIC al tope, o contención de WAN; eso
  es para que el operador triage.

---

## Salida sample (terminal)

```
BATCH B1
============================================================
  pipeline                 csv-trigger
  total_docs               10
  elapsed_s                12.34
  throughput               0.810 docs/s

STAGES
------------------------------------------------------------
  stage    count    p50_ms    p95_ms    p99_ms
  S5          10    100.00    500.00    800.00

NETWORK
------------------------------------------------------------
  kind            count    p50_ms    p95_ms    p99_ms          bytes
  cmis_upload         1    200.00    200.00    200.00           1024

SYSTEM
------------------------------------------------------------
  samples                  1
  cpu_pct_avg/max          30.0 / 30.0
  process_cpu_avg/max      25.0 / 25.0
  ram_pct_avg/max          25.0% / 25.0%
  disk_mbps_avg/max        8.0 / 8.0
  net_mbps_avg/max         60.0 / 60.0
  worker_saturation        0.0%

TOP SLOW OPS
------------------------------------------------------------
  cmis_upload          6000 ms  txn=TXN_001  worker=w1

Bottleneck: upload-bound (confidence 1.00)
  • S5 dominates — 100% of total stage time (p50 100 ms, p95 500 ms); bottleneck is OUTSIDE the program
```

---

## Playbook de operador

**"El batch X tardó N minutos. ¿Fue CPU-bound o network-bound?"**

```bash
cmcourier analyze batch X --config prod.yaml
```

Mirá la línea `Bottleneck:` al final.

**"Corrida de tuning ayer: ¿duplicar `cmis.workers` realmente
ayudó?"**

```bash
cmcourier analyze compare yesterday-batch today-batch \
  --config prod.yaml
```

Compará `throughput_delta`, `elapsed_delta`, y los deltas de p95 por
stage. Si `S5 p95` bajó y el throughput subió, el cambio funcionó. Si
S5 p95 bajó pero el throughput quedó plano, podés haber pegado un
bottleneck distinto (leé el veredicto `Bottleneck:` del batch nuevo).

**"¿Estamos derivando con el tiempo?"**

```bash
cmcourier analyze trends --last 20 --pipeline rvabrep \
  --config prod.yaml
```

Mirá la columna throughput y la columna p95 S5 con el tiempo.

---

## Salida JSON

`--format json` emite un documento determinista, machine-readable, con
los mismos datos que el reporte de terminal. Usalo para pipear hacia
otras herramientas:

```bash
cmcourier analyze batch <id> --config prod.yaml --format json \
  | jq '.bottleneck'
```

Garantía de determinismo: JSONL de entrada idéntico → salida JSON
idéntica (claves ordenadas, sin timestamps embebidos, sin IDs random).

---

## Integración CI / PR (033)

La salida `--format json` del analizador + el output determinista lo
hacen un fit natural para un guardrail de CI: cada PR (o job
programado) corre un pequeño batch de validación, después chequea el
veredicto de bottleneck + p95 S5 contra un baseline. Si aparece una
regresión, el job de CI falla y se postea un comentario en el PR.

### Check mínimo viable

Para una herramienta de migración, `upload-bound` es el estado estable
*esperado* — S5 (el upload CMIS) dominando significa que el programa
está haciendo su trabajo y el bottleneck está AFUERA de nuestro control.
La regresión a atrapar es una stage **ADENTRO** del programa dominando
de repente (`assembly-bound`, `metadata-bound`, `mapping-bound`, …) —
eso significa que *nuestro* código se puso lento. Entonces el gate de CI
es "asseverar que el veredicto se quedó afuera del programa":

```bash
# En CI — corré una migración pequeña (el flag --total de 033 la limita):
cmcourier csv-trigger-pipeline run \
    --config staging.yaml \
    --no-tui --skip-doctor \
    --total 10 --batches-in-flight 1

# Inspeccioná el veredicto del batch más reciente:
VERDICT=$(cmcourier analyze trends --last 1 --config staging.yaml --format json \
          | jq -r '.[0].batch_id' \
          | xargs -I {} cmcourier analyze batch {} --config staging.yaml --format json \
          | jq -r '.bottleneck.classification')

# Hacé fallar el build si una stage ADENTRO del programa regresó:
case "$VERDICT" in
  "upload-bound"|"under-utilized"|"network-bound")
    echo "::notice::CI batch verdict: $VERDICT (bottleneck outside the program)"
    ;;
  *)
    echo "::error::CI batch verdict regressed to '$VERDICT' — an INSIDE-the-program stage now dominates"
    exit 1
    ;;
esac
```

### GitHub Actions

```yaml
- name: Run CMCourier validation batch
  env:
    CMIS_USERNAME: ${{ secrets.CMIS_USERNAME }}
    CMIS_PASSWORD: ${{ secrets.CMIS_PASSWORD }}
  run: |
    cmcourier csv-trigger-pipeline run \
      --config configs/staging.yaml \
      --no-tui --skip-doctor \
      --total 10 --batches-in-flight 1

- name: Analyze most recent batch
  run: |
    LAST_BATCH=$(cmcourier analyze trends --last 1 \
                  --config configs/staging.yaml --format json \
                  | jq -r '.[0].batch_id')
    cmcourier analyze batch "$LAST_BATCH" \
      --config configs/staging.yaml --format json > batch-report.json
    cat batch-report.json | jq .

- name: Upload report artifact
  uses: actions/upload-artifact@v4
  with:
    name: cmcourier-batch-report
    path: batch-report.json
```

### GitLab CI

```yaml
cmcourier-validation:
  stage: test
  script:
    - cmcourier csv-trigger-pipeline run
        --config configs/staging.yaml
        --no-tui --skip-doctor
        --total 10 --batches-in-flight 1
    - LAST_BATCH=$(cmcourier analyze trends --last 1
                    --config configs/staging.yaml --format json
                    | jq -r '.[0].batch_id')
    - cmcourier analyze batch "$LAST_BATCH"
        --config configs/staging.yaml --format json > batch-report.json
  artifacts:
    paths:
      - batch-report.json
    when: always
```

### Filtros `jq` útiles

```bash
# Throughput a través de los últimos 10 batches:
cmcourier analyze trends --last 10 --config c.yaml --format json \
  | jq '[.[].throughput_docs_per_s] | {min, max, avg: (add/length)}'

# Todos los valores de p95 S5 que cruzaron 5000 ms:
cmcourier analyze trends --last 50 --config c.yaml --format json \
  | jq '[.[] | select(.s5_p95_ms > 5000)] | length'

# Veredicto + confidence para un batch conocido:
cmcourier analyze batch "$ID" --config c.yaml --format json \
  | jq '.bottleneck | {classification, confidence}'

# Top-3 slow ops por duración:
cmcourier analyze batch "$ID" --config c.yaml --format json \
  | jq '.slow_ops | sort_by(-.duration_ms) | .[:3]'
```

### Contrato de exit code (gate de regresión)

Para uso en CI, los exit codes del analizador:

* `0` — reporte producido exitosamente (sin importar la clasificación).
* `2` — error de config / CLI (path mal, batch faltante, flag malformado).
* `3` — excepción no manejada adentro del analizador.

**La clasificación NO está en el exit code** — el analizador reporta
hechos; el job de CI decide qué cuenta como regresión. Esto mantiene
al analizador componible y deja que cada proyecto elija sus propios
thresholds. El bloque `case` en el ejemplo mínimo viable de arriba es
el patrón recomendado: parseá la salida JSON vos mismo y salí non-zero
sobre las clases que te importan.

### Limitaciones en CI

* **CMIS real no disponible**: la mayoría de los CI runners no pueden
  alcanzar al servidor CMIS del banco. Usá el pipeline `single-doc`
  contra un container CMIS-emulador, o corré solo las stages pre-S5
  y salteá S5 enteramente (un cambio futuro puede agregar
  `--skip-s5`).
* **`--total` chico oculta señales de carga**: con `--total 10`, el controller
  AIMD nunca calienta y `active_workers` queda bajo — las razones
  corroborantes `worker-saturated` / `cpu-bound` casi nunca disparan en
  CI, y eso es esperable. El veredicto dirigido por stage sigue siendo
  significativo (un batch chiquito normalmente sigue siendo `upload-bound`).
  CI atrapa regresiones de config / wiring, no problemas de carga.
* **El determinismo es per-input**: JSONL idéntico produce JSON idéntico,
  pero dos corridas de CI con timing distinto producen JSONL distinto.
  No fijes contra `reportes byte-idénticos` entre corridas — fijá contra
  campos específicos.

---

## Cross-references

- Entrada del roadmap POST-MVP: `docs/roadmap/POST-MVP.md` §3.
- Contrato del nivel 5: la spec de dominio del proyecto §17.4
  + `specs/026-system-metrics-tier5/`.
- Spec de este cambio: `specs/027-log-analyzer/`.

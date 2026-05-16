# Profilear un cuello de botella

> [← Volver al índice](../../INDEX.md) · [How-to](../README.md) · [Developer](README.md)

Cuando el pipeline va lento y el TUI no alcanza para identificar dónde se va el tiempo, abrís el cinturón de profilers. CMCourier emite tres telemetrías nativas (`batch_summary`, slow-ops aggregator, system metrics) y se lleva bien con `py-spy` y `cProfile` para deep dives.

## Cuándo aplica

- Throughput cayó respecto al baseline y los workers de S5 no parecen ser el límite.
- p95/p99 de algún stage explotó pero el promedio no — síntoma típico de cola larga.
- Sospechás GIL contention en S4 (assembly) o S5 (upload).
- El sistema está al 100% de CPU/disco/red y querés saber cuál.

## Pasos

### 1. Leé `batch_summary` en `logs/`

Al cierre de cada batch (modo `batched`) o al cierre de la corrida (modo `streaming`), `MetricsRecorder` emite una línea JSON `batch_summary` al logger `cmcourier.metrics.pipeline`. Con `observability.log_format: json` (default) la línea aparece tal cual en `logs/cmcourier-*.log`.

```bash
jq -c 'select(.kind == "batch_summary")' logs/cmcourier-*.log
```

Campos clave por stage (S0..S7):

```json
{
  "kind": "batch_summary",
  "batch_id": "...",
  "elapsed_s": 312.4,
  "throughput_docs_per_s": 14.2,
  "stages": {
    "S1": {"count": 4400, "p50_ms": 22.1, "p95_ms": 88.0, "p99_ms": 214.7, "sum_ms": 119840.0},
    "S4": {"count": 4400, "p50_ms": 412.0, "p95_ms": 1850.0, "p99_ms": 4900.0, "sum_ms": 2050400.0},
    "S5": {"count": 4400, "p50_ms": 905.0, "p95_ms": 3400.0, "p99_ms": 12300.0, "sum_ms": 4900000.0}
  }
}
```

Heurística rápida: ordená los stages por `sum_ms` descendente — el que más suma es el que más tiempo se llevó wall-clock-equivalente. Si un stage tiene `p99_ms >> p95_ms`, hay cola pesada (algunos docs son patológicos).

### 2. Slow-ops aggregator

Para cada batch que tuvo ops por encima de `observability.slow_op_threshold_ms` (default 5000), se emite `logs/slow-ops-{batch_id}.jsonl` con el top-N (`slow_op_top_n`, default 20):

```bash
jq -c '.' logs/slow-ops-<batch_id>.jsonl | head -20
```

Cada entrada lleva `kind` (ej. `cmis_request`, `as400_query`), `duration_ms`, `txn_num`, `url_prefix` / `sql_prefix`. Si las 20 ops más lentas son todas `cmis_request` con el mismo `url_prefix`, ya sabés qué fix priorizar. Si están mezcladas entre AS400 y CMIS, el cuello está en otro lado (CPU, GC, disco).

### 3. Correlacioná con métricas de sistema

Cuando `observability.system_metrics.enabled: true` (default), un thread daemon muestrea cada `sample_interval_s` (default 5 s) y escribe `logs/system-{date}.jsonl`. Tiene host-level (`cpu_pct`, `ram_used_mb`, `disk_read_mbps`, `net_out_mbps`) y process-level (`process_cpu_pct`, `process_rss_mb`, `process_threads`, `active_workers`).

```bash
# Pico de CPU del proceso vs throughput de upload
jq -c '{ts: .timestamp, cpu: .process_cpu_pct, net_out: .net_out_mbps}' logs/system-*.jsonl
```

Lecturas típicas:

- `process_cpu_pct` plano cerca de `100 × N_cores` con `net_out_mbps` bajo → CPU-bound, casi seguro en S4 (assembly de PDF).
- `process_cpu_pct` bajo con `net_out_mbps` plano cerca del límite del link → red-bound, S5 maxeando el ancho de banda.
- `ram_used_mb` creciendo monotónico → memory leak o batch sin cerrar.
- `active_workers` < `cmis.workers` durante mucho tiempo → el productor (PREP) no le da abasto al consumidor (UPLOAD).

### 4. Análisis agregado con `cmcourier analyze`

El grupo `analyze` (spec 027) compara batches y trends a partir de los JSONL de logs:

```bash
cmcourier analyze batch <batch_id>                # detalle de un batch específico
cmcourier analyze compare <batch_a> <batch_b>     # diff entre dos corridas
cmcourier analyze trends --since 7d               # tendencia de los últimos N días
```

Verificá los flags reales con `cmcourier analyze --help` — el subcomando puede tener opciones específicas según versión.

### 5. `py-spy` para sampling profiler en vivo

`py-spy` ataca un proceso en ejecución sin reiniciarlo. Ideal para cuando el lento solo se reproduce contra prod.

```bash
pip install py-spy
ps aux | grep cmcourier                           # encontrá el PID
sudo py-spy top --pid <pid>                       # top en vivo (estilo top de Unix)
sudo py-spy record -o profile.svg --pid <pid> --duration 60   # flamegraph SVG
sudo py-spy dump --pid <pid>                      # snapshot del stack de cada thread
```

El flamegraph (`profile.svg`) se abre en cualquier navegador. Buscá las "mesetas anchas" — son las funciones donde el proceso gasta más tiempo. Para muchos hilos (S5 worker pool), `--threads` ayuda a separar.

### 6. `cProfile` para batches chicos reproducibles

Cuando el lento se reproduce con un batch de < 100 docs, `cProfile` te da call-graph completo:

```bash
python -m cProfile -o pipeline.prof -m cmcourier csv-trigger-pipeline run \
    --config sample/config-staging.yaml --total 50 --no-tui

# Visualizar
pip install snakeviz
snakeviz pipeline.prof
```

`cProfile` tiene overhead alto (10–30%) — no es válido para medir wall-clock real, pero el ranking relativo de funciones es confiable.

### 7. ¿Sospecha de GIL en S4?

S4 (PDF assembly: `img2pdf` + `Pillow` + `PyPDF2`) es CPU-bound. Por default `processing.s4_use_processes: true` corre S4 en un `ProcessPoolExecutor` con `os.cpu_count()` workers (o `processing.s4_max_processes` si está seteado). Si tenés sospecha de regresión por contención de GIL:

```yaml
processing:
  s4_use_processes: true          # (default) usa ProcessPool
  s4_max_processes: 8             # override; null → os.cpu_count()
```

Comparar throughput contra `s4_use_processes: false` (corre S4 inline en el thread productor, comportamiento pre-066) te dice cuánto te está dando el ProcessPool. Si la diferencia es < 10%, S4 no es el cuello, mirá hacia S5 o S1.

## Verificación

Después de cualquier optimización, comparar dos corridas equivalentes:

```bash
cmcourier analyze compare <batch_before> <batch_after>
diff <(jq -c '.stages' logs/batch-before.json) <(jq -c '.stages' logs/batch-after.json)
```

Las regresiones de performance son test-eables — si el fix vale, escribí un test que falle sin el fix (test de throughput contra fixture sintético — `cmcourier mock generate` produce el corpus determinístico).

## Gotchas

- **Modo `batched` emite un `batch_summary` por chunk** (cada `MultiBatchOrchestrator` arma un `MetricsRecorder` por chunk). Para wall-clock total, sumá los `elapsed_s` o leé el reporte agregado de `MultiBatchRunReport`.
- **Modo `streaming` emite un único `batch_summary` al cierre** — el promedio de stages incluye toda la corrida, no por chunk.
- **El handler de slow-ops se attachea por batch y se detachea al cierre**. Si abortás un batch con SIGTERM, el flush a `slow-ops-*.jsonl` puede no ocurrir; usar `kill -USR1` o terminar con `Q` desde el TUI para flushear limpio.
- **`py-spy` necesita `sudo` en Linux** salvo que tunees `ptrace_scope`. En contenedores, el flag `--cap-add SYS_PTRACE` en `docker run` lo habilita.
- **El throughput en `batch_summary` cuenta docs procesados / `elapsed_s`** — incluye filtered/failed. Para throughput "útil" filtrá por status `S5_DONE` directamente en SQLite (`tracking.db`).
- **Usar muestras grandes**: la regla del `min_samples: 20` del AIMD (auto-tune) aplica también acá. Decisiones sobre p95 con menos de 20 muestras son ruido.

## Ver también

- [`../../reference/observability-fields.md`](../../reference/observability-fields.md) — catálogo completo de campos JSONL
- `src/cmcourier/observability/metrics.py` — `MetricsRecorder`, `SlowOpAggregator`, `BatchSummary`
- `src/cmcourier/observability/system_metrics.py` — `SystemSample`
- [`../log-analysis.md`](../log-analysis.md) — uso operativo de `cmcourier analyze`
- [`../operator/tune-aimd-for-a-slow-link.md`](../operator/tune-aimd-for-a-slow-link.md) — tuning del auto-tune cuando S5 es el cuello
- [`run-the-test-suite.md`](run-the-test-suite.md) — coverage gate y marcadores

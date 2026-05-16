# Configurar heavy/light lanes

> [← Volver al índice](../../INDEX.md) · [How-to](../README.md) · [Operador](README.md)

Cuando tu corpus mezcla docs chicos (~KB) y docs grandes (>10 MB), un único pool de uploaders deja a los chicos esperando detrás de los grandes. Heavy/Light lanes (036, 065, 070) parte el budget total en dos `ResizableSemaphore`s — HEAVY para docs ≥ `heavy_threshold_bytes`, LIGHT para el resto — y rebalancea workers entre ambos según uso.

## Cuándo usarlo

- Distribución bimodal en tamaño (mezcla chicos + grandes con gap claro).
- Te importa la latencia por documento, no solo el wall-clock total.
- Tenés al menos `heavy_lane_min_batch` (default 50) docs — debajo de eso el splitter no activa lanes.

**No** lo uses cuando:

- Los tamaños son uniformes (no hay nada que separar).
- El batch es chico (overhead de coordinación domina).
- Solo te importa throughput agregado y la cola pesada domina igual.

## Pre-requisitos

- YAML pipeline funcionando contra staging o prod.
- Datos previos de la distribución de tamaños — calibrar el threshold a ciegas es como tirar dardos.
- Idealmente, AIMD activado (`cmis.auto_tune.enabled: true`) — el LaneController consume el `total_budget` del AIMD.

## Pasos

### 1. Mirá la distribución real de tu corpus

Antes de elegir `heavy_threshold_bytes`, mirá los datos. Si ya corriste antes y tenés tracking:

```bash
sqlite3 sample/tracking.db <<SQL
SELECT
    CASE
        WHEN file_size_bytes < 1048576    THEN '< 1 MB'
        WHEN file_size_bytes < 5242880    THEN '1-5 MB'
        WHEN file_size_bytes < 10485760   THEN '5-10 MB'
        WHEN file_size_bytes < 52428800   THEN '10-50 MB'
        ELSE                                   '> 50 MB'
    END AS bucket,
    COUNT(*) AS docs,
    SUM(file_size_bytes) / 1048576 AS total_mb
  FROM migration_log
 WHERE status = 'S5_DONE'
 GROUP BY 1
 ORDER BY MIN(file_size_bytes);
SQL
```

Buscá el "valle" — el rango con pocos docs entre la cola de chicos y la de grandes. Ese valle es tu threshold.

### 2. Activá lanes en el YAML

```yaml
processing:
  heavy_light_lanes:
    enabled: true
    heavy_threshold_bytes: 10485760   # 10 MB default — calibrá según paso 1
    heavy_lane_min_batch: 50          # default — debajo no activa
    heavy_initial_ratio: 0.2          # 20% del budget al lane HEAVY al arrancar
    rebalance_interval_s: 10.0        # daemon corre cada 10s
    idle_threshold_s: 15.0            # un lane idle >15s cede 1 worker
```

Defaults sanos. Ajustes típicos:

- `heavy_threshold_bytes`: subilo si tu valle está más arriba (p.ej. `52428800` = 50 MB para corpus dominantemente grande).
- `heavy_initial_ratio`: subilo a `0.3` o `0.4` si vés en el TUI que arrancás con HEAVY siempre saturado.
- `idle_threshold_s`: bajalo (~5 s) si querés rebalanceo más reactivo; subilo (~30 s) si vés workers oscilando demasiado.

### 3. Asegurate que el pool total tenga sentido

Ambos lanes siempre tienen ≥ 1 worker, y comparten el `total_budget` que viene de `cmis.workers` (o del AIMD si está activo). Si tenés `cmis.workers: 4` y querés lanes, considerá subirlo a `cmis.workers: 8` o más — sino partís un budget chico que no rinde.

```yaml
cmis:
  workers: 12                # budget total para HEAVY+LIGHT combinado
  auto_tune:
    enabled: true            # opcional pero recomendado
    min_threads: 4
    max_threads: 40
```

### 4. Corré la pipeline

```bash
cmcourier rvabrep-pipeline run \
    --config sample/config.yaml \
    --batch-id bimodal-test-001
```

### 5. Leé las lanes en el TUI

#### Tab UPLOAD (`U`)

Cuando lanes están activos, la sección WORKERS pasa de single-pool a dual-panel:

```
 WORKERS (heavy/light · total budget 12)
  HEAVY  capacity   4   in-use   3   idle   1   queue   18
         done    47   failed    0
  LIGHT  capacity   8   in-use   6   idle   2   queue    9
         done   312   failed    1
```

- `total budget` = `cmis.workers` actual (puede haberlo movido el AIMD).
- `capacity` por lane = workers asignados ahora.
- `queue` = docs esperando upload en ese lane.

#### Tab BUCKET (`B`, modo streaming)

En streaming, el bloque LANES se renderiza debajo del de WORKERS:

```
LANES (heavy/light, 065)
────────────────────────
  heavy  budget 4    busy 3    queue 18
  light  budget 8    busy 6    queue 9
  total budget 12
```

### 6. Calibrá iterativamente

Fingerprint de lanes mal calibradas:

- HEAVY queue siempre grande, LIGHT queue siempre 0 + workers idle → threshold demasiado bajo (muchos docs caen como HEAVY). Subilo.
- LIGHT queue grande, HEAVY queue 0 + workers idle → threshold demasiado alto. Bajalo.
- Ambas queues fluyendo, rebalanceos ocasionales → calibración sana.

## Verificación

```bash
# El batch terminó sin un sesgo gigante de failed en un solo lane
cmcourier batch show bimodal-test-001 --config sample/config.yaml

# Distribución final por tamaño vs status
sqlite3 sample/tracking.db <<SQL
SELECT
    CASE WHEN file_size_bytes >= 10485760 THEN 'HEAVY' ELSE 'LIGHT' END AS lane,
    status,
    COUNT(*) AS n
  FROM migration_log
 WHERE batch_id='bimodal-test-001'
 GROUP BY 1, 2;
SQL
```

Esperás tasas de fallo similares en ambos lanes. Si HEAVY tiene tasa de fallo notablemente mayor, hay un problema upstream con docs grandes (probablemente S5 timeouts — ajustá `cmis.timeout_seconds` o tuneá AIMD).

## Si algo sale mal

| Síntoma | Causa | Acción |
|---------|-------|--------|
| `enabled: true` pero el TUI no muestra LANES | Batch debajo de `heavy_lane_min_batch` | Es esperable — splitter cae a single-lane silenciosamente |
| Un lane siempre vacío | Threshold muy lejos del valle real | Re-mirá la distribución, ajustá `heavy_threshold_bytes` |
| Rebalanceos ruidosos (workers oscilando) | `idle_threshold_s` muy bajo | Subilo a 30 s |
| `total budget` no se mueve aunque AIMD esté ON | Activá `cmis.auto_tune.enabled: true` y revisá el panel auto-tune del TUI |

## Ver también

- [`tune-aimd-for-a-slow-link.md`](tune-aimd-for-a-slow-link.md) — el AIMD gobierna el `total_budget` que reparten los lanes
- [`../heavy-light-lanes.md`](../heavy-light-lanes.md) — diseño y tradeoffs (036)
- [`interpret-the-tui-tabs.md`](interpret-the-tui-tabs.md) — leer los paneles WORKERS y LANES

# Correr una migración desde CSV

> [← Volver al índice](../../INDEX.md) · [How-to](../README.md) · [Operador](README.md)

La receta canónica: tenés un CSV con la lista de triggers (ShortName, CIF, SystemID), un YAML de config válido y querés disparar la migración end-to-end con un `batch-id` nombrado.

## Cuándo usarlo

- Es tu corrida de producción típica con triggers explícitos.
- Necesitás un `batch-id` deterministico para trazabilidad posterior (`batch show`, `batch export-report`).
- Querés ver el progreso en vivo en el TUI.

## Pre-requisitos

- Python 3.11+ y CMCourier instalado (`uv pip install -e .` o el venv equivalente).
- YAML de pipeline con `trigger.kind: csv` y `trigger.csv_path` apuntando a tu CSV de triggers.
- Credenciales CMIS exportadas en el ambiente:
  ```bash
  export CMIS_USERNAME="tu-usuario"
  export CMIS_PASSWORD="tu-password"
  ```
  (Si tu config usa `indexing.source.kind: as400`, agregá `AS400_USERNAME` y `AS400_PASSWORD`.)
- `cmcourier doctor` pasando en verde — no te saltees este paso:
  ```bash
  cmcourier doctor --config sample/config.yaml
  ```

## Pasos

### 1. Verificá la config con doctor

```bash
cmcourier doctor --config sample/config.yaml
```

Esperás exit code `0` y todos los checks en `PASS`. Si alguno falla, resolvelo antes de seguir — correr la pipeline con doctor rojo te garantiza ruido en S5.

### 2. Disparar la corrida

```bash
cmcourier csv-trigger-pipeline run \
    --config sample/config.yaml \
    --batch-id mi-batch-001
```

Defaults útiles que aplican silenciosamente:

- `--from-stage 1` (arranca en S0/S1).
- `--tui` (TUI activo). Para correrla en background o en CI, agregá `--no-tui`.
- `--batches-in-flight 2` (overlap N=2 — el chunk K+1 prepara mientras el K sube).
- `--log-level INFO`.

### 3. Mirá el progreso en el TUI

Tabs:

- `P` PREP — S0–S4: triggers adquiridos, docs indexados, mapeados, metadata resuelta, PDFs ensamblados.
- `U` UPLOAD — S5: docs subidos, throughput MB/s, p95, ETA.
- `C` CHUNKS — vista multi-batch (con `batches_in_flight=2` vas a ver dos chunks intercalándose).
- `Q` quit.

Ver [`interpret-the-tui-tabs.md`](interpret-the-tui-tabs.md) si necesitás traducir lo que ves.

### 4. Override de la lista de triggers (opcional)

Si querés probar con un subset sin tocar el YAML:

```bash
cmcourier csv-trigger-pipeline run \
    --config sample/config.yaml \
    --batch-id smoke-100 \
    --triggers /tmp/triggers-subset.csv \
    --total 100
```

`--total 100` corta después de 100 triggers (smoke / dry run).

## Verificación

### Exit code

```bash
echo $?
```

| Code | Significado |
|------|-------------|
| `0` | Corrida exitosa, todo en `S5_DONE` (o `S1_SKIPPED` por idempotency) |
| `1` | Corrió pero terminó con `*_FAILED` en algún stage |
| `2` | Error de config — el YAML no carga, alguna sección rota |
| `3` | Excepción no manejada — bug, abrí issue con el `logs/` adjunto |

### Estado del batch

```bash
cmcourier batch show mi-batch-001 --config sample/config.yaml
```

Te muestra contadores por stage (DONE / FAILED / PENDING) y la lista de fallados con `error_message`. Si todo salió bien, vas a ver todos los `S0_DONE` … `S5_DONE` iguales al total.

### Lista global de batches

```bash
cmcourier batch list --config sample/config.yaml
```

### Tracking DB directo (cuando dudás)

```bash
sqlite3 sample/tracking.db \
    "SELECT status, COUNT(*) FROM migration_log WHERE batch_id='mi-batch-001' GROUP BY status;"
```

## Si algo sale mal

| Síntoma | Acción |
|---------|--------|
| Exit code 1 + FAILEDs | Ver [`retry-only-failed-records.md`](retry-only-failed-records.md) |
| Exit code 2 | Re-leé el error de `doctor` — config inválida o credenciales mal |
| `CMISServerError` en cascada | Backend caído. Ver [`tune-aimd-for-a-slow-link.md`](tune-aimd-for-a-slow-link.md) para tolerar mejor latencia |
| Memoria sube descontrolada | Pasá a modo streaming — ver [`run-a-streaming-load-against-staging.md`](run-a-streaming-load-against-staging.md) |
| SQLite "database is locked" o "disk image is malformed" | Ver [`recover-from-a-corrupted-tracking-db.md`](recover-from-a-corrupted-tracking-db.md) |

## Ver también

- [`retry-only-failed-records.md`](retry-only-failed-records.md) — reintentar solo los FAILED
- [`interpret-the-tui-tabs.md`](interpret-the-tui-tabs.md) — qué significa cada número del TUI
- [`../local-staging-simulation.md`](../local-staging-simulation.md) — runbook para staging local

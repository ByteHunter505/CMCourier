# Correr una carga en modo streaming contra staging

> [← Volver al índice](../../INDEX.md) · [How-to](../README.md) · [Operador](README.md)

Cargar miles de documentos sin que el RSS del proceso explote. El modo `streaming` (063) usa producer-consumer con un `bucket` acotado entre PREP y UPLOAD — el pico de memoria colapsa a ~`bucket_size` docs en vez de a un chunk entero.

## Cuándo usarlo

- Vas a procesar >5k triggers en una sola corrida.
- Tu host tiene memoria contenida y el batched mode te hace OOM.
- Querés throughput sostenido sin las pausas de cierre/apertura de chunks que tiene el modo batched.

**No** lo uses cuando:

- Necesitás resumir desde un `from-stage > 1` — el `StreamingOrchestrator` rechaza eso explícitamente.
- Tu corrida es chica (<500 docs) — el overhead de coordinación no se justifica.

## Pre-requisitos

- YAML configurado como en [`run-a-migration-from-csv.md`](run-a-migration-from-csv.md).
- Una sección `processing` ajustada:

  ```yaml
  processing:
    mode: streaming
    streaming:
      bucket_size: 200    # docs en vuelo entre PREP y UPLOAD
    prep_workers: 4       # paralelismo S2/S3/S4 (S4 usa procesos por default)
  ```

  Defaults relevantes:
  - `bucket_size = 100`. Subilo si vés `prep` esperando al `bucket` lleno; bajalo si tu RAM aprieta.
  - `prep_workers = 1`. Pasalo a `4–8` si la PREP es CPU-bound (S4 ensamblando PDFs grandes).
  - `s4_use_processes = true` (066). Solo desactivalo si tu host no tolera procesos hijo.

## Pasos

### 1. Verificá la config

```bash
cmcourier doctor --config sample/config-staging-rvabrep-streaming.yaml
```

### 2. Corré la pipeline con el TUI

```bash
cmcourier rvabrep-pipeline run \
    --config sample/config-staging-rvabrep-streaming.yaml \
    --batch-id streaming-$(date +%Y%m%d-%H%M%S) \
    --tui
```

### 3. Abrí el tab BUCKET en vivo

Tecla `B` en el TUI. Vas a ver:

- `level X / Y` — fill del bucket. Si está pegado al cap, S5 va detrás (uploader es el bottleneck). Si está vacío, PREP no llega.
- `peak` — máximo histórico del bucket.
- `PREP docs/s` vs `S5 docs/s` — ventana deslizante de 5s. Si PREP > S5 sostenido, el bucket se llena y PREP queda bloqueado (back-pressure correcto).
- `PREP in-flight / configured` — workers PREP ocupados sobre el total.

Tecla `U` para ver el upload (throughput MB/s, p95, AIMD si está activo).

### 4. Benchmark formal (opcional)

Si querés números reproducibles, hay un script de benchmark contra `/tmp/mockfiles-mixed`:

```bash
scripts/staging/throughput-bench.sh 1000 \
    sample/config-staging-rvabrep-streaming.yaml
```

- Primer arg: `TOTAL` de docs.
- Segundo arg: config (default `sample/config-staging-rvabrep-streaming.yaml`).

Reporta `total elapsed`, bytes acumulados y throughput promedio al final. El real-time vive en el TUI — abrí `b` (BUCKET) y `u` (UPLOAD).

Si la pipeline falla porque falta el árbol de archivos mock, el script te apunta a `cmcourier mock generate` antes de seguir.

## Verificación

```bash
# Exit code
echo $?

# Estado final del batch
cmcourier batch show "$BATCH_ID" --config sample/config-staging-rvabrep-streaming.yaml

# Pico de memoria — lo medís externo, p.ej.:
#   /usr/bin/time -v cmcourier rvabrep-pipeline run ...
# y mirá "Maximum resident set size"
```

Un fingerprint sano de streaming bien configurado:

- Pico de RSS estable, no creciente.
- Bucket oscilando entre 30% y 90% del cap (señal de equilibrio PREP/S5).
- `S5_DONE` creciendo monotónicamente.

## Si algo sale mal

| Síntoma | Causa probable | Fix |
|---------|----------------|-----|
| `ValueError: streaming mode rejects from_stage>1` | Quisiste resumir | Streaming no resume. Pasá a `mode: batched` o arrancá de cero |
| Bucket clavado en `level == cap` | S5 no da abasto | Subí `cmis.workers` o activá AIMD (`auto_tune.enabled: true`) |
| Bucket clavado en `level == 0` | PREP no llega | Subí `prep_workers`, revisá S4 (PDF assembly), o el origen RVABREP |
| RSS sigue creciendo | `bucket_size` muy alto, o leak en S4 | Bajá `bucket_size`, revisá `s4_use_processes` |

## Ver también

- [`tune-aimd-for-a-slow-link.md`](tune-aimd-for-a-slow-link.md) — ajustar el AIMD si tu link no banca el ritmo de subida
- [`configure-heavy-light-lanes.md`](configure-heavy-light-lanes.md) — si tu corpus es bimodal en tamaño
- [`interpret-the-tui-tabs.md`](interpret-the-tui-tabs.md) — leer las tabs BUCKET y UPLOAD
- [`../local-staging-simulation.md`](../local-staging-simulation.md) — montar staging local con Alfresco

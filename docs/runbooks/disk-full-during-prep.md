> [← Volver al índice](../INDEX.md) · [Runbooks](README.md)

# Runbook: Disco lleno durante prep (S4)

> **Severidad**: P1 · **Tiempo estimado**: 15 min · **Última revisión**: 2026-05-15

## Síntoma

`OSError: [Errno 28] No space left on device` aparece durante S4 (assembly). Síntomas asociados:

- TUI tab `PREP` muestra `failed` subiendo en la fila S4.
- En paralelo, el tracking SQLite puede tirar `sqlite3.OperationalError: database is locked` o `disk I/O error` — el WAL no puede crecer porque no hay espacio.
- Logs estructurados también empiezan a fallar: `logs/pipeline-*.jsonl` se trunca a media línea o deja de escribir.
- Si tenés `s4_use_processes: true` (default en 066), los worker processes mueren con `BrokenProcessPool` y el orchestrator se desmadra.

## Diagnóstico rápido

```bash
# 1. ¿Qué partition está llena?
df -h

# 2. ¿Dónde se fue el espacio? (los 3 sospechosos habituales)
du -sh logs/                                             # observability
du -sh "$(rg 'temp_dir' sample/config.yaml | awk '{print $2}')"  # assembly.temp_dir
du -sh "$(dirname "$(rg 'db_path' sample/config.yaml | awk '{print $2}')")"  # tracking DB + WAL

# 3. ¿Cuánto pesa el WAL?
ls -lh sample/*.db-wal 2>/dev/null
# Un WAL > 1 GB suele indicar que el writer thread se trabó hace rato.

# 4. ¿Hay corrida viva?
pgrep -af cmcourier
```

## Mitigación inmediata

1. **`Ctrl+C` en la corrida activa**. Esperá el graceful shutdown. Si el writer thread no puede flushear porque el disco está al 100%, va a colgarse — dale 30 s y si no responde, `kill <PID>` (sin `-9`).
2. **Liberá espacio AHORA, antes de tocar la pipeline**. Tres targets seguros para borrar sin perder estado:
   ```bash
   # Logs viejos (más de N días)
   find logs/ -name "*.jsonl" -mtime +7 -delete

   # Temp dir de assembly (se regenera; nunca debería tener nada de la corrida cerrada)
   rm -rf "$(rg 'temp_dir' sample/config.yaml | awk '{print $2}')"/*

   # Mock staging si lo tenés
   rm -rf sample/staging_tmp/*
   ```
3. **NO borres** la tracking DB ni sus `.db-wal` / `.db-shm` — tenés un runbook aparte para eso si está corrupta.
4. **Confirmá con `df -h` que recuperaste al menos 1 GB libre** antes de continuar. Si no llegás a eso, tenés que mover archivos a otro filesystem.

## Resolución

El objetivo es que **no vuelva a pasar**. Tres palancas, ordenadas por costo:

### 1. Rotación y retención de logs (la más barata)

Si los logs ocuparon la mayor parte del disco, ajustá `observability` en tu YAML:

```yaml
observability:
  rotation_mb: 100        # rota cada 100 MB (default; bajalo si tu disco es chico)
  retention_days: 7       # default 30; 7 alcanza para post-mortems típicos
```

`rotation_mb` corta archivos grandes, `retention_days` los borra cuando vencen. Defaults son `100` y `30`; en hosts chicos `50` / `7` es razonable.

### 2. Mover `assembly.temp_dir` a otra partition

Si el archivo más pesado fue el temp dir (TIFFs intermedios + PDFs ensamblados antes del upload), apuntalo a un filesystem más grande:

```yaml
assembly:
  temp_dir: "/mnt/scratch/cmcourier-tmp"
```

El temp dir se crea en runtime, no necesita existir de antemano. Importante: el filesystem destino tiene que tener al menos `2 × (max_doc_size)` × `prep_workers` libre — si bajás workers, bajás el high-watermark.

### 3. Mover tracking DB a otra partition

Si el WAL infló el disco principal, mové `tracking.db_path` a un volume con más holgura. Esto requiere parar la pipeline, copiar la DB con `sqlite3 .backup` (NO `cp` directo, el WAL puede estar caliente), actualizar el YAML, y reanudar.

```yaml
tracking:
  db_path: "/mnt/data/cmcourier/tracking.db"
```

### 4. Subir capacidad del disco

Si las tres palancas anteriores no alcanzan, hablá con infra. Plot twist: a veces el disco "lleno" es realmente un mount point chico. Validá con `lsblk` antes de pedir más almacenamiento.

## Verificación

```bash
# 1. Espacio libre razonable (>= 20% holgura)
df -h

# 2. La pipeline arranca sin tirar errno 28
cmcourier doctor --config sample/config.yaml --check connections
# Mirá log_dir_writable y tracking_openable — ambos PASS.

# 3. Reanudá el batch interrumpido
cmcourier csv-trigger-pipeline run \
    --config sample/config.yaml \
    --batch-id <batch-id> \
    --resume

# 4. Después de ~5 minutos de corrida, re-chequeá df
df -h
# Si el % usado vuelve a trepar rápido, una de las palancas no se aplicó bien.
```

## Post-mortem

- Documentá qué directorio fue el culpable mayoritario y cuántos GB ocupaba al pico.
- Si fue el WAL, indagá por qué el writer thread no flusheaba (probablemente había contención de reader simultáneo — ver `tracking-db-locked.md`).
- Si fue el temp dir, calculá el high-watermark: `max_doc_size × prep_workers × batches_in_flight`. Documentalo en `reference/` como el sizing recomendado.
- Si fue logs y tu `log_format: "json"` infla mucho, considerá `log_format: "text"` para hosts chicos (sale legible al `tail`, no pierde info esencial).
- Agendá una alerta en el host: warning a 80% disco usado, page a 90%.

## Ver también

- [`tracking-db-locked.md`](tracking-db-locked.md) — si la DB quedó lockeada después del disk full.
- [`how-to/operator/wipe-staging-state.md`](../how-to/operator/wipe-staging-state.md) — receta para borrar staging state limpio.
- [`reference/`](../reference/) — schema completo de `observability` y `assembly`.

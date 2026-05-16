# Recuperarte de un tracking DB corrupto

> [← Volver al índice](../../INDEX.md) · [How-to](../README.md) · [Operador](README.md)

El SQLite de tracking (`tracking.db_path`) corre en WAL con `synchronous=OFF` — bueno para throughput, pero si el host se cuelga a media transacción o se llena el disco, el archivo puede quedar inconsistente. Esta receta es para esos casos.

## Cuándo usarlo

- Recibís `sqlite3.DatabaseError: database disk image is malformed`.
- `cmcourier batch show` colapsa o devuelve filas con valores raros.
- El proceso se interrumpió (kill -9, OOM killer, corte de energía) durante una corrida.
- Disco se llenó durante la migración y dejó el WAL roto.

## Pre-requisitos

- `sqlite3` CLI instalado (`apt install sqlite3` o equivalente).
- Acceso lectura/escritura al directorio que contiene `tracking.db_path`.
- **PARÁ LA CORRIDA primero** — no hagas nada con un proceso CMCourier vivo apuntando al mismo archivo.

## Pasos

### 1. Detené cualquier corrida activa

```bash
# Buscá el PID
pgrep -f cmcourier

# Terminalo de manera ordenada (SIGTERM primero)
kill <PID>

# Si no responde en ~10s, último recurso
kill -9 <PID>
```

### 2. Hacé backup del estado actual

**Antes de tocar nada.** Backup atómico vía SQLite — preserva WAL/SHM como una snapshot consistente:

```bash
sqlite3 sample/tracking.db ".backup sample/tracking-backup-$(date +%Y%m%d-%H%M%S).db"
```

Si ese comando también falla (DB irrecuperablemente rota), copiá los 3 archivos crudos:

```bash
cp sample/tracking.db     sample/tracking.db.bak
cp sample/tracking.db-wal sample/tracking.db-wal.bak 2>/dev/null || true
cp sample/tracking.db-shm sample/tracking.db-shm.bak 2>/dev/null || true
```

### 3. Diagnosticá la integridad

```bash
sqlite3 sample/tracking.db "PRAGMA integrity_check;"
```

Tres outcomes:

| Output | Diagnóstico | Acción |
|--------|-------------|--------|
| `ok` | DB sana | El problema es otro (lock, permisos). No sigas con esta receta |
| Lista corta de errores | Corrupción acotada | Probá `VACUUM` (paso 4) |
| `database disk image is malformed` | Corrupción severa | Saltá al paso 5 (restore o wipe) |

### 4. Intento de reparación con VACUUM

Si `integrity_check` devolvió errores pero la DB todavía se abre:

```bash
sqlite3 sample/tracking.db "VACUUM INTO 'sample/tracking-vacuumed.db';"
sqlite3 sample/tracking-vacuumed.db "PRAGMA integrity_check;"
```

Si esta nueva DB pasa `integrity_check`, reemplazala:

```bash
mv sample/tracking.db sample/tracking-broken.db
mv sample/tracking-vacuumed.db sample/tracking.db
rm -f sample/tracking.db-wal sample/tracking.db-shm
```

### 5. Si VACUUM no salva: restore desde backup

Si tenés un backup previo (de antes de la corrida problemática):

```bash
rm -f sample/tracking.db sample/tracking.db-wal sample/tracking.db-shm
cp sample/tracking-backup-YYYYMMDD-HHMMSS.db sample/tracking.db
```

Ojo: vas a re-procesar todo lo que migró **después** del momento del backup. La idempotency cross-batch (vía `S1_SKIPPED`) protege contra duplicar uploads si el txn ya tiene `S5_DONE` registrado en la DB de backup — pero si esos docs ya están en CM y NO están en tu backup, se re-suben (Alfresco rechaza por nombre duplicado, CM Real puede aceptar — depende del backend).

### 6. Alternativa de último recurso: empezar de cero

Si no tenés backup utilizable, podés borrar la DB y dejar que la idempotency rehidrate el estado vía `is_uploaded()`:

```bash
rm -f sample/tracking.db sample/tracking.db-wal sample/tracking.db-shm
cmcourier csv-trigger-pipeline run \
    --config sample/config.yaml \
    --batch-id recovery-$(date +%Y%m%d)
```

**Tradeoff explícito**: la pipeline va a re-pedir RVABREP y CSV/AS400 para cada trigger, va a re-evaluar mapping/metadata, y SOLO va a saltearse el upload en S5 (cuando el adapter de tracking AS400 sync esté activado y reporte que el `txn_num` ya existe) o por `S1_SKIPPED` si activaste tracking de uploads previos. Si **no** tenés sync AS400 ni copia previa del estado: estás aceptando re-subir todo. Hacelo con los ojos abiertos.

## Verificación

```bash
# Integrity pasa
sqlite3 sample/tracking.db "PRAGMA integrity_check;"   # → ok

# Se abre desde CMCourier
cmcourier batch list --config sample/config.yaml

# Conteos coherentes
sqlite3 sample/tracking.db "SELECT status, COUNT(*) FROM migration_log GROUP BY status;"
```

## Si algo sale mal

- **`Error: database is locked`**: hay otro proceso pegado al archivo. `lsof sample/tracking.db` para encontrarlo.
- **Restore "exitoso" pero los contadores se ven mal**: backup era de un punto incoherente. Volvé al paso 3 con el backup como fuente y diagnosticá.
- **No tenés backup ni sync AS400**: documentá el corpus ya migrado antes de borrar (export-report de cada batch viejo a CSV). Después decidí si re-subís todo o filtrás manualmente.

## Ver también

- [`wipe-staging-state.md`](wipe-staging-state.md) — wipe completo (no recovery, reset total para smoke)
- [`retry-only-failed-records.md`](retry-only-failed-records.md) — si la DB está sana pero hay FAILEDs
- [`../as400-sync.md`](../as400-sync.md) — sync NIARVILOG para tracking distribuido (034)

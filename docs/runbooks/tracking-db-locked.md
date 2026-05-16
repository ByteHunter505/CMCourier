> [← Volver al índice](../INDEX.md) · [Runbooks](README.md)

# Runbook: Tracking DB lockeada

> **Severidad**: P2 · **Tiempo estimado**: 10 min · **Última revisión**: 2026-05-15

## Síntoma

`sqlite3.OperationalError: database is locked` aparece en los logs. Cómo se manifiesta:

- El writer thread del tracking store no avanza. El TUI muestra el batch en `S5_DONE` pero el contador final no se actualiza.
- `cmcourier batch show` se cuelga o devuelve un timeout de SQLite.
- Si el lock es del reader, no del writer, la pipeline arranca y muere en `start_batch` con el mismo error.

**Importante**: en CMCourier corre con `PRAGMA journal_mode=WAL` (ver dossier §12). En WAL los readers no bloquean al writer y vice-versa — si igual ves un lock, casi seguro hay un proceso externo con la DB abierta en modo exclusive (DB Browser, DBeaver, otro `cmcourier` huérfano, un `sqlite3 <db>` abierto en otra terminal).

## Diagnóstico rápido

```bash
# 1. ¿Quién tiene el archivo abierto?
lsof "$(rg 'db_path' sample/config.yaml | awk '{print $2}')"
# Cualquier PID que no sea tu corrida activa es sospechoso.

# 2. Alternativa más rápida si tenés fuser
fuser -v "$(rg 'db_path' sample/config.yaml | awk '{print $2}')"

# 3. ¿Hay procesos cmcourier huérfanos?
pgrep -af cmcourier

# 4. ¿Existen los archivos de WAL? (señal de WAL activo o checkpoint inconcluso)
ls -la sample/*.db sample/*.db-wal sample/*.db-shm 2>/dev/null
```

## Mitigación inmediata

1. **Cerrá cualquier GUI conectada a la DB**. Los sospechosos comunes:
   - SQLite Browser / DB Browser for SQLite (abre en modo write por default)
   - DBeaver con una conexión activa
   - VS Code con la extensión SQLite Viewer
   - Un `sqlite3 <db>` interactive en otra terminal
2. **Matá procesos `cmcourier` huérfanos** (los que viste en `pgrep -af`):
   ```bash
   kill <PID>
   # Esperá 10s. Si sigue vivo:
   kill <PID>  # SIGTERM otra vez
   # Solo como ÚLTIMO recurso, y entendiendo que vas a tener que correr
   # el runbook tracking-db-locked otra vez si esto fragmenta el WAL:
   kill -9 <PID>
   ```
3. **Si ningún proceso aparece pero el lock persiste**: hay un `.db-shm` huérfano. NO lo borres todavía — pasá a Resolución.

## Resolución

### Caso A: el lock lo tenía un proceso externo

Una vez cerrado, validá:

```bash
lsof "$(rg 'db_path' sample/config.yaml | awk '{print $2}')"
# Sin output → libre. Pasá a Verificación.
```

### Caso B: proceso huérfano matado

Después del kill, los archivos WAL/SHM pueden haber quedado en estado inconsistente. Chequeá la integridad antes de relanzar:

```bash
sqlite3 sample/tracking.db "PRAGMA integrity_check;"
# Esperás "ok" en una sola línea.
```

Si devuelve `ok`, listo. Si devuelve una lista de errores o `database disk image is malformed`, **no es lock — es corrupción**. Salí de este runbook y andá a [`how-to/operator/recover-from-a-corrupted-tracking-db.md`](../how-to/operator/recover-from-a-corrupted-tracking-db.md).

### Caso C: `.db-shm` huérfano sin proceso vivo

Esto pasa cuando un `kill -9` dejó el shared-memory file pero ya no hay quien lo use:

```bash
# 1. Confirmá que NADIE tiene la DB abierta
lsof sample/tracking.db
# (sin output)

# 2. Forzá un checkpoint con sqlite3 directo
sqlite3 sample/tracking.db "PRAGMA wal_checkpoint(TRUNCATE);"
# Devuelve "0|N|N" donde N es la cantidad de páginas procesadas.

# 3. Si el checkpoint pincha con "database is locked", recién ahora podés
#    borrar los aux files. Es seguro PORQUE confirmaste que nadie los usa:
rm -f sample/tracking.db-wal sample/tracking.db-shm
```

Después corré integrity_check para confirmar que la DB principal sobrevivió:

```bash
sqlite3 sample/tracking.db "PRAGMA integrity_check;"
```

## Verificación

```bash
# 1. Integrity pasa
sqlite3 sample/tracking.db "PRAGMA integrity_check;"   # → ok

# 2. CMCourier abre la DB
cmcourier batch list --config sample/config.yaml

# 3. Reanudá la corrida — debería avanzar
cmcourier csv-trigger-pipeline run \
    --config sample/config.yaml \
    --batch-id <batch-id> \
    --resume
```

El TUI vuelve a actualizar contadores en S6 y `done` sube. Si seguís viendo `database is locked` después de relanzar, hay otro proceso que NO viste con `lsof` (containerizado, montado por NFS, etc.) — re-escaneá ampliando el ámbito.

## Post-mortem

- Anotá qué proceso tenía el lock. Si fue una GUI humana, es problema de proceso: definí una política de "nadie abre la DB en GUI sobre el host de producción".
- Si fue un `cmcourier` huérfano, indagá por qué quedó vivo. Causas típicas: un `kill -9` previo, un crash del TUI que dejó el orchestrator en background, una desconexión SSH sin `disown`/`nohup`.
- Si fue corrupción enmascarada como lock (Caso B con integrity_check fallando), seguramente hubo un evento anterior (disk full, OOM kill). Cruzá fechas con `dmesg` y `journalctl`.

## Ver también

- [`disk-full-during-prep.md`](disk-full-during-prep.md) — disk full suele preceder a este síntoma.
- [`how-to/operator/recover-from-a-corrupted-tracking-db.md`](../how-to/operator/recover-from-a-corrupted-tracking-db.md) — receta completa de recovery si integrity falla.
- [`explanation/architecture-overview.md`](../explanation/architecture-overview.md) — por qué el writer es un thread separado y cómo funciona el WAL en este proyecto.

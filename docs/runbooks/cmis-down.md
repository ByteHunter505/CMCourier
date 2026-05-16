> [← Volver al índice](../INDEX.md) · [Runbooks](README.md)

# Runbook: CMIS devuelve 5xx en oleada

> **Severidad**: P1 · **Tiempo estimado**: 15 min · **Última revisión**: 2026-05-15

## Síntoma

Tres señales que se ven juntas (cualquiera basta para sospechar, las tres confirman):

- Logs llenos de `CMISServerError` (status 5xx) seguidos de `RetriesExhaustedError` con `attempts={retry_max_attempts}`.
- Tab `UPLOAD` del TUI: el contador `failed` sube rápido mientras `done` se queda quieto. El throughput cae a 0 MB/s.
- AIMD halve repetido en logs (`auto_tune decision=halve`) hasta clavarse en `min_threads`.

Esto típicamente significa que el server CMIS (IBM Content Manager o Alfresco según el ambiente) está caído, en mantenimiento, o tirando 5xx por load shed.

## Diagnóstico rápido

```bash
# 1. ¿El server responde HTTP?
curl -k -sS -o /dev/null -w "%{http_code}\n" \
    "$(rg 'base_url' sample/config.yaml | head -1 | awk '{print $2}')?cmisselector=repositoryInfo"
# Esperás 200. Si ves 5xx, 000 (timeout) o connection refused → server caído.

# 2. ¿Es de red o del server?
ping -c 3 <host-cmis>

# 3. Validación canónica desde CMCourier
cmcourier doctor --config sample/config.yaml --check cm-targets
# Si falla en cmis_connectivity, los checks cm_type_alignment / cmis_folders_exist /
# cmis_properties_alignment quedan SKIPPED en cascada. Eso es esperado.

# 4. ¿Cuánto venimos perdiendo?
cmcourier batch show <batch-id> --config sample/config.yaml
# Mirá la fila S5: si FAILED >> DONE, el sangrado es real.
```

> El warmup real usa `GET {base_url}/{repo_id}?cmisselector=repositoryInfo` para IBM CM, o `GET {base_url}?cmisselector=repositoryInfo` para Alfresco (`repo_id=""`). Replicá esa URL exacta — sirve para descartar bugs de routing en la `base_url`.

## Mitigación inmediata

1. **`Ctrl+C` en la corrida activa**. Esperá el shutdown graceful (15–30 s). El TUI muestra `Shutting down…`. El tracking DB queda consistente porque el writer thread drena la queue antes de cerrar.
2. **NO uses `kill -9`**. Deja el WAL en estado raro y vas a sumar un segundo runbook arriba de este.
3. **Si la corrida ya terminó sola con exit code 1**: no hay nada que detener, los `S5_FAILED` ya quedaron registrados y son reintentables.

A esta altura el sangrado paró: ningún doc nuevo se está marcando `S5_FAILED` por culpa del 5xx.

## Resolución

1. **Contactá al equipo de Content Manager** (o al admin de Alfresco si estás en staging). Lo que ellos necesitan:
   - URL exacta (`cmis.base_url`).
   - Hora de la primera 5xx (sale del primer log con `status: 5\d\d` en `logs/network-*.jsonl`).
   - Status code observado (500/502/503/504). Cada uno apunta a una causa distinta — 503 suele ser load shed, 504 timeout de gateway, 500 bug del server.
2. **Esperá la confirmación de que el server volvió**. No reintentes a ciegas: si está en degraded mode, vas a clavar AIMD en `min_threads` otra vez y a sumar `S5_FAILED` artificiales.
3. **Re-validá con doctor** antes de tocar la pipeline:
   ```bash
   cmcourier doctor --config sample/config.yaml --check cm-targets
   ```
   Tienen que pasar `cmis_connectivity`, `cm_type_alignment`, `cmis_folders_exist`, `cmis_properties_alignment`. Si alguno sigue fallando, el server no está realmente up — volvé al paso 1.

## Verificación

El estado del batch sobrevivió al outage (tracking DB en WAL, idempotency por `rvabrep_txn_num`). Tenés dos caminos según qué tan limpio quedó:

**Caso A — solo S5 quedó dañado** (lo más común):

```bash
cmcourier batch retry-failed \
    --config sample/config.yaml \
    --batch <batch-id> \
    --stage S5
```

Esto resetea las filas `S5_FAILED` a `S5_PENDING`. Después relanzá la pipeline con `--resume`:

```bash
cmcourier csv-trigger-pipeline run \
    --config sample/config.yaml \
    --batch-id <batch-id> \
    --resume
```

**Caso B — querés rehacer desde S5 sin discriminar FAILED vs DONE** (raro, solo si sospechás que el server confirmó uploads que NO persistió):

```bash
cmcourier csv-trigger-pipeline run \
    --config sample/config.yaml \
    --batch-id <batch-id> \
    --from-stage 5
```

`--from-stage` explícito le gana a `--resume` (cableado en `app.py:803`+). Los docs con `S5_DONE` se saltean por idempotency (`is_uploaded()` → `S1_SKIPPED`).

Confirmá que la corrida avanza:

- TUI tab `UPLOAD`: `done` sube, `failed` se mantiene en el conteo previo.
- TUI tab `CHUNKS`: los chunks pasan de `S5` a `S6` (tracking).
- Logs: deja de aparecer `CMISServerError` y empieza `cmis_post status=201` (creación exitosa).

## Post-mortem

Documentá en el ticket del incidente:

- Ventana exacta del outage (primera 5xx → primer 2xx después de la recuperación).
- Cantidad de `S5_FAILED` generados (sale de `cmcourier batch show <id>`).
- Cuántos fueron auto-recuperables vía `retry-failed` y cuántos pidieron intervención manual.
- Si AIMD se clavó en `min_threads` y por cuánto tiempo (busca `auto_tune decision=halve` en `logs/pipeline-*.jsonl`).

Métricas a revisar la semana siguiente:

- `cmis_request` p95 en `logs/network-*.jsonl`. Si subió de forma estable, hablá con CM para entender capacidad.
- Tasa de 5xx histórica. Si esto pasa más de 1×/mes, considerá bajar `auto_tune.target_p95_ms` o subir `auto_tune.halve_threshold_ratio` (más tolerancia antes de halve).

## Ver también

- [`explanation/aimd-auto-tuning.md`](../explanation/aimd-auto-tuning.md) — por qué AIMD se clava y cómo leerlo.
- [`how-to/operator/retry-only-failed-records.md`](../how-to/operator/retry-only-failed-records.md) — receta detallada de `batch retry-failed`.
- [`how-to/operator/tune-aimd-for-a-slow-link.md`](../how-to/operator/tune-aimd-for-a-slow-link.md) — si el problema es de tuning, no de outage.

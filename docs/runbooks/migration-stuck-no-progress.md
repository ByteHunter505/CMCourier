> [← Volver al índice](../INDEX.md) · [Runbooks](README.md)

# Runbook: Migración trabada sin progreso

> **Severidad**: P2 · **Tiempo estimado**: 20 min · **Última revisión**: 2026-05-15

## Síntoma

La pipeline está viva pero no avanza:

- TUI muestra throughput de **0 docs/s sostenido por más de 30 segundos**.
- Tab `BUCKET` (streaming) o `UPLOAD` (batched): `queue_depth` constante y `done` no sube.
- AIMD entra en loop de halve repetido (`auto_tune decision=halve` cada `adjustment_interval_s`) hasta quedar clavado en `min_threads`.
- No hay `*_FAILED` subiendo — distinto de [`cmis-down.md`](cmis-down.md), acá los workers simplemente no terminan los items que ya tomaron.

## Diagnóstico rápido

```bash
# 1. ¿La pipeline está viva o murió en silencio?
pgrep -af cmcourier

# 2. ¿En qué stage está cada chunk? (multi-batch)
cmcourier batch show <batch-id> --config sample/config.yaml
# Mirá los counts por stage. Si S4_PENDING o S5_PENDING están altos y no bajan, ese es el cuello.

# 3. Inspect a nivel doc — qué txn está en vuelo y desde hace cuánto
cmcourier inspect rvabrep \
    --config sample/config.yaml \
    <SHORTNAME> <SYSTEM_ID>
# (shortname y system_id van como argumentos posicionales)
# Útil si sospechás que un trigger puntual rompió la indexación.

# 4. Dónde están realmente los threads bloqueados — el diagnóstico definitivo
pip install py-spy   # si no lo tenés
sudo py-spy dump --pid "$(pgrep -f 'cmcourier .* run' | head -1)"
# Te muestra el stack de cada thread. Buscá llamadas en httpx (CMIS lento),
# pyodbc (AS400 lento), o assembly (img2pdf/Pillow lento).

# 5. ¿System metrics dan pista?
tail -5 logs/system-*.jsonl | python3 -m json.tool
# CPU bajo + RAM baja + net bajo → workers esperando algo (I/O bound)
# CPU 100% sin progreso → bug de busy loop o assembly en input patológico
```

## Mitigación inmediata

1. **NO mates con `kill -9`**. El tracking writer thread queda con queue en memoria sin flushear y la DB queda en estado raro (vas a sumar [`tracking-db-locked.md`](tracking-db-locked.md) o peor a la sesión).
2. **`Ctrl+C` y esperá el graceful shutdown**. Puede tardar hasta 60 segundos si AIMD está bajando timeouts. El TUI muestra `Shutting down…` y los workers terminan o cancelan sus operaciones en curso.
3. **Si el shutdown se cuelga >60 s**: probablemente hay una operación de red sin timeout efectivo. Bajá a `SIGTERM` por PID:
   ```bash
   pkill -TERM -f cmcourier
   ```
4. **No reintentes a ciegas**. Sin diagnóstico, vas a clavarte en el mismo punto otra vez.

## Resolución

Según lo que mostró el `py-spy dump`:

### CMIS lento (stack en `httpx`, `_warmup_session`, `upload_one`)

El server CMIS está respondiendo pero lento (p95 > `target_p95_ms`). AIMD debería estar bajando workers, pero si está clavado en `min_threads` ya tocó fondo. Opciones:

- Hablá con el equipo de CM por qué la latencia subió.
- Si el ambiente es de bajo throughput esperable (link finito, server compartido), recalibrá AIMD:
  ```yaml
  cmis:
    auto_tune:
      target_p95_ms: 10000          # default 5000; subilo si tu link es lento honestamente
      halve_threshold_ratio: 2.0     # default 1.5; más tolerancia antes de halve
      min_threads: 4                 # default 2; si tu link aguanta más, subí el piso
  ```
  Detalle del algoritmo en [`explanation/aimd-auto-tuning.md`](../explanation/aimd-auto-tuning.md) y receta paso a paso en [`how-to/operator/tune-aimd-for-a-slow-link.md`](../how-to/operator/tune-aimd-for-a-slow-link.md).

### Prep trabada (stack en `assembly`, `img2pdf`, `Pillow`, `PyPDF2`)

S4 está atascado ensamblando PDFs. Causas y remedios:

- **Input patológico**: un TIFF con compresión rara o un PDF muy grande. Mirá el `txn_num` que está en vuelo (logs `stage=S4`), pedí el archivo del file server y reproducí localmente con `single-doc run`.
- **`prep_workers` mal dimensionado**: si tenés `s4_use_processes: true` (default 066) y `s4_max_processes` cerca de `os.cpu_count()`, podés estar saturando CPU. Bajá `prep_workers` o ponele tope explícito a `s4_max_processes`.
- **Heavy/Light lanes en streaming**: si `processing.heavy_light_lanes.enabled: true` y todos los docs son heavy (> `heavy_threshold_bytes`), la light lane queda ociosa mientras heavy se traba. Revisá `LANES` en TUI tab `UPLOAD` o `BUCKET`.

### AS400 lento (stack en `pyodbc.Cursor.execute`)

S1 está colgado esperando respuesta de RVABREP. Mirá [`as400-down.md`](as400-down.md) — si AS400 responde TCP pero las queries cuelgan, el subsystem está saturado.

### CPU al 100% sin progreso

Bug de busy loop. Capturá `py-spy record -o profile.svg --pid <PID> --duration 30` y abrí el flamegraph. Reportá como bug — esto no debería pasar en steady-state.

## Verificación

```bash
# 1. Reanudá con la config ajustada
cmcourier csv-trigger-pipeline run \
    --config sample/config.yaml \
    --batch-id <batch-id> \
    --resume

# 2. Después de 2-3 minutos, validá throughput
# TUI tab UPLOAD: docs/s > 0, queue_depth bajando.
# TUI tab CHUNKS: los chunks progresan de S5 a S6.

# 3. Si quedó stuck otra vez en el mismo punto:
cmcourier batch show <batch-id> --config sample/config.yaml
# Identificá si el cuello sigue siendo el mismo stage. Si sí, el ajuste no fue suficiente.
```

## Post-mortem

- Anotá qué stage era el cuello según el `py-spy dump`. Sin ese dato, cualquier conclusión es adivinanza.
- Si fue CMIS lento, mirá si la latencia bajó después de la queja al equipo de CM o si tu config nueva la absorbió.
- Si fue prep, documentá si fue un input patológico (caso aislado) o un sizing wrong (problema sistémico).
- Si AIMD se clavó en `min_threads` por una hora, probablemente esos defaults no son los correctos para tu ambiente — abrí ticket para revisar la calibración del 068 (`growth_factor`, `halve_factor`, `halve_threshold_ratio`).
- Guardá un snapshot del `batch_summary` JSON del log para comparar contra corridas siguientes.

## Ver también

- [`cmis-down.md`](cmis-down.md) — si los workers fallan rápido en vez de quedarse colgados.
- [`as400-down.md`](as400-down.md) — si el cuelgue es en S0/S1.
- [`explanation/aimd-auto-tuning.md`](../explanation/aimd-auto-tuning.md) — el algoritmo y cómo leer las decisiones.
- [`how-to/operator/tune-aimd-for-a-slow-link.md`](../how-to/operator/tune-aimd-for-a-slow-link.md) — receta para ajustar AIMD a un link real.
- [`explanation/heavy-light-lanes.md`](../explanation/heavy-light-lanes.md) — cuándo activar lanes y cuándo te empeora.

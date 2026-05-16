> [← Volver al índice](../INDEX.md) · [Tutoriales](README.md)

# 03 — Modos de Ejecución: Batched vs Streaming

CMCourier tiene dos orquestadores que cambian radicalmente cómo se ejecuta una pipeline. El `trigger.kind` y el comando que disparás no cambian — el orquestador sí. Lo elegís con un solo flag en el config:

```yaml
processing:
  mode: batched           # o "streaming"
```

En este tutorial entendés qué hace cada uno, cuándo elegir cuál, y qué tradeoffs hay.

> **Nota histórica**: streaming entró en 063 (`StreamingOrchestrator`). El default sigue siendo `batched` porque es el modo con resume. Lanes se unificaron entre ambos modos en 070.

---

## El problema que cada modo resuelve

Antes de entrar en mecánica, las dos preguntas que cada modo contesta:

1. **¿Cuánto pico de memoria estás dispuesto a aceptar?**
2. **¿Cuán importante es poder hacer resume tras un kill?**

| Modo | Memoria peak | Resume | Cuándo elegir |
|------|--------------|--------|---------------|
| `batched` | `O(batch_size × batches_in_flight)` | **Sí** | Lotes acotados, runs que pueden cortarse, mayoría de los casos |
| `streaming` | `O(bucket_size)` ~constante | **No** (rechaza `from_stage > 1`) | Migraciones grandes, hardware acotado de memoria, máximo throughput |

---

## Modo `batched` (default)

### Orquestador: `MultiBatchOrchestrator`

Source: `src/cmcourier/orchestrators/multi_batch.py`. Entró en 028.

### Comportamiento

El orquestador divide los triggers en **chunks** de `batch_size` (top-level del config, default 1000). Procesa hasta `batches_in_flight` chunks en paralelo (default 2). Cada chunk recorre S0 → S5 de manera secuencial; lo que se overlapa es **prep de chunk K+1** con **upload de chunk K**.

```
chunk 0:  [S1│S2│S3│S4│S5═════════════]
chunk 1:                  [S1│S2│S3│S4│S5═════════════]
chunk 2:                                   [S1│S2│S3│S4│S5═════════════]
                                              ↑ K+1 prepara mientras K sube
```

El pool de workers S5 es **compartido** entre chunks — no hay duplicación de threads. Cada chunk tiene su propio `MetricsRecorder` + `ChunkState` para que los percentiles no se mezclen.

### Qué hace si un chunk falla

Falla un chunk, los otros siguen. Al final el orquestador devuelve un `MultiBatchRunReport` con los chunks fallados loggeados pero el resto cuenta como éxito parcial. Exit code 1.

### Resume

`batched` soporta resume completo:

- `--from-stage 5` salta directo a S5 si los docs ya están ensamblados.
- `--resume` auto-detecta el `from-stage` mirando el estado del batch en SQLite.
- 044 hace robusto el resume incluso después de `kill -9` en medio de S5 (detecta gaps de stage `S{N}_DONE → S{N+1}`).

### Cuándo elegirlo

- El lote es chico-mediano (cientos de miles).
- Querés poder cortar y reanudar.
- Estás haciendo un dry run y querés ver el comportamiento clásico.
- Es el default — si no tenés razón para cambiarlo, dejalo así.

---

## Modo `streaming` (063)

### Orquestador: `StreamingOrchestrator`

Source: `src/cmcourier/orchestrators/streaming.py`. Entró en 063.

### Comportamiento

No hay chunks. Hay un solo `batch_id` que dura todo el run. Adentro:

- **Productores (PREP)** corren S1–S4 dimensionados por `processing.prep_workers`.
- **Consumidores (UPLOAD)** corren S5 dimensionados por el `_pool_ceiling()` (el techo de AIMD).
- Entre los dos hay un **bucket**: un `queue.Queue` bounded de tamaño `processing.streaming.bucket_size` (default 100).
- Cuando el bucket está lleno los productores se bloquean; cuando está vacío los consumidores se bloquean. Eso es back-pressure natural.

```
[S1│S2│S3│S4] → ┐
[S1│S2│S3│S4] → ├─→ [bucket de N=100] → ┌─→ [S5]
[S1│S2│S3│S4] → ┘                       ├─→ [S5]
                                        └─→ [S5]
   K productores                         M consumidores
```

Al final del stream, los productores envían **poison pills** y los consumidores hacen shutdown ordenado.

### Por qué la memoria es constante

En `batched`, si subís el `batch_size` a 10000, vas a tener 10000 docs ensamblados en disco/RAM esperando ser subidos. En `streaming`, **siempre** hay a lo sumo `bucket_size` docs intermedios. Cuando un doc se sube, libera lugar en el bucket; un productor inmediatamente pone otro. El pico no escala con el total — solo con el bucket.

Eso es lo que permite migrar 20M filas de RVABREP sin OOM (esa fue la motivación de 063).

### Resume: rechazado

```python
# orchestrators/streaming.py
if from_stage > 1 or resume_batch_id:
    raise ValueError("streaming mode does not support resume")
```

Si pasás `--from-stage 5` o `--resume` con `mode: streaming`, el orquestador te tira `ValueError` antes de arrancar. ¿Por qué?

Streaming no tiene chunks discretos para identificar "qué quedó en cada estado". El recorrido es continuo, así que el invariante de "todos los docs del chunk K llegaron al menos a Sn" no existe.

¿Cómo recuperás entonces? **Re-corrés todo** — la idempotencia cross-batch te salva. Los docs ya `S5_DONE` se marcan `S1_SKIPPED` en S1 (062) y no se re-procesan. El precio: viaje extra a SQLite para chequear `is_uploaded`, pero no re-subida. La trazabilidad la dan las filas `S1_SKIPPED` que aparecen en `inspect` / `analyze`.

### Lanes

Lanes heavy/light (036) funcionan en ambos modos desde 070 (antes era solo batched). Si activás `heavy_light_lanes.enabled: true` en config con `mode: streaming`, el orquestador inserta un **dispatcher** entre el bucket y S5 que rutea cada item a cola heavy o light según `staged_file.size_bytes >= heavy_threshold_bytes`. Cada lane tiene su propio pool gateado por el `LaneController` unificado.

### Cuándo elegirlo

- Migración productiva grande (>500k docs).
- Memoria es restricción (server con poca RAM, container limitado).
- No te importa el resume — vas a correr de un saque o re-correr completo.
- Querés ver el throughput máximo sostenido sin valles entre chunks.

---

## Tabla comparativa completa

| Aspecto | `batched` | `streaming` |
|---------|-----------|-------------|
| Default | **Sí** | No |
| Orquestador | `MultiBatchOrchestrator` | `StreamingOrchestrator` |
| Memoria peak | `O(batch_size × batches_in_flight)` | `O(bucket_size)` |
| Resume soportado | **Sí** (`--from-stage`, `--resume`) | **No** (raises `ValueError`) |
| `batches_in_flight` | Honrado (1–2) | Ignorado |
| `bucket_size` | Ignorado | Aplica |
| Chunks discretos | Sí (uno por `batch_size`) | No (un único chunk sintético en TUI) |
| Tab TUI principal | `CHUNKS` | `BUCKET` |
| Lanes (036) | Sí | Sí (desde 070) |
| AIMD | Sí | Sí |
| Recorder por chunk | Sí (uno por chunk) | Un solo recorder global |
| Failed handling | Chunk falla, otros siguen | Productores fallidos drainean, consumidores siguen |
| Cuándo elegir | Lotes acotados, runs interrumpibles | Migraciones grandes, RAM acotada |

---

## Ejemplo: el mismo lote, dos configs

### Config `batched` (clásico)

```yaml
processing:
  mode: batched
  batches_in_flight: 2
  prep_workers: 4
batch_size: 1000
```

Comportamiento: el lote de 50k se parte en 50 chunks de 1000. Dos chunks activos a la vez. Pico de memoria = 2 × 1000 docs ensamblados = ~2GB si los docs promedian 1 MB.

### Config `streaming` (memoria constante)

```yaml
processing:
  mode: streaming
  prep_workers: 4
  streaming:
    bucket_size: 100
batch_size: 1000          # se usa solo como sema en métricas
```

Comportamiento: un solo batch_id durando el run entero. 4 productores ensamblan, M consumidores suben, bucket de 100 en el medio. Pico de memoria = ~100 docs ensamblados ≈ 100 MB.

Mismo input. Mismo CMIS de destino. La diferencia es perfil de memoria y trazabilidad de chunks.

---

## Combinación con lanes y AIMD

Lanes y AIMD son ortogonales al modo. Podés combinarlos como quieras:

| Combinación | Comportamiento |
|-------------|----------------|
| `batched` + AIMD | Default productivo. AIMD escala el pool S5 entre chunks. |
| `batched` + AIMD + lanes | Pool S5 partido en heavy/light, ambos limitados por el budget total del AIMD. |
| `streaming` + AIMD | El productor dispatchea al bucket, los consumidores escalan según p95. |
| `streaming` + AIMD + lanes | Dispatcher + dos pools por lane, todos bajo el `LaneController` unificado (070). |

> Para AIMD ver la sección 10 del [dossier](../_internal/dossier.md). Para lanes ver `docs/how-to/heavy-light-lanes.md`.

---

## Decidir en 30 segundos

1. ¿Tu lote es < 100k docs y querés poder cortar? → `batched`.
2. ¿Tu lote es > 500k y la RAM es ajustada? → `streaming`.
3. ¿No estás seguro? → `batched`. Es el default por algo.

Para arrancar siempre arrancás con `batched`. Si en producción ves picos de RAM que no querés, ahí movés a `streaming`. Antes no.

---

## Siguientes pasos

- [04 — Tour de todos los comandos](04-all-commands-tour.md): el CLI entero
- [06 — Tu primera corrida streaming](06-first-streaming-run.md): walkthrough con TUI en modo streaming
- [`docs/how-to/multi-batch.md`](../how-to/multi-batch.md): receta concreta de multi-batch (batched + overlap)
- [`docs/how-to/heavy-light-lanes.md`](../how-to/heavy-light-lanes.md): activar y tunear lanes

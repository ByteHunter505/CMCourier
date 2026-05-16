> [← Volver al índice](../INDEX.md) · [ADRs](README.md)

# ADR-006: Lanes heavy/light en el pool de upload

- **Estado**: Aceptado y vigente
- **Fecha**: 2026-05-15
- **Spec(s) relacionadas**: 036 (heavy/light lanes iniciales), 065 (extensión a streaming), 070 (unificación del `LaneController` entre batched y streaming)
- **Versión donde se shipping**: 0.37.0 (lanes en batched); 0.67.0 (lanes en streaming); 0.72.0 (controller unificado)

## Contexto

El stage S5 (CMIS upload) usa un pool de workers (controlado por AIMD — ver [ADR-004](004-aimd-auto-tune.md)). Pre-036 era un único pool indiferenciado: cada worker tomaba el próximo doc del bucket/queue y lo subía.

El problema apareció en datasets reales con distribución bimodal de tamaño — algo común en producción del banco. Un mismo trigger CSV producía mix de:

- Docs chicos (1–2 MB): autorizaciones, formularios firmados.
- Docs medianos (5–10 MB): paquetes consolidados de varios pages.
- **Docs grandes (30–100+ MB)**: TIFFs multipage de 540 páginas, ensamblados como un único PDF.

Con un pool único de, digamos, 8 workers, lo que pasaba era esto: 3 docs gigantes llegaban a la cabeza de la queue, tomaban 3 slots, cada upload demoraba ~30-90 segundos. Mientras tanto, los otros 5 slots procesaban docs chicos a ~1 segundo cada uno — pero atrás de los 3 gigantes había **decenas de docs chicos en cola** esperando un slot libre. Resultado: latencia por-doc terrible para los chicos. El operador veía la TUI clavada en 3-4 docs/s cuando podía ir a 30+.

Esto es **head-of-line blocking** clásico. En la spec 036 lo abordamos con el patrón estándar: **dos lanes**, una para "heavy" (≥ 10 MB) y otra para "light" (< 10 MB). Cada una con su slice del budget total que AIMD controla. Si una lane se queda sin trabajo, un daemon rebalance migra un worker a la lane que tiene cola.

## Decisión

Implementamos lanes heavy/light en tres etapas, sin breaking changes en cada una:

**Spec 036 — batched mode.** Introdujimos `LaneController` con dos `ResizableSemaphore`s (heavy + light) compartiendo el budget total que AIMD controla. El umbral default `heavy_threshold_bytes: 10485760` (10 MB) es el divisor empírico. `heavy_lane_min_batch: 50` evita activar lanes para batches chicos donde el overhead no se paga. Un daemon `rebalance_interval_s: 10.0` chequea si una lane está idle más de `idle_threshold_s: 15.0` y migra 1 worker a la otra. Las dos lanes siempre tienen ≥ 1 worker (floor). Default `enabled: False` por seguridad: el operador opt-in.

**Spec 065 — streaming mode.** Cuando `processing.mode == "streaming"` AND `heavy_light_lanes.enabled == true`, `StreamingOrchestrator` arma un dispatcher thread que rutea cada item del bucket principal a una de dos queues per-lane según `staged_file.size_bytes ≥ heavy_threshold_bytes`. Heavy y light tienen pools de consumers separados. El `LaneController` y las semáforos siguen del 036 — la novedad es el dispatcher y el ruteo por *tamaño real del staged file*.

**Spec 070 — unificación del controller.** Bug operativo post-067: la UPLOAD-tab mostraba `queue 0` para HEAVY y LIGHT eternamente, mientras la BUCKET-tab mostraba los mismos campos vivos y correctos. Root cause: había **dos instancias de `LaneController`** en streaming + lanes. `StagedPipeline.__init__` (036) construía una; `StreamingOrchestrator.__init__` construía otra. El `TUIDataProvider.lane_snapshot` leía la del pipeline — la muerta en modo streaming. Peor todavía: AIMD's `set_total_budget` también estaba llamando al controller muerto, así que el rebalance per-lane nunca llegaba a las semáforos vivas. Spec 070 hace que `StreamingOrchestrator` **reuse** `pipeline.lane_controller` via property forwarding. Ahora hay una sola instancia que todos comparten.

## Consecuencias

### Positivas

- **Head-of-line blocking resuelto.** Docs chicos no esperan atrás de gigantes. Latencia per-doc para light docs se vuelve estable e independiente del traffic heavy.
- **Throughput agregado similar o mejor.** El wall-clock total en el test sintético bimodal (30 × 1 MB + 5 × 50 MB, N=4 workers) gana ~5-10% — la cola heavy sigue dominando el tail. La gana real visible al operador es la latencia per-doc, no el wall-clock.
- **AIMD sigue dueño del budget total.** El controller no se duplica: AIMD ajusta `total_budget`, `LaneController.set_total_budget` redistribuye preservando la ratio actual y respetando los floors. Una sola fuente de verdad para el "cuántos workers en total".
- **Dispatcher streaming es barato.** Una comparación + un `queue.put` por item. Cero overhead medible.
- **El bug del 070 ya no se reproduce.** Una sola instancia de `LaneController` por run, sea batched o streaming.

### Negativas / Tradeoffs

- **`heavy_light_lanes.enabled` es opt-in.** El operador tiene que conocer y activar el feature. Default off por riesgo: no queremos cambiar el comportamiento de runs existentes silenciosamente.
- **Un umbral binario es heurística.** Un doc de 9.99 MB va a la lane light; uno de 10.01 MB va a heavy. La discontinuidad existe. Mitigamos esto con el rebalance daemon — si la diferencia entre lanes se vuelve extrema, los workers migran. Pero conceptualmente es una aproximación, no un óptimo.
- **Total in-flight upper bound en streaming es `3 × bucket_size`** (main bucket + heavy queue + light queue). El operador que dimensiona su memoria por `bucket_size` tiene que saber esto. Aceptable porque las lane queues drenan asimétricamente — rara vez están las tres llenas al mismo tiempo.
- **Spec 070 movió `LaneController` ownership al `StagedPipeline`.** Es una decisión de wiring sutil: el streaming orchestrator no posee el controller, lo reusa. Cualquier feature futura que toque lanes tiene que respetar esa propiedad.
- **Bandwidth limiter no es per-lane.** Ambas lanes comparten el `BandwidthLimiter` global (spec 029). Si el operador necesita per-lane bandwidth quota, eso es POST-MVP §8 (no implementado).

### Neutras

- **El rebalance daemon es muy simple.** Drena-driven: si una lane queda vacía > `idle_threshold_s`, migra 1 worker. No optimiza utilización dinámicamente; reacciona a starvation. Para los workloads del banco alcanza.

## Alternativas consideradas

- **Shortest-job-first (SJF).** Idea: priorizar docs chicos. Requiere estimar el tamaño antes de subir — que es lo que hace nuestro split por `staged_file.size_bytes`, pero global en lugar de por-lane. La complejidad de mantener una priority queue ordenada con resize concurrente del pool era injustificada. Lanes son SJF aproximado con menos overhead.
- **Three lanes (small/medium/large).** Doble la complejidad, gana marginal. El bimodal real del banco es heavy vs el resto — un tercer corte no agrega claridad.
- **Round-robin entre buckets.** Mantiene head-of-line blocking dentro de cada bucket. No resuelve el problema.
- **Single lane con AIMD más agresivo.** Más workers no resuelven el problema si los 3 más viejos están atascados con docs gigantes. El problema es estructural, no de capacidad.
- **Dejar a operador decidir cantidad de workers per-size.** Configuración manual no escala — el dataset real tiene distribución que el operador no conoce de antemano.

## Ver también

- [Explanation: heavy/light lanes](../explanation/heavy-light-lanes.md)
- [Spec 036 — heavy/light lanes inicial](../../specs/036-heavy-light-lanes/)
- [Spec 065 — heavy/light lanes en streaming](../../specs/065-streaming-heavy-light-lanes/)
- [Spec 070 — unificación del LaneController](../../specs/070-unify-lane-controller/)
- [ADR-004: AIMD auto-tune](004-aimd-auto-tune.md)
- [ADR-003: modo streaming](003-streaming-mode.md)

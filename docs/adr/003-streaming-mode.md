> [← Volver al índice](../INDEX.md) · [ADRs](README.md)

# ADR-003: Modo `streaming` con bucket acotado

- **Estado**: Aceptado y vigente
- **Fecha**: 2026-05-15
- **Spec(s) relacionadas**: 063 (orquestador streaming core), 064 (tab BUCKET del TUI), 065 (lanes en streaming), 067 (fixes de TUI en streaming)
- **Versión donde se shipping**: 0.65.0 (streaming core); 0.66.0 (BUCKET tab); 0.67.0 (lanes integradas)

## Contexto

El modo `batched` original (spec 028, `MultiBatchOrchestrator`) tomaba la lista entera de triggers, la cortaba en chunks de `batch_size × batches_in_flight` documentos y los pre-cargaba en memoria por chunk: PREP procesaba chunk K+1 mientras UPLOAD procesaba chunk K (N=2). Esto funcionó bien para el dry-run inicial — pero a escala de los datasets reales del banco se rompió:

- Memoria peak crecía como `batch_size × batches_in_flight`. Con `batch_size=100, N=2` ya estábamos en ~200 docs en RAM. Para los datasets reales (>100.000 docs en un sólo trigger), incluso con `batch_size=50` la combinación de docs + metadatos resueltos + staged files referenciados llegaba a OOM en hosts de producción del banco con RAM limitada.
- Había una "valle" idle entre chunks: cuando S5 terminaba el chunk K antes de que PREP terminara K+1, el pool de upload se quedaba parado. Cuando PREP terminaba K+1 antes de que S5 terminara K, los workers de PREP se quedaban parados. Las dos mitades nunca corrían al ritmo del eslabón más lento de forma sostenida — siempre estaban sincronizándose en los bordes del chunk.
- El `batches_in_flight` máximo era 2 por diseño (ampliar a N>2 requería un rework del shared pool de S5 + AIMD controller que no valía la pena).

El Principio IV de la Constitución es explícito: **streaming over buffering**. El modo batched lo violaba para listas de triggers grandes.

## Decisión

Introducimos un **segundo orquestador**, `StreamingOrchestrator` (spec 063), que corre adyacente al batched. El operador elige uno via `processing.mode: "batched" | "streaming"` en YAML. Default sigue siendo `batched` para preservar comportamiento pre-063 byte-a-byte.

La estructura del streaming es el patrón canónico **producer-consumer con buffer acotado**:

- Una `queue.Queue` con capacidad fija — el **bucket** — sentada entre PREP y UPLOAD. Tamaño configurable via `processing.streaming.bucket_size: int = 100`.
- `prep_workers` threads productores corriendo S1→S4 sobre triggers individuales y haciendo `bucket.put(staged_item)`. Si el bucket está lleno, bloquean: **back-pressure natural**.
- Pool de S5 consumers (sized a `_pool_ceiling()` = `max(cmis.workers, auto_tune.max_threads)`) haciendo `bucket.get()` y subiendo. Si el bucket está vacío, bloquean.
- Poison pills para shutdown ordenado.
- Un único `batch_id` por corrida, un único `MetricsRecorder` global.

Memory peak colapsa a **`bucket_size`** independiente del total de triggers. Para `bucket_size=100`, el peak es ~100 docs in-memory, sea el dataset de 1.000 o de 20 millones.

## Consecuencias

### Positivas

- **Memoria acotada y predecible.** El operador ajusta `bucket_size` y sabe exactamente cuánta RAM va a usar el pipeline. Cero correlación con el tamaño del dataset.
- **Cero idle entre chunks** porque no hay chunks. PREP y UPLOAD corren al ritmo del eslabón más lento de forma continua. Si UPLOAD es más lento (caso típico, red CMIS), PREP llena el bucket y se sienta. Si PREP es más lento (caso S4 pesado), UPLOAD drena el bucket y se sienta. En ambos casos el rate observado es el rate sostenible.
- **AIMD opera contra un único recorder.** No hay aislamiento por chunk como en batched. La p95 vista por AIMD es la p95 real del run completo. La guardia `min_samples=20` (spec 061) sigue cubriendo el cold-start.
- **Compatible con heavy/light lanes** (spec 065 — ver [ADR-006](006-heavy-light-lanes.md)). Un dispatcher thread entre el bucket y los consumers rutea por tamaño hacia lane heavy/light.

### Negativas / Tradeoffs

- **Resume está deshabilitado en streaming.** El modo no soporta `--from-stage > 1` ni `--resume` ni `--batch-id` operator-named. Si pasás cualquiera de esos, `StreamingOrchestrator` lanza `ValueError`. La traza para "este doc ya está subido" se cubre via spec 062 (filas `S1_SKIPPED` en `migration_log` por idempotencia cross-batch).
- **Cero overlap N=2 entre chunks.** El batched aceptaba la pérdida de memoria a cambio del overlap producer-consumer entre chunks. El streaming reemplaza ese overlap por el bucket continuo — pero pierde el concepto mismo de "chunk", que algunos operadores usaban como anchor mental ("chunk 3/12 terminó").
- **CHUNKS tab pierde sentido en streaming.** Lo reemplazamos con un BUCKET tab (spec 064) que muestra fill level vs cap, throughput PREP-side y UPLOAD-side en ventana de 5s, peak level. CHUNKS sigue presente pero muestra una fila sintética única — el operador que viene del modo batched tiene que adaptarse.
- **No vamos a poder reanudar runs interrumpidos.** Aceptado: spec 063 documenta que `resume era poco usado en producción` porque la idempotencia cross-batch (Principio II) ya cubría el 95% del use case. Cuando un run se interrumpe, el siguiente arranca limpio y los docs ya `S5_DONE` se filtran en S1.

### Neutras

- **`batched` no se removió.** Sigue siendo el default; es la opción correcta para batches chicos donde el overlap N=2 paga y la memoria no es problema.

## Alternativas consideradas

- **Subir `batches_in_flight` a N>2.** Reduciría las "valles" pero no resolvería el OOM — la memoria crecería *más*, no menos. Además, el shared S5 pool + AIMD controller requerían rework no trivial para N>2.
- **Cursor-based streaming sin bucket (un trigger → S1→S5 en línea).** Descartado: pierde toda la paralelización. Habría sido un único worker secuencial.
- **Reactive streams (RxPy o similar).** Overkill para una pipeline de 5 stages con tipos concretos. `queue.Queue` + threads es la implementación más simple del patrón producer-consumer y la stdlib la soporta nativa.
- **Async (asyncio).** Habría requerido rewrites masivos: `pyodbc`, `PIL`, `img2pdf`, `PyPDF2` son todas APIs síncronas. Aún `httpx` (que sí tiene async) usamos en modo sync porque el orquestador es `ThreadPoolExecutor`-based. La gana hipotética no justificaba el costo.

## Ver también

- [Explanation: streaming vs batched](../explanation/streaming-vs-batched.md)
- [Explanation: el patrón bucket](../explanation/the-bucket-pattern.md)
- [Spec 063 — orquestador streaming](../../specs/063-streaming-core/)
- [Spec 064 — tab BUCKET](../../specs/064-tui-bucket-tab/)
- [Spec 065 — heavy/light lanes en streaming](../../specs/065-streaming-heavy-light-lanes/)
- [ADR-006: heavy/light lanes](006-heavy-light-lanes.md)
- [Constitution — Principio IV (streaming over buffering)](../../.specify/memory/constitution.md)

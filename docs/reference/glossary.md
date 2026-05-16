> [← Volver al índice](../INDEX.md) · [Reference](README.md)

# Glossary

Vocabulario del proyecto. Si vas a leer el código o los docs internos, esto es lo que cada palabra significa adentro de CMCourier.

Entradas en orden alfabético. Si una entrada referencia otra, está linkeada con anchor.

---

### <a id="aimd"></a>AIMD
*Additive Increase, Multiplicative Decrease.* Algoritmo de auto-tune del pool de workers de S5. Crece de a `growth_factor` (default ×1.25) cuando p95 < target, y achica a `halve_factor` (default ×0.75) cuando p95 > `halve_threshold_ratio` × target. Implementado en `services/auto_tune.py`; recalibrado en spec 068.

### <a id="as400"></a>AS400
IBM i / iSeries. El host donde viven RVABREP, NIARVILOG y la mayoría de los sources de metadata del banco. CMCourier se conecta vía pyodbc + el "iSeries Access ODBC Driver". El driver no es thread-safe; cada thread usa su propia conexión (`thread-local`).

### <a id="batch"></a>batch
Una corrida lógica del pipeline. Una fila en `migration_batch` con un `batch_id`. Agrupa hasta `batch_size` (default 1000) documentos.

### <a id="batch_id"></a>batch_id
Identificador (string) del batch. Lo provee `--batch-id` o se autogenera. Indispensable para `--resume` y para `batch show`.

### <a id="bucket"></a>bucket
La cola acotada (`queue.Queue`) entre productores (prep) y consumidores (upload) en modo [streaming](#streaming-mode). Capacidad = `streaming.bucket_size` (default 100). Cuando está llena, prep bloquea; cuando está vacía, upload bloquea. Por eso la memoria pico escala sólo con `bucket_size`, independiente del total.

### <a id="chunk"></a>chunk
Una unidad de procesamiento dentro de [`MultiBatchOrchestrator`](#multibatchorchestrator). En `batched` mode con `batches_in_flight: 2`, mientras un chunk sube (S5), el siguiente prep (S0–S4) en paralelo. Cada chunk tiene su propio `MetricsRecorder` + `ChunkState`.

### <a id="cif"></a>CIF
*Clave / Código de Identificación de Cliente.* Identificador del cliente del banco. Aparece como columna del trigger CSV (default `CIF`) y se persiste en `migration_log.trigger_cif`.

### <a id="cmis"></a>CMIS
*Content Management Interoperability Services.* Protocolo HTTP estandarizado para repositorios de contenido. CMCourier sube vía el **Browser Binding** (multipart POST). Cliente: httpx con HTTP/2, circuit breaker, bandwidth limiter.

### <a id="cm"></a>CM (Content Manager)
*IBM Content Manager.* El destino de la migración. Sirve CMIS Browser Binding. Sus "object types" y "folders" los configura el operador en el [Modelo Documental](#mapping).

### <a id="doctor"></a>Doctor
Sub-comando de pre-flight (`cmcourier doctor`). Corre checks de conectividad (CMIS, AS400, log dir), de mapping (completeness), de metadata (sources), y de CM (types + folders + properties alignment). Por defecto se ejecuta antes de cada `*-pipeline run` salvo `--skip-doctor`.

### <a id="heavy-lane"></a>heavy lane
Una de las dos lanes del [LaneController](#lanesnapshot) (036). Aloja documentos con `file_size_bytes >= heavy_threshold_bytes` (default 10 MiB). Se activa con `heavy_light_lanes.enabled: true` + al menos `heavy_lane_min_batch` docs.

### <a id="idempotency"></a>idempotency
Garantía de que correr el mismo trigger dos veces NO produce dos uploads. La clave natural es `rvabrep_txn_num`. El check usa el partial index `idx_migration_log_uploaded ON migration_log (rvabrep_txn_num) WHERE status='S5_DONE'`. Si ya existe, la fila nueva pasa directo a [`S1_SKIPPED`](#s1-skipped).

### <a id="light-lane"></a>light lane
La contraparte de [heavy lane](#heavy-lane). Aloja documentos por debajo del threshold.

### <a id="multibatchorchestrator"></a>MultiBatchOrchestrator
Orchestrator del modo `batched`. Producer-consumer para N=2 chunks: mientras chunk K sube, chunk K+1 prep. Implementado en `orchestrators/multi_batch.py`.

### <a id="multipart"></a>multipart
El encoding HTTP que el Browser Binding de CMIS espera para uploads. CMCourier streamea el body (no carga el PDF entero en RAM).

### <a id="niarvilog"></a>NIARVILOG
Tabla AS400 (`RVILIB.NIARVILOG` por default) que coordina el estado del pipeline de forma distribuida (spec 034). Cuando `tracking.as400_sync.enabled: true`, S6 escribe ahí además del SQLite local.

### <a id="prep-workers"></a>prep workers
Thread pool fijo (size = `processing.prep_workers`, default 1) que paraleliza S2/S3/S4. S0 y S1 quedan seriales — cargan la lógica de idempotency cross-batch.

### <a id="processpool"></a>ProcessPool
`concurrent.futures.ProcessPoolExecutor` que usa S4 cuando `processing.s4_use_processes: true` (default). Esquiva el GIL para img2pdf / Pillow / PyPDF2 (066). Las excepciones cruzan el boundary vía `__reduce__`.

### <a id="rvi"></a>RVI (IBM RVI)
*Records Vault Imaging.* El sistema legacy del que migra CMCourier. Vive sobre AS400. RVABREP es su catálogo de documentos.

### <a id="rvabrep"></a>RVABREP
Tabla del [RVI](#rvi) que enumera los documentos: una fila por imagen/PDF, con metadatos como `ABAANB` (txn_num), `ABABCD` (shortname), `ABAACD` (system_id), `ABAHCD` (id_rvi), etc. CMCourier puede leerla de CSV o de AS400 (mismo shape, distinto storage).

### <a id="rvabrep-txn-num"></a>rvabrep_txn_num
La clave natural del documento (`ABAANB`). Es lo que hace única una fila de `migration_log` por batch, y lo que ancla la idempotency cross-batch.

### <a id="s0-s7"></a>S0–S7
Los stages del pipeline:
- **S0** Trigger acquisition.
- **S1** Indexing (query a RVABREP, cross-check de deletes).
- **S2** Mapping (id_rvi → CM type + folder).
- **S3** Metadata resolution (resolver propiedades con fallback chain).
- **S4** Assembly (validar archivos, TIFF→PDF, PDF passthrough).
- **S5** Upload (POST a CMIS Browser Binding, multipart, retry AIMD).
- **S6** Tracking (escribe SQLite + opcionalmente NIARVILOG).
- **S7** Idempotency marker (cross-batch dedup via `is_uploaded()` al arrancar S1 en la próxima corrida).

### <a id="s1-skipped"></a>S1_SKIPPED
Status terminal de la fila de `migration_log` cuando el documento ya tiene un `S5_DONE` en otro batch (idempotency cross-batch, spec 062).

### <a id="shortname"></a>ShortName
Identificador corto del cliente / contenedor del documento. Columna del trigger CSV (default `ShortName`) y de RVABREP (`ABABCD`). Se persiste en `migration_log.trigger_shortname`.

### <a id="systemid"></a>SystemID
Identificador del sistema origen del documento. Columna del trigger CSV (default `SystemID`) y de RVABREP (`ABAACD`). Se persiste en `migration_log.trigger_system_id`.

### <a id="staging"></a>staging
Ambiente intermedio entre dev y producción. CMCourier soporta dry-runs locales contra una pila Alfresco/file-server simulada — ver [How-to: local staging simulation](../how-to/local-staging-simulation.md).

### <a id="streaming-mode"></a>streaming mode
Modo de orquestación alternativo (`processing.mode: streaming`, spec 063). Productor (prep) y consumidor (upload) comunicados por un [bucket](#bucket) acotado. Pico de memoria = O(bucket_size). Rechaza `--from-stage > 1` y `--batch-id` (los resume se hacen como corrida nueva). Implementado en `orchestrators/streaming.py`.

### <a id="tui"></a>TUI
*Textual User Interface.* La interfaz live de Textual que muestra PREP / UPLOAD / CHUNKS / BUCKET / DETAIL. Refresh 250 ms. Ver [tui-keybindings.md](tui-keybindings.md).

### <a id="trigger"></a>trigger
Un `TriggerRecord` — el input lógico de S0. Cuatro `kind`s soportados: `csv`, `rvabrep`, `local_scan`, `single_doc`. Discriminados por la unión `TriggerConfigUnion` en `config/schema.py`.

## Ver también

- [`config-schema.md`](config-schema.md) — keys YAML mencionadas (`trigger.kind`, `processing.mode`, etc.).
- [`error-codes.md`](error-codes.md) — qué exception corresponde a qué stage.
- [`tracking-db-schema.md`](tracking-db-schema.md) — schema completo de los términos `migration_log`, `migration_batch`, `document_cache`.
- [Explanation: pipeline stages](../explanation/pipeline-stages.md) — los stages en prosa.

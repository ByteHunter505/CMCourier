# CMCourier

> Herramienta de migración de documentos para mover documentación bancaria desde el sistema legacy IBM RVI en AS400 hacia IBM Content Manager vía CMIS.

**Estado**: Bootstrap — la constitución y la arquitectura están ratificadas, la implementación del MVP aún no comenzó.

CMCourier es una reescritura completa de la antigua herramienta `RVIMigration`. La reescritura es **green-field en código** y **brown-field en dominio**: las reglas de negocio, las particularidades de integración, los formatos de archivo y las fuentes de datos están bien entendidos y documentados. La arquitectura y la disciplina de ingeniería arrancan de cero bajo diseño hexagonal y Spec-Driven Development.

---

## Qué contiene este repositorio en este momento

```
CMCourier/
├── .specify/
│   └── memory/
│       └── constitution.md          # Ley de ingeniería ratificada (v1.0.0)
│
├── docs/
│   ├── domain/                     # Verdad de dominio (1300+ líneas)
│   ├── roadmap/
│   │   └── POST-MVP.md              # Todo lo diferido más allá del MVP
│   └── samples/
│       ├── csv/                     # CSVs de referencia del proyecto viejo
│       ├── excel/                   # Volcado de la tabla RVABREP (xlsx)
│       └── responses/               # Fixture real de respuesta CMIS
│
├── README.md                        # Este archivo
├── CHANGELOG.md                     # Historia del proyecto (formato Keep a Changelog)
└── CONTRIBUTING.md                  # Flujo SDD, estándares de commit, reglas de PR
```

Todavía no hay código fuente. El esqueleto (`src/cmcourier/`, `tests/`, `pyproject.toml`, etc.) aterriza con el primer cambio de implementación.

---

## Mapa de documentación

El punto de entrada canónico es **[`docs/INDEX.md`](docs/INDEX.md)** — una sola página que mapea todos los artefactos de documentación del repo. Abajo hay un cheat sheet de acceso rápido para las lecturas más comunes.

| Documento | Cuándo leer | Propósito |
|----------|-----------|---------|
| [`docs/INDEX.md`](docs/INDEX.md) | **En cualquier momento** | Mapa canónico de toda la documentación, organizado por propósito (inspirado en Diátaxis) |
| [`README.md`](README.md) | Primero | Qué es el proyecto, estado actual, dónde buscar qué |
| [`.specify/memory/constitution.md`](.specify/memory/constitution.md) | Antes de escribir cualquier cosa | Los 9 principios inmutables de ingeniería. Specs, diseño y código que los viole son rechazados |
| La spec de dominio del proyecto en `docs/domain/` | Antes de escribir algo relacionado al dominio | El contexto de dominio completo: sistema origen (RVI/AS400), sistema destino (CMIS/Content Manager), formatos de archivo, resolución de metadatos, particularidades de la integración CMIS, arquitectura de stages |
| [`docs/roadmap/POST-MVP.md`](docs/roadmap/POST-MVP.md) | Cuando preguntás "¿nos olvidamos de X?" | Toda funcionalidad diferida más allá del MVP, con intención + diseño + criterios de aceptación |
| [`docs/how-to/README.md`](docs/how-to/README.md) | Cuando necesitás *hacer* algo | Índice de recetas (orientado a problemas). Vacío al inicio del MVP; crece a medida que se shippean comandos |
| [`docs/explanation/README.md`](docs/explanation/README.md) | Cuando necesitás *entender* algo | Índice de explicaciones (orientado a entendimiento). Acompaña a la explicación canónica de dominio |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Antes de abrir un PR | Flujo SDD, reglas de commit, estándares de PR |
| [`CHANGELOG.md`](CHANGELOG.md) | En cualquier momento | Historial versionado de cada cambio significativo en el proyecto |

---

## Qué va a hacer CMCourier

De punta a punta:

1. **Descubrir** documentos a migrar a través de una de varias fuentes trigger (CSV, query AS400, filtro RVABREP, scan de carpeta local).
2. **Indexar** cada trigger contra la tabla maestra RVABREP en AS400.
3. **Mapear** el código de tipo RVI de cada documento a una clase documental de Content Manager (carpeta + tipo de objeto + campos de metadatos requeridos).
4. **Resolver** metadatos para cada documento vía una cadena de fallback configurable sobre múltiples fuentes.
5. **Ensamblar** el PDF final (fusionar TIFFs multi-página en un PDF único, o passthrough de PDFs nativos).
6. **Subir** a Content Manager vía la API REST CMIS Browser Binding con los metadatos correspondientes.
7. **Trackear** cada documento para que las re-corridas sean idempotentes.

El diseño completo está descrito en la spec de dominio del proyecto en `docs/domain/`.

---

## Arquitectura en un párrafo

**Arquitectura Hexagonal (Ports & Adapters)** con cuatro capas: `domain` (Python puro, sin dependencias externas), `services` (lógica de negocio que depende solo de ports), `orchestrators` (coordinadores delgados), `adapters` (implementaciones concretas de ports — pyodbc para AS400, requests para CMIS, pandas para CSV, SQLite para tracking, img2pdf/Pillow para ensamblado de PDFs). Las pipelines son **composiciones nombradas de stages atómicos** (`S0`–`S7`), cada pipeline es un comando CLI, nunca un flag de config.

Ver el Principio Constitucional I y la spec de dominio del proyecto para más detalle.

---

## Tech stack

Definido por la Constitución. Cualquier sustitución requiere enmienda constitucional.

- **Lenguaje**: Python 3.11+
- **Config**: Pydantic v2 (validado en startup)
- **CLI**: Click
- **AS400**: pyodbc + iSeries Access ODBC Driver (conexiones thread-local)
- **HTTP**: requests + requests-toolbelt (`MultipartEncoder` para uploads streaming)
- **CSV**: pandas
- **Ensamblado de PDF**: img2pdf (fast path) + Pillow + PyPDF2 (fallback)
- **Tracking**: SQLite (modo WAL), alternativa AS400 (post-MVP)
- **Testing**: pytest + pytest-cov
- **Lint / format**: ruff
- **Type check**: mypy (strict sobre `domain/`, `services/`, `orchestrators/`)
- **Packaging**: pyproject.toml (PEP 621)

---

## Cómo empezar

### Prerrequisitos

- **Python 3.11 o más nuevo** (CMCourier está verificado en 3.11 y 3.12).
- **Un compilador de C y los headers ODBC** — requeridos por `pyodbc`:
  - **Linux** (Debian/Ubuntu): `sudo apt install build-essential unixodbc-dev`
  - **macOS**: `brew install unixodbc`
  - **Windows**: instalá el [IBM iSeries Access ODBC Driver](https://www.ibm.com/support/pages/ibm-i-access-client-solutions) (el driver ya trae su propio SDK).
- **Git**.

### Instalar (editable, con herramientas de desarrollo)

```bash
git clone <repo> CMCourier
cd CMCourier
python3 -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate            # Windows
pip install -e .[dev]
pre-commit install
pre-commit install --hook-type commit-msg
```

### Correr el smoke test

```bash
pytest                             # todos los tests
pytest -m unit                     # solo tests unitarios
pytest -m integration              # solo tests de integración
pytest -m "not slow"               # saltear tests lentos
```

### Lint, format, type-check

```bash
ruff check src/ tests/             # lint
ruff format src/ tests/            # auto-format
ruff format --check src/ tests/    # chequeo estilo CI (no escribe)
mypy src/cmcourier/                # type-check (strict en capas internas)
```

### Bypass de pre-commit hook

No se hace bypass de los pre-commit hooks. Si un hook falla, arreglá la causa y creá un nuevo commit. Nunca `--no-verify` (Constitución / Git Safety Protocol).

### Variables de entorno requeridas (cuando se corren migraciones reales)

Las credenciales viven en el entorno, nunca en YAML commiteado (Principios Constitucionales V y VIII):

```bash
export AS400_USERNAME="..."
export AS400_PASSWORD="..."
export CMIS_USERNAME="..."
export CMIS_PASSWORD="..."
```

Un `config/config.yaml` real y un comando CLI funcional aterrizan en cambios subsiguientes. Por ahora, la CLI imprime su mensaje de ayuda:

```bash
cmcourier --help
```

Para la arquitectura, el contexto de dominio y el roadmap: leé [docs/INDEX.md](docs/INDEX.md). Primero viene el entendimiento; el código después (Principio Constitucional IX).

---

## Flujo del proyecto

CMCourier sigue **Spec-Driven Development** bajo las convenciones de GitHub Spec Kit. En resumen:

```
Constitución (filtro inmutable)
        ↓
Especificación (el qué — requisitos, escenarios, criterios de aceptación)
        ↓
Plan / Diseño (el cómo — arquitectura, librerías, descomposición)
        ↓
Tareas (el checklist de implementación)
        ↓
Código (implementar contra la spec)
        ↓
Verificar (validar contra constitución + spec)
```

No aterriza código sin spec. Ninguna spec contradice a la constitución. Ver [`CONTRIBUTING.md`](CONTRIBUTING.md) para el flujo completo.

---

## Checklist de estado

- [x] Constitución ratificada (v1.0.0)
- [x] Estructura del proyecto definida
- [x] Verdad de dominio documentada (en `docs/domain/`)
- [x] Arquitectura de pipeline basada en stages definida
- [x] Validación pre-flight definida
- [x] Niveles de observabilidad definidos
- [x] Roadmap post-MVP capturado
- [x] Contexto SDD registrado (`/sdd-init`)
- [x] Primer cambio: bootstrap del esqueleto Python
- [x] Segundo cambio: modelos de dominio, ports, excepciones
- [x] Tercer cambio: primer adapter concreto (Data Source tabular CSV+XLSX)
- [x] Cuarto cambio: primer service (MappingService sobre Modelo Documental)
- [x] Quinto cambio: MetadataService (cadena de fallback + auto-curación de CIF)
- [x] Sexto cambio: estrategias trigger S0 (CSV + direct_rvabrep + stubs)
- [x] Séptimo cambio: tracking store SQLite (idempotencia + estado por stage)
- [x] Octavo cambio: IndexingService (S1 — lookup RVABREP)
- [x] Noveno cambio: PdfAssembler (S4 — img2pdf + fallback Pillow/PyPDF2)
- [x] Décimo cambio: CmisUploader (S5 — CMIS Browser Binding + política de retry + limitador de bandwidth)
- [x] Undécimo cambio: orquestador CsvTriggerPipeline (S0..S6 de punta a punta, librería) — **pipeline MVP completa**
- [x] Decimosegundo cambio: CLI + config Pydantic + loader YAML — **CLI MVP usable de punta a punta**
- [x] Decimotercer cambio: pre-flight `cmcourier doctor`
- [x] Decimocuarto cambio: adapter AS400 + rvabrep-pipeline + as400-trigger-pipeline — **multi-pipeline + AS400 listo para producción**
- [x] Decimoquinto cambio: fuentes de metadatos AS400 (cierra el gap de 014)
- [x] Decimosexto cambio: local-scan-pipeline (4ª pipeline productiva; set de modos trigger completo)
- [x] Decimoséptimo cambio: single-doc-pipeline (diagnóstica — one-shot dirigida por CLI)
- [x] Decimoctavo cambio: override de query AS400 por fuente (cierra el gap de escala de 015)
- [x] Decimonoveno cambio: limpieza de higiene de port en adapters (cada adapter ahora declara su port)
- [x] Vigésimo cambio: niveles de observabilidad 1-4 — JSON app log + pipeline + network + slow-ops
- [x] Vigésimo primer cambio: esenciales de CLI para operador — batch list/show/retry-failed + inspect rvabrep/mapping + as400-query
- [x] Vigésimo segundo cambio: flags de seguridad de pipeline — auto-doctor + --resume + doctor --check
- [x] Vigésimo tercer cambio: menús CLI de operador completos — inspect trigger / mapping-stats + batch export-report
- [x] Vigésimo cuarto cambio: background runner — punto de entrada cron-friendly con lock fcntl por config
- [x] Vigésimo quinto cambio: TUI live de dos tabs + worker pool S5 + auto-tune AIMD
- [x] Vigésimo sexto cambio: métricas de sistema nivel 5 (POST-MVP §2 — sampleo psutil, costo ~0.1% CPU)
- [x] Vigésimo séptimo cambio: analizador de logs offline `cmcourier analyze batch/compare/trends` (POST-MVP §3)
- [x] Vigésimo octavo cambio: orquestador multi-batch con overlap producer-consumer N=2 (POST-MVP §7, N=2)
- [x] Vigésimo noveno cambio: `BandwidthLimiter` compartido con token bucket — `cmis.max_bandwidth_mbps` ahora es el verdadero tope global
- [x] Trigésimo cambio: vista multi-batch en TUI — nueva tab `CHUNKS` + binding del recorder live
- [x] Trigésimo segundo cambio: auto-completion de shell (`cmcourier completion bash|zsh|fish`)
- [x] Trigésimo tercer cambio: polish de Tier 1 — flag `--total <N>` + docs de integración CI para `analyze`
- [x] Trigésimo cuarto cambio: idempotencia distribuida AS400 NIARVILOG (POST-MVP §4 — toggleable, retry/backoff, CLI `cmcourier sync resolve`)
- [x] Trigésimo quinto cambio: split de CSV de mapping (`MapeoRVI_CM.csv` + `MetadatosCM.csv` + columna `CMISType` — formato de producción; el modo consolidado queda para tests)
- [x] Trigésimo sexto cambio: lanes adaptativos heavy/light para upload (POST-MVP §1 — default off, `LaneSplitter` + `LaneController` + rebalance dirigido por drain + sub-paneles TUI duales)
- [x] Trigésimo séptimo cambio: tabla cross-batch `document_cache` (POST-MVP §9 — default off, respaldada en SQLite, consciente del TTL, CLI `cmcourier cache stats|clear`)
- [x] Trigésimo octavo cambio: sizing del CMIS connection pool + warm-up eager (POST-MVP §10.2 — `HTTPAdapter pool_maxsize`, `warm_connection_pool(n)` pre-S5)
- [x] Trigésimo noveno cambio: override de `object_type_id` CMIS (vía `mapping.cmis_type`) + scaffolding de dry-run de staging (Alfresco-en-Docker + runbooks)
- [x] Cuadragésimo cambio (038): pre-flight de destino CMIS + trace de payload de upload — columnas `CMISFolder` + `CMISPropertyId`; `doctor --check cm-targets` (folders + properties); `IUploader.verify_folder_exists` (read-only); eventos `s5_upload_attempt` / `s5_upload_failed` con enmascaramiento de PII + toggle `observability.unmask_pii`
- [x] Cuadragésimo primer cambio (039): generador sintético de CSV RVABREP — `cmcourier mock rvabrep` streamea un CSV determinista por semilla a cualquier escala (encadena en `mock generate` para materialización de archivos)
- [x] Cuadragésimo segundo cambio (040): compatibilidad CMIS Alfresco — semántica `repo_id=""` + heurística de propiedad mime + allowlist del formatter JSON + override `cmis_type` en doctor; smoke en vivo contra Alfresco 23.x shippea con 0 failures de punta a punta
- [x] Cuadragésimo tercer cambio (041): pase de quality-of-life en TUI — dashboard limpio (el handler de stderr se desconecta cuando Textual posee la terminal), la tab UPLOAD agrega MB-subidos/MB-planificados + wall-clock por chunk + MB/s promedio + ETA, la tab CHUNKS se convierte en una tabla de breakdown por stage con fila agregada TOTAL
- [x] Cuadragésimo cuarto cambio (042): aislamiento de métricas multi-batch en TUI — filtro `_BandwidthHandler` por batch (no más bleed de bytes entre chunks superpuestos), `s5_done`/`s5_failed` en vivo propagados a la fila CHUNKS durante UPLOAD (no más `0/0/0` colgado), slot `upload_recorder()` separado en `MultiBatchOrchestrator` para que los percentiles S5 de la tab UPLOAD no se vean perturbados por flips de recorder del lado PREP
- [x] Cuadragésimo quinto cambio (043): el auto-tune AIMD ve el p95 real en modo multi-batch — swap hook `AutoTuneController.set_p95_provider` + el orquestador cablea el recorder de upload activo para restaurar la propiedad de protección elástica (pre-043 el controller observaba `p95=0` siempre y solo crecía workers, nunca decrecía)
- [x] Cuadragésimo sexto cambio (044): resume robusto tras kill -9 en medio de S5 — `_apply_resume` detecta gaps de stage `S{N}_DONE → S{N+1}` (workers pausados a mitad de batch ya no se abandonan como "limpios"), `--batch-id` siempre se propaga (batches con nombre de operador respetados sin `--resume`), `--from-stage` explícito gana sobre la auto-detección
- [x] Cuadragésimo séptimo cambio (045): upload S5 idempotente ante conflicto 409 — `CmisUploader.upload` recupera de huérfanos por kill-race (doc en Alfresco, ausente de migration_log) consultando el `cmis:objectId` existente vía el endpoint folder-children; cierra la última ventana `S5_FAILED` tras un `kill -9` real
- [x] Cuadragésimo octavo cambio (046): modelo `Trigger` polimórfico — cada pipeline emite su forma natural de trigger (`ClientTrigger` para csv / single-doc / as400, `RvabrepRowTrigger` para rvabrep-direct, `LocalScanTrigger` para local-scan); S1 dispatchea por subtipo, así que local-scan ahora sube exactamente los archivos del pool de scan (no más sobre-expansión "1 archivo → todos los docs del cliente")
- [x] Cuadragésimo noveno cambio (047): persiste `cm_object_id` en `S5_DONE` — `mark_stage_done` ahora escribe el objectId de CMIS en `migration_log` para que la DB de tracking pueda responder "¿cuál es el objectId del doc X?" sin un children-walk contra CMIS
- [x] Quincuagésimo cambio (048): fuente RVABREP pluggable — `indexing.source` se vuelve un union discriminado (`kind: csv` ↔ `kind: as400`); `rvabrep-pipeline` sirve ambos (archivo CSV vs. query AS400 en vivo devolviendo una tabla con forma RVABREP), el comando independiente `as400-trigger-pipeline` y `trigger.kind: as400` se eliminan (AS400 es una elección de *fuente*, no un tipo de trigger)
- [x] Quincuagésimo primer cambio (049): nombres de columna NIARVILOG configurables — `tracking.as400_sync.columns` mapea los 15 campos lógicos de NIARVILOG a nombres físicos por entorno (simétrico con `indexing.columns`); todos los identificadores configurables (`columns.*`, `library`, `table`) ahora se validan como identificadores DB2, cerrando la superficie de interpolación SQL
- [x] Quincuagésimo segundo cambio (050): pipeline trigger en streaming — los triggers streamean en chunks de `batch_size` en lugar de materializarse enteros; el pico de memoria es `O(batch_size × batches_in_flight)` no `O(total)`, así que la migración productiva del RVABREP de ~20M filas ya no hace OOM (derrotó cuatro puntos de materialización: el `list()` de `_run_overlapped`, el path monolítico N=1, `TabularDataSource.get_all`, y `--total`)
- [x] Quincuagésimo tercer cambio (051): "filtrado en S1" es un resultado de primera clase — las filas RVABREP con código de borrado se dropeaban silenciosamente en S1 sin trazabilidad; ahora `_enrich_known_row` levanta `RVABREPDeletedError`, `_stage_s0_s1` lo cuenta como `filtered` (no failed, no silent drop) con un log por doc, y `s1_filtered` aparece en el resumen headless + tabs PREP/CHUNKS del TUI
- [x] Quincuagésimo cuarto cambio (052): tab CHUNKS — rates en vivo, timer congelado, drill-down — columna `MB/s·docs/s` de throughput por chunk; el timer del run ahora se congela al completar en lugar de contar para siempre; una nueva tab DETAIL (cursor de chunk `[` / `]`, `d` para ver) lista cada doc de un chunk (nombre/size/estado/razón), leída on demand desde el tracking store así la memoria queda acotada
- [x] Quincuagésimo quinto cambio (053): clasificador de bottleneck consciente de stages — `cmcourier analyze batch` ahora lidera con el breakdown por stage (la señal exacta por batch que antes ignoraba): una stage que retiene ≥45% del tiempo total de stage *es* el bottleneck, y el veredicto nombra si está DENTRO del programa (`assembly/metadata/mapping/indexing/trigger-bound`) o FUERA de él (`upload-bound` — el servidor CMIS + la red); `LogReader` asocia los niveles sin tag `network-*`/`system-*` por la ventana temporal del batch en lugar de un `batch_id` ausente, así que `network_summary`/`system_summary` ya no están siempre vacíos
- [x] Quincuagésimo sexto cambio (054): cableado del recorder de la tab UPLOAD — termina el split PREP/UPLOAD del recorder de 042: `bandwidth_current/peak/series` + `slow_ops_all` ahora leen el recorder lado UPLOAD (pre-054 leían el recorder PREP, que en runs N=2 no ve ninguno de los eventos `cmis_upload` del chunk subiendo → 0 bandwidth, sparkline en blanco, sin slow ops); el timer de UPLOAD por chunk mide desde `upload_started_monotonic` (inicio de S5) en vez de `prep_started_monotonic`, así "chunk elapsed" y `avg_mbps` reflejan la ventana real de upload
- [x] Quincuagésimo séptimo cambio (055): los eventos de network llevan el `batch_id` — causa raíz detrás de la tab UPLOAD muerta: `CmisUploader._emit_network` nunca seteaba `batch_id`, así que el `_BandwidthHandler` / `_SlowOpHandler` por-batch (que filtran por él) silenciosamente dropeaban *todos* los eventos `cmis_upload` en *todos* los recorders desde la spec 042; `IUploader.upload` ahora toma un keyword `batch_id` requerido y lo enhebra a través de `_post_with_retries` → `_emit_network` (+ los eventos diagnósticos `s5_upload_attempt`/`s5_upload_failed`), así bandwidth/peak/sparkline/slow-ops finalmente reciben datos
- [x] Quincuagésimo octavo cambio (056): workers de prep configurables — `processing.prep_workers` dimensiona un `ThreadPoolExecutor` fijo para los stages de prep S2 (mapping), S3 (metadata) y S4 (assembly), que corrían un documento por vez en un único thread; default `1` es byte-idéntico a antes, `pool.map` mantiene la lista de sobrevivientes en orden de entrada, y S0/S1 quedan seriales por diseño (cargan la lógica de idempotencia cross-batch + resume). Sin AIMD/lanes/maquinaria de bandwidth — solo un thread count
- [x] Quincuagésimo noveno cambio (057): dimensionar el thread pool de S5 al techo AIMD — el `ThreadPoolExecutor` de upload se creaba con `max_workers=cmis.workers` (fijo), así que el `ResizableSemaphore` redimensionado por AIMD nunca podía exceder el conteo inicial: `pool_in_use` quedaba clavado en `cmis.workers` mientras la capacidad del TUI subía, y la perilla auto-tune estaba desconectada del motor; el pool (tanto `_stage_5_single` como el par dual heavy/light) ahora se dimensiona a `_pool_ceiling()` = `auto_tune.max_threads`, así el semáforo/lane controller se vuelve el limitador efectivo — sin cambio cuando AIMD está apagado
- [x] Sexagésimo cambio (058): fixes de tab DETAIL — (a) la columna `size` por doc siempre leía `—` porque `file_size_bytes` nunca se persistía: la fila se INSERT-OR-IGNORE'aba primero en S1 (cuando `item.staged_file` aún era `None`) y el INSERT de S4 se ignoraba silenciosamente, así que la columna quedaba NULL para siempre; un nuevo `ITrackingStore.record_staged_file_metadata` UPDATEa la fila después de que S4 ensambla, idempotente para que los runs de resume también la rellenen; (b) el panel DETAIL estaba envuelto en un `Container` plano que recorta overflow en vez de scrollear — ahora un `VerticalScroll` con `#detail_body { height: auto }` y `_MAX_ROWS` elevado a 2000, así chunks más grandes que la altura visible se leen más allá del fold
- [x] Sexagésimo primer cambio (060): cliente HTTP migrado de `requests` a `httpx[http2]` — `CmisUploader` ahora negocia HTTP/2 vía ALPN, así los N workers S5 concurrentes comparten una sola conexión TCP (Alfresco con frontend Apache en prod), bajando overhead de uploads chicos; fallback transparente a HTTP/1.1 cuando el servidor no anuncia h2 (Tomcat-directo en staging), así el comportamiento allí no cambia; 56 tests de integración del adapter migrados de `responses` a `respx`
- [x] Sexagésimo segundo cambio (061): guardia AIMD `min_samples` — el controller halvea el worker pool unos segundos en el primer chunk porque el p95 por rango más cercano con ~5 muestras estaba dominado por un único outlier de conexión fría; nueva config `cmis.auto_tune.min_samples` (default 20) short-circuita la decisión a una nueva acción `insufficient_data` cuando se acumularon pocas muestras, dejando workers/timeout intactos hasta que la observación sea confiable
- [x] Sexagésimo tercer cambio (062): persiste docs filtrados/skipeados cross-batch en S1 a `migration_log` — dos nuevos valores de `StageStatus` (`S1_FILTERED`, `S1_SKIPPED`) + un método de port `mark_stage_terminal`, así la tab DETAIL / `analyze batch` / `cmcourier batch show` pueden identificar qué docs específicos fueron filtrados (con código de borrado en origen, spec 051) o skipeados cross-batch (idempotencia); el contrato anterior de "skip silencioso" revertido intencionalmente por trazabilidad
- [x] Sexagésimo cuarto cambio (063): orquestador streaming (core, single-lane) — nuevo `processing.mode: "batched" | "streaming"` selecciona el orquestador; `"streaming"` corre un pipeline producer-consumer continuo manejado por un **bucket** acotado (`processing.streaming.bucket_size`, default 100) entre PREP (productores S1–S4, dimensionados por `prep_workers`) y consumidores S5 (dimensionados a `_pool_ceiling()`). El pico de memoria colapsa a `bucket_size` (independiente del conteo total de triggers) y S5 nunca queda idle esperando el PREP de un chunk. Resume queda rechazado en modo streaming — re-ejecutar + las filas `S1_SKIPPED` de 062 dan trazabilidad. Lanes heavy/light (036) y una tab BUCKET TUI real quedan diferidas a 065 / 064
- [x] Sexagésimo quinto cambio (064): tab BUCKET en TUI para modo streaming — nuevo keybind `b` abre una tab dedicada que muestra el nivel del bucket vs cap (barra ASCII), nivel peak desde el inicio del run, throughput de ventana deslizante de 5s en PREP + S5, conteo de productores in-flight, totales de workers configurados, y acumulados `S5_DONE` / `S5_FAILED` / `S1_FILTERED` / `S1_SKIPPED`. El orquestador expone un reader `streaming_snapshot()` y un `_ThroughputWindow` (deque+lock) alimenta las tasas. El modo batched no cambia — la tab BUCKET imprime un stub de una línea apuntando a CHUNKS
- [x] Sexagésimo sexto cambio (065): lanes heavy/light en modo streaming — combinar `processing.mode: "streaming"` con `heavy_light_lanes.enabled: true` ahora inserta un thread dispatcher entre el bucket principal y S5: rutea cada item a una cola heavy o light por-lane según `staged_file.size_bytes >= heavy_threshold_bytes`, y cada lane recibe su propio consumer pool gateado por el `LaneController` existente (split de semáforos + rebalance dirigido por drain de 036). La tab BUCKET gana un sub-bloque LANES mostrando budget heavy/light, busy, profundidad de cola, y budget total. Elimina el head-of-line blocking causado por un único doc heavy hambriendo a los más livianos encolados detrás
- [x] Sexagésimo séptimo cambio (066): ensamblado PDF S4 en `ProcessPoolExecutor` — diagnosticado `prep_workers: 16` corriendo a < 5 docs/s agregado porque el GIL serializa el trabajo de `img2pdf`/`PIL`/`PyPDF2`. Nuevo default-on `processing.s4_use_processes: true` dispatchea `assemble()` a un process pool dimensionado por `s4_max_processes` (default `os.cpu_count()`), saltando el GIL completamente. Contexto `spawn` (no `fork`) evita el riesgo de deadlock de un padre multi-thread. `SourceFileMissingError` / `PDFAssemblyFailedError` recibieron `__reduce__` para que crucen limpiamente el borde de worker. Esperar speedup ~Nx para runs dominados por S4
- [x] Sexagésimo octavo cambio (067): fixes de bugs en TUI de modo streaming — cuatro bugs reportados en la primera corrida de streaming de punta a punta: barra de tab UPLOAD clavada en `count/count` (sin `pool_stats.queue_depth` publicado), timer de chunk + velocidad promedio en 0 (chunk sintético hard-coded `status="PREP"` para todo el run), tab CHUNKS congelada en 0 (contadores live seteados solo al fin del run), contador de cola LANES monotónico-creciente excediendo `bucket_size` (contador privado en vez de `qsize()`). Los cuatro fixes adentro de `streaming.py`: `pool_stats.set_queue_depth(...)` live por put/get, chunk sintético sembrado `status="UPLOAD"` + stamps monotónicos al inicio del run, nuevo `_publish_chunk_state` llamado después de cada outcome S5, y `lane_queue.qsize()` reportado al `LaneController` en lugar de un contador monotónico (también re-habilita la heurística de rebalance dirigido por drain, que nunca disparaba pre-067)
- [x] Sexagésimo noveno cambio (068): crecimiento agresivo de AIMD + halve suave — diagnosticado peak `<20 MB/s` contra un link de 300 Mbps porque la `capacidad del pool` quedaba en 4-8: AIMD crecía `+1` por tick de 15s (44 ticks para llegar a 50) mientras que un único outlier de p95 de 40s en un upload de 30 MB halveaba el pool a /2. Tres nuevas perillas tuneables en `cmis.auto_tune`: `growth_factor` (default 1.25 → crecimiento multiplicativo, piso +1), `halve_factor` (default 0.75 → halve suave), `halve_threshold_ratio` (default 1.5 → halvear a 1.5× target en vez de 1.2×). La capacidad ahora alcanza el techo en ~2.5 min y sobrevive a la varianza natural de p95 con archivos pesados
- [x] Septuagésimo cambio (069): el sampler de bandwidth distribuye bytes sobre la ventana real de transmisión — diagnosticado el TUI flipeando entre `current 11 MB/s` y `0 MB/s` porque `_BandwidthSampler.record_upload` acreditaba todo el tamaño del archivo al segundo de completion. Para un upload de 30 MB / 3 s todos los bytes caían en un bucket y cero en los otros dos. Nueva firma `(size, *, started_at, completed_at)` distribuye uniformemente entre los buckets que la transmisión abarcó; el `_BandwidthHandler` deriva `started_at` del `duration_ms` ya transportado en el log record `cmis_upload`. `current_mbps`, `peak_mbps`, y la sparkline ahora reflejan throughput sostenido en vez de aliasing de completion
- [x] Septuagésimo primer cambio (070): unificar el LaneController entre streaming + batched — diagnosticado el LANES `queue 0` de la tab UPLOAD (y la tab BUCKET LANES mostrando el valor correcto): había dos instancias `LaneController` cuando las configs de ambos modos tenían `heavy_light_lanes.enabled: true`. El `StreamingOrchestrator` (065) construía la propia, el `StagedPipeline` (036) construía otra, y el TUI leía la del pipeline (idle). También rompía silenciosamente el direccionamiento de budget por-lane de AIMD. Ahora el orquestador streaming reusa `pipeline.lane_controller` vía una property read-through — una instancia por run, todos los flujos de datos le pegan
- [x] MVP: `rvabrep-pipeline` de punta a punta
- [ ] Dry run con datos reales contra staging
- [ ] Primera migración productiva

---

## Licencia

Por definir por el dueño del proyecto. Hasta entonces, tratá este repositorio como propietario; no distribuir sin permiso.

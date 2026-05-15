# 066 — Armado de PDF de S4 en un ProcessPoolExecutor (paralelismo real)

## Por qué

Diagnosticado durante un run de staging de streaming de 5000
docs (`config-staging-rvabrep-streaming.yaml`):

* `processing.prep_workers: 16` configurado
* El tab BUCKET mostraba `PREP 16 in-flight` (contador
  correcto)
* El nivel del BUCKET quedaba cerca de 0 — S5 siempre más
  rápido que PREP
* Throughput del PREP: **< 5 docs/s** a pesar de los 16
  threads producer

Diagnóstico: S4 (armado de PDF vía `img2pdf` + `PIL` +
`PyPDF2`) es CPU-bound. El **GIL serializa la ejecución de
bytecode de Python**, así que múltiples threads corriendo
`PdfAssembler.assemble()` se ejecutan de a uno a la vez en
el límite de C-extension. El paralelismo de 16 threads es
real en términos de *threads existiendo adentro de
`streaming_prep_one`*, pero el throughput agregado es
~equivalente a un único worker.

Los stages anteriores del prep (indexing S1, mapping S2,
metadata S3) son todos dict-lookup-in-memory — paralelizan
bien con threading porque pasan la mayoría del tiempo en
operaciones de pandas / dict a nivel C que liberan el GIL.
Solo S4 es el cuello de botella.

## Qué

### 1. `ProcessPoolExecutor` solo para S4

Un pool de `N` procesos worker corre
`PdfAssembler.assemble()` para cada invocación de S4. El
thread producer en `StreamingOrchestrator` llama:

```python
staged = self._s4_pool.submit(_pool_assemble, document).result()
```

El thread bloquea esperando el resultado, pero **libera el
GIL durante la espera** — así otros threads producer pueden
ejecutar trabajo de S1/S2/S3 en paralelo. Mientras tanto,
los N procesos worker cada uno tienen su propio intérprete
Python y ejecutan `assemble()` con paralelismo real a nivel
OS.

### 2. Helpers de pool a nivel módulo (picklability)

```python
# en cmcourier.adapters.assembly.pool

_worker_assembler: PdfAssembler | None = None

def _pool_init(config: AssemblerConfig) -> None:
    global _worker_assembler
    _worker_assembler = PdfAssembler(config)

def _pool_assemble(document: RVABREPDocument) -> StagedFile:
    assert _worker_assembler is not None
    return _worker_assembler.assemble(document)
```

El pool se construye una vez en la capa de wiring con
`initializer=_pool_init, initargs=(assembler_config,)`.
Cada worker reconstruye el assembler en su propio proceso.

### 3. Config

```yaml
processing:
  # 066: cuando true, el armado de S4 corre en un ProcessPoolExecutor
  # con `s4_max_processes` workers (default = os.cpu_count()).
  # Cuando false, S4 corre sincrónico adentro del thread producer
  # (comportamiento 063/064/065).
  s4_use_processes: true  # NUEVO DEFAULT — opt-out para byte-idéntico-a-pre-066
  s4_max_processes: null  # null → os.cpu_count(); sino int explícito
```

### 4. Lifecycle

* **Construcción**: la capa de wiring crea el pool cuando
  `s4_use_processes=true`. Lo pasa a
  `StagedPipeline.__init__`.
* **Uso**: `_s4_one` chequea presencia del pool y despacha
  a `pool.submit(...).result()` en vez de llamar a
  `_assembler.assemble` directo.
* **Shutdown**: la capa de wiring (o el `close()` del
  pipeline) llama `pool.shutdown(wait=True)` después de
  que el run completa.

### 5. Requerimientos de picklability

* `RVABREPDocument` — ya un `@dataclass(frozen=True)` —
  picklable.
* `AssemblerConfig` — ya un dataclass — picklable.
* `StagedFile` — ya un dataclass — picklable.

Sin trabajo nuevo de picklability necesario.

## Fuera de alcance

* S2 y S3 en process pool — son trabajo
  dict-lookup-in-memory, picklecost > computecost.
  Dejarlos en threads.
* S1 (indexing) — mismo razonamiento.
* S5 (upload) — ya paralelizado vía httpx + ThreadPool,
  network-bound así que sin presión del GIL.
* Matiz cross-platform fork vs spawn —
  `ProcessPoolExecutor` default al método preferido de la
  plataforma; no lo overrideamos.
* Logging desde los procesos worker — los workers corren
  silenciosos para 066; cualquier mensaje de log desde
  adentro de `assemble()` se pierde. Una spec de follow-up
  puede wirear un `QueueHandler` si los operadores
  necesitan logs de diagnóstico.

## Criterios de aceptación

* `processing.s4_use_processes` default a `true`.
  Setearlo a `false` restaura el comportamiento
  063/064/065 byte-idénticamente (sin pool creado, S4
  corre en thread producer).
* `processing.s4_max_processes` default a `None` (=
  `os.cpu_count()`). `int` explícito overridea.
* `StagedPipeline` acepta un
  `s4_process_pool: ProcessPoolExecutor | None` opcional.
  Cuando seteado, `_s4_one` despacha al pool.
* `cmcourier.adapters.assembly.pool` expone `_pool_init` y
  `_pool_assemble` a nivel módulo (importable /
  picklable).
* La capa de wiring construye el pool cuando está
  configurado y lo shutdownea en close del pipeline.
* Todos los tests existentes pasan. Tests nuevos:
  * Unit: las funciones helper del pool son picklables.
  * Unit: `_s4_one` despacha al pool cuando está
    presente.
  * Unit: `_s4_one` hace fallback a assembly directo
    cuando el pool es None.
  * Integration: un run streaming de 6 docs con
    `s4_use_processes=true` produce el mismo conteo
    `S5_DONE` que sin él.
* mypy + ruff limpios.
* CHANGELOG `[0.68.0]`; pyproject 0.67.0 → 0.68.0.

## Notas sobre impacto esperado

* Latencia de S4 per-doc: aproximadamente la misma
  (ligeramente más alta por overhead de pickle + IPC de
  ~1-5ms por doc).
* Throughput agregado del PREP: debería escalar con
  `s4_max_processes` para cargas CPU-bound. Con
  `os.cpu_count() = 8`, esperar ~8x speedup sobre S4
  single-thread para PDFs grandes.
* Memoria: cada proceso worker tiene su propio intérprete
  Python (~30-50 MB RSS cada uno). `s4_max_processes=8`
  agrega ~250-400 MB al RSS total — bien dentro del
  budget para los servidores del banco.
* Latencia del primer doc: la inicialización del pool toma
  200-500 ms (importando PIL/img2pdf/PyPDF2 en cada
  worker). Amortizado a nada a lo largo del resto del
  run.

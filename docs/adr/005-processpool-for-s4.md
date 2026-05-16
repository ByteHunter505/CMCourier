> [← Volver al índice](../INDEX.md) · [ADRs](README.md)

# ADR-005: `ProcessPoolExecutor` para ensamblado PDF (S4)

- **Estado**: Aceptado y vigente
- **Fecha**: 2026-05-15
- **Spec(s) relacionadas**: 066 (S4 process pool); precedida por 056 (prep workers configurables, base que expuso el problema)
- **Versión donde se shipping**: 0.68.0

## Contexto

S4 es el stage de **ensamblado PDF**: toma N archivos de imagen (TIFF, JPEG) glob-eados del file server bancario, los convierte a PDF página-por-página y los mergea en un único archivo staged que después S5 sube a CMIS. Las herramientas en juego son `img2pdf` (fast path), `Pillow` (fallback para TIFF LZW que img2pdf rechaza), y `PyPDF2` (merge final).

Spec 056 introdujo `prep_workers` configurable para paralelizar S2/S3/S4. La intuición operativa era que con `prep_workers=16` y un dataset mixto de 5000 docs, S4 debería paralelizarse y la pipeline iría rápido. Lo que se vió en producción fue lo contrario:

- BUCKET tab mostraba los 16 producers "in flight".
- Bucket level cerca de cero (S5 drenaba rápido).
- **Throughput agregado de PREP < 5 docs/s.** A pesar de 16 threads.

Diagnóstico:

S1 (indexing) y S2 (mapping) y S3 (metadata) son **dict-lookups en memoria** — el GIL no los lastima porque son operaciones cortas que liberan el lock entre llamadas. S4 es lo opuesto: **CPU-bound**, dominado por llamadas a extensiones C (`img2pdf.convert`, `PIL.Image.save`, `PdfMerger.append`) que **no siempre liberan el GIL**. El resultado es que los 16 threads existían pero **solo uno corría en cualquier instante**. El paralelismo era ficción.

Esto rompe el Principio I implícitamente — el bottleneck es el runtime de Python, no la lógica de negocio. Y rompe el Principio IV explícitamente: ensamblar PDFs en serie cuando tenemos 8 cores ociosos es buffering de CPU desperdiciado.

## Decisión

Movemos S4 (y solo S4) a un `ProcessPoolExecutor`. El resto del pipeline sigue en threads.

- **Nueva config `processing.s4_use_processes: bool = True`** — NEW DEFAULT. Cuando True, S4 corre en process pool. Cuando False, restaura el comportamiento inline pre-066 byte-a-byte (escape hatch).
- **`processing.s4_max_processes: int | None = None`** — count de procesos. `None` resuelve a `os.cpu_count()`.
- **Módulo `cmcourier.adapters.assembly.pool`** con funciones module-level (picklables): `_pool_init`, `_pool_assemble`, `build_s4_process_pool`.
- **`StagedPipeline._s4_one`** rutea via `pool.submit(_pool_assemble, doc).result()` cuando el pool está set, sino llama `self._assembler.assemble(doc)` directo. El thread bloquea en `.result()` pero **libera el GIL** durante el wait — otros producers corren S1-S3 en paralelo.
- **`SourceFileMissingError.__reduce__` + `PDFAssemblyFailedError.__reduce__`** — los kwargs-only init de estas excepciones no eran pickle-friendly. `__reduce__` arregla el round-trip worker→main.
- **`multiprocessing.get_context("spawn")` explícito.** No `fork`. El parent tiene muchos threads (producers, S5 pool, AIMD controller, sampler); `fork` en parent multi-threaded deja al child con locks inconsistentes y emite `DeprecationWarning` en Python 3.12+. `spawn` levanta un intérprete fresco y re-corre `_pool_init` limpio.

## Consecuencias

### Positivas

- **Paralelismo CPU real.** Para workloads dominadas por S4 en PDFs grandes, esperamos ~8× speedup en throughput PREP con `os.cpu_count()=8`. Empíricamente se confirmó en staging.
- **GIL ya no es bottleneck para S4.** Cada worker process tiene su propio intérprete; corren bytecode Python en paralelo de verdad.
- **Aislamiento de crash.** Si una página corrupta hace que `img2pdf` segfault-ee dentro de su extensión C, el worker process muere — el orquestador lo nota, marca el doc como `S4_FAILED`, y los otros workers siguen. Pre-066, un segfault en el thread principal hubiera terminado todo el proceso.
- **Compatible con Python 3.12+.** El `spawn` context explícito elimina el DeprecationWarning sobre fork en parents multi-threaded.

### Negativas / Tradeoffs

- **Overhead de IPC + pickle.** ~1-5 ms por doc para serializar input y output. Negligible contra el costo real del assembly (multi-segundos en PDFs largos), pero medible en docs triviales (1 página).
- **Memoria adicional.** Cada worker process es ~30-50 MB RSS. Con `s4_max_processes=8`, eso suma ~250-400 MB. Para hosts apretados, hay que dimensionar.
- **First-doc latency.** Pool spin-up + worker imports toma 200-500 ms al inicio. Amortizado a cero sobre el resto del run, pero el primer doc se siente lento.
- **Excepciones cruzan límite de proceso vía pickle.** Tuvimos que agregar `__reduce__` a `SourceFileMissingError` y `PDFAssemblyFailedError`. Cualquier excepción S4 nueva que tenga kwargs-only init va a necesitar el mismo tratamiento — es trampa fácil de pisar.
- **`fork`-based Python en plataformas viejas no soportado.** Decisión consciente: el banco corre Python ≥ 3.11 en hosts modernos, y `spawn` es el future-proof default.
- **Wiring level necesita registrar shutdown del pool.** Hoy via `atexit` (spec 066 documentó la posibilidad de mover a un `pipeline.close()` explícito). Funciona, pero es global state.

### Neutras

- **S1/S2/S3 siguen en threads.** Son dict-lookup-bound, threads les sirven. No movemos todo el PREP a procesos.

## Alternativas consideradas

- **Cython / Rust extension nativo para el ensamblado.** Overkill. `img2pdf` ya hace el trabajo C-side; el problema no era el assembly per se, era la concurrencia. Re-implementar en lenguaje nativo era 10× el esfuerzo.
- **AsyncIO en S4.** No aplica: `img2pdf`, `PIL`, `PyPDF2` son APIs síncronas que bloquean el event loop. Habría tenido que envolverlas en `run_in_executor` — que internamente usa thread pool, volviendo al problema original.
- **Mantener todo en threads y aceptar el GIL.** Es lo que teníamos pre-066. Documentamos que `prep_workers=16` daba <5 docs/s. Inaceptable.
- **Spawn manual de subprocesos con `subprocess`.** El subprocess CLI lookup, JSON serialization de input/output, parsing de errores — todo eso ya lo hace `ProcessPoolExecutor` con pickle. Reinventar la rueda sin ganar nada.
- **`s4_use_processes=False` como default.** Lo descartamos: el speedup en producción es lo suficientemente grande como para que el default valga la pena. El escape hatch existe para entornos raros.

## Ver también

- [Explanation: ProcessPool para PDF assembly](../explanation/processpool-for-pdf-assembly.md)
- [Spec 056 — prep workers configurables](../../specs/056-prep-workers/)
- [Spec 066 — S4 process pool](../../specs/066-s4-process-pool/)
- [Constitution — Principio IV (streaming over buffering)](../../.specify/memory/constitution.md)

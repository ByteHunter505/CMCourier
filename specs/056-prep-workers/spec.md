# 056 — Workers de prep configurables: paralelizar S2/S3/S4

## Por qué

Mirando la TUI en un run de staging, el operador vio el stage
de armado (S4) avanzando a paso de tortuga. Y lo está —
`_stage_s4` es un loop serial `for item in items:` plano, un
documento a la vez, en un solo thread. Lo mismo
`_stage_s2` y `_stage_s3`. Mientras tanto S5 (upload) corre en
un pool de N threads desde la spec 025.

El pedido del operador, textual y deliberadamente acotado:
*no* la maquinaria S5 completa (sin AIMD auto-tune, sin lanes
heavy/light, sin limitador de bandwidth) — solo **una palanca
YAML de cuántos threads puede usar el prep**.

### Qué es el prep en realidad

El prep son cinco stages, encadenados serialmente sobre la
lista de items: **S0** (acquire el index) → **S1** (indexing)
→ **S2** (mapping) → **S3** (metadata) → **S4** (assembly).
Se separan en dos grupos:

- **S2 / S3 / S4 — homogéneos, parallel-safe.** Los tres tienen
  la forma idéntica: `for item in items:`, trabajo
  independiente per-documento, después un write al tracking
  store. El tracking store *ya* es thread-safe (es el mismo
  store que los N threads de S5 martillan hoy — una cola async
  writer + un lock de reader). El `DocumentCacheService` de S3
  y su adapter `SqliteDocumentCache` están *los dos* protegidos
  por `threading.Lock` (verificado). El `StageTimer` /
  `MetricsRecorder` son thread-safe ("las métricas per-stage
  usan un lock bajo el capó").
- **S0 / S1 — ordenados, stateful.** `_stage_s0_s1` lleva la
  lógica de idempotencia cross-batch, el `resume_scope`, el
  filtering de `RVABREPDeletedError` (051). Paralelizarlo deja
  de ser "simple" e introduce riesgo real — y no es el stage
  que duele. **Fuera de alcance.**

## Qué

### 1. `processing.prep_workers` — nueva palanca YAML

Agregar `prep_workers: int = Field(default=1, ge=1)` a
`ProcessingConfig` (ya tiene la palanca de concurrencia a
nivel processing `batches_in_flight`). Default `1` →
comportamiento byte-idéntico al de hoy, así que los configs
existentes no se ven afectados y nadie se sorprende.

### 2. `StagedPipeline` toma `prep_workers`

`__init__` gana `prep_workers: int = 1` (al lado del
`workers` existente); guardado como
`self._prep_workers = max(1, int(prep_workers))`. La capa de
wiring pasa `config.processing.prep_workers`.

### 3. S2 / S3 / S4 corren en un pool de tamaño fijo

Extraer el cuerpo per-item de cada stage en un helper
(`_s2_one` / `_s3_one` / `_s4_one`) que devuelve
`tuple[_StageItem | None, bool]` —
`(survivor o None, fue_una_falla_contada)`. El `bool`
preserva el edge case actual de resume: un item que falla
*pero ya fue marcado done en un run anterior* se descarta de
survivors sin incrementar `failed`.

Un helper de dispatch compartido corre los cuerpos:

- `prep_workers == 1` → una list comprehension serial plana —
  **byte-idéntica al loop actual** (mismo patrón que
  `_stage_5_single` siendo "byte-idéntico al de 025").
- `prep_workers > 1` →
  `ThreadPoolExecutor(max_workers=prep_workers)` con
  `pool.map(...)`. `pool.map` **preserva el orden de input**,
  así que `survivors` queda determinístico sin importar el
  orden de completion — sin regresión de ordenamiento para el
  stage S5 que lo consume.

Los helpers per-item ya atrapan sus propias excepciones de
dominio (`IDRViNotMappedError`, `SourceFailedError`,
`PDFAssemblyFailedError`, …) adentro del body — devuelven
`(None, …)` en vez de levantar, así `pool.map` nunca ve una
falla de dominio. Las excepciones inesperadas propagan
exactamente como lo hacen en el loop serial hoy.

## Fuera de alcance

- **S0 / S1** — ordenados/stateful; explícitamente excluidos
  arriba.
- La maquinaria de S5 — AIMD auto-tune, lanes heavy/light,
  limitador de bandwidth, el panel en vivo
  `WorkerPoolStats`. El operador pidió un conteo de threads
  plano y nada más.
- Un surface en la TUI para los prep workers — el progreso
  per-stage existente del tab PREP es suficiente; este cambio
  solo hace que esos números se muevan más rápido. Sin panel
  nuevo.
- `ProcessPoolExecutor` — S2/S3/S4 son I/O-bound (copias de
  archivos, lectura de imágenes de páginas, I/O de fuente de
  metadata), así que el GIL se libera durante el trabajo y los
  threads escalan. Sin necesidad de multiprocessing.

## Criterios de aceptación

- `processing.prep_workers` parsea, default a `1`, rechaza
  `< 1`.
- Con `prep_workers = 1`, S2/S3/S4 corren el camino serial —
  un test assertea que el dispatch toma la rama non-pool (o,
  equivalentemente, que el output es idéntico al loop pre-056
  en un input fijo).
- Con `prep_workers = 4`, S2/S3/S4 procesan correctamente un
  batch multi-item: cada survivor presente, `survivors` en
  **orden de input**, conteo de `failed` correcto incluyendo
  el caso de resume already-done — un test assertea cada
  uno.
- Un item que falla (excepción de dominio) se descarta de
  survivors y se cuenta en `failed` exactamente como en el
  camino serial, bajo `prep_workers = 1` y `> 1`.
- `StagedPipeline.__init__` acepta `prep_workers`; la capa de
  wiring pasa `config.processing.prep_workers`.
- Suite completa unit + integration verde; mypy + ruff
  limpios.
- `CHANGELOG.md [0.59.0]`; `pyproject.toml` 0.58.0 → 0.59.0;
  `config-reference.yaml` documenta
  `processing.prep_workers`.

## Notas sobre estrategia de tests

S2/S3/S4 son ejercitados hoy por los tests del pipeline en
`staged.py` con fakes/stubs para los services. Los tests de
056 agregan un run de batch multi-item a `prep_workers = 4` y
assertean (a) corrección + ordenamiento de input, (b) que el
conteo de failure/resume matchea el camino serial, y (c) que
`prep_workers = 1` queda sin cambios. La thread-safety de los
colaboradores (`tracking_store`, `DocumentCacheService`,
`MetricsRecorder`) está establecida — son los mismos objetos
que S5 ya impulsa concurrentemente — así que los tests se
enfocan en la lógica nueva de dispatch, no en re-probar los
stores.

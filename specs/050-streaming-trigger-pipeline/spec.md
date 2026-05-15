# 050 — Trigger pipeline en streaming (memoria acotada para RVABREP 20M+)

## Por qué

La tabla RVABREP real del banco tiene ~20 millones de filas. El
pipeline actual materializa el set **entero** de triggers en RAM
antes de hacer cualquier trabajo — OOMearía mucho antes del primer
upload.

Las estrategias de trigger (`csv`, `direct_rvabrep`, `local_scan`,
`single_doc`) son todas **generadores** — `yield`ean fila por fila.
Esa pereza es correcta. Está **derrotada downstream** en cuatro
puntos:

1. **`MultiBatchOrchestrator._run_overlapped`** (`multi_batch.py:363`)
   — `triggers = list(self._pipeline._trigger_strategy.acquire(...))`
   materializa cada trigger, después `chunk_list = list(chunked(...))`
   materializa cada chunk, después `for idx in range(len(chunk_list))`
   siembra la máquina de estado de chunks para todos ellos upfront.
2. **`MultiBatchOrchestrator._run_single`** → `StagedPipeline.run`
   (`staged.py:306`) — `triggers = list(acquire(...))`, después S0–S4
   se corren sobre todo el batch monolíticamente; `_stage_s0_s1`
   construye una `list[_StageItem]` de cada doc y la pasa a través
   de S2/S3/S4.
3. **`TabularDataSource.get_all`** (`tabular.py:138`) —
   `self._df.to_dict(orient="records")` construye una lista Python
   completa de cada fila como dict antes de que el generator rinda
   nada.
4. **`--total`** — `triggers[:total]` slicea *después* de que la
   lista completa ya se materializó.

Efecto neto: un run de 20M filas necesita ~20M objetos trigger +
~20M objetos `_StageItem` + (para la fuente CSV) un DataFrame
pandas de 20M filas + una lista de dicts de 20M elementos —
decenas de GB. Las palancas `batch_size` y `--total` **no** ayudan;
slicean después del hecho.

El fix es dejar fluir la pereza del generator: los triggers
streamean en chunks de `batch_size`, cada chunk corre S0→S5, su
memoria se libera antes de que se tire del siguiente chunk. La
memoria pico pasa a ser `O(batch_size × batches_in_flight)`, no
`O(total triggers)`.

## Qué

### 1. `_run_overlapped` — streamear el iterador (camino N=2)

- `triggers = list(acquire(...))` → mantener el **iterador**:
  `triggers = self._pipeline._trigger_strategy.acquire(...)`.
- `--total`: `triggers[:total]` → `itertools.islice(triggers, total)`.
- `chunk_list = list(chunked(...))` → consumir el iterador **lazy**
  `chunked(triggers, batch_size)` directamente. `chunked()`
  (`orchestrators/chunked.py`) ya acepta generators y rinde
  lazy — sin cambios al helper.
- El loop de siembra de chunk-state upfront
  (`for idx in range(len(chunk_list))`) se remueve. El estado de
  cada chunk se siembra **lazy** por `_prep_loop` el momento en
  que tira de ese chunk (QUEUED→PREP en un paso). El tab CHUNKS
  de la TUI ya no muestra el plan completo upfront — ese es el
  trade-off necesario: saber el conteo total *es* materializar
  el total.
- El caso de input vacío cae naturalmente: un iterador vacío
  rinde cero chunks, `_prep_loop` corre cero iteraciones, el
  resultado es un `MultiBatchRunReport` vacío.

### 2. `_run_single` — separar resume de N=1 fresco

`_run_single` actualmente siempre llama al monolítico
`StagedPipeline.run()`. Separar por intención:

- **Resume / `from_stage > 1`** (el operador nombró un batch_id
  específico): sin cambios — `StagedPipeline.run()` monolítico.
  El batch es uno *previamente creado*, ya acotado por
  `batch_size`; no hay set de 20M acá.
- **N=1 fresco** (`batches_in_flight=1`, sin resume,
  `from_stage=1` — p. ej. el config heavy-lanes): un camino nuevo
  `_run_sequential` que streamea el iterador de triggers a través
  de `chunked()` y corre `prep_chunk` + `upload_chunk` por chunk —
  la forma N=1 de `_run_overlapped` sin el overlap de thread
  producer-consumer. Los `RunReport` por-chunk se acumulan en el
  `MultiBatchRunReport`.

### 3. `TabularDataSource.get_all` — iterar, no materializar

`for row in self._df.to_dict(orient="records")` →
iterar el DataFrame fila por fila (`itertuples` / build de dict
per-row) así el generator rinde sin construir primero la lista
completa de dicts. Esto reduce a la mitad el pico transient de la
fuente CSV.

### 4. Contrato de memoria

Después de 050, un run de N triggers tiene a lo sumo
`batch_size × batches_in_flight` objetos `_StageItem` + el mismo
orden de objetos trigger en vuelo a la vez — **constante en N**.
Asserteado por un test que corre un iterador sintético grande de
triggers y chequea que el orchestrator nunca materialice el set
completo (p. ej. un iterador instrumentado/contador, o una
aserción de RSS pico).

## Fuera de alcance

- **Carga eager del DataFrame en `TabularDataSource._load_csv`.** La
  fuente CSV es in-memory **por diseño** (spec 003, "primer
  adapter") — sus lookups random-access de `get_by_fields`
  (necesitados por el S1 del pipeline csv-trigger) *requieren* la
  tabla completa indexada en RAM. No hay historia coherente de
  streaming para random access. Los runs de migración de
  producción de 20M corren contra
  `indexing.source.kind: as400` (la tabla RVABREP AS400 en vivo,
  quereyada por-lookup) — la fuente AS400 ya streamea
  (`query_stream` / `fetchmany`). 050 hace que el **orchestrator**
  deje de derrotar ese streaming. La fuente CSV se queda
  bounded-memory-por-diseño y ese límite se documenta, no se
  arregla.
- **Resume re-iterando la fuente completa.** En resume /
  `from_stage>1`, `StagedPipeline.run()` todavía corre `acquire()`
  de S0 sobre toda la fuente para reconstruir los triggers antes
  de que `resume_scope` los filtre. Resume opera sobre un batch
  de *recovery* (≤ `batch_size`), no sobre el happy path de 20M —
  optimizarlo (impulsar los triggers de resume directamente
  desde la tracking DB) es un follow-up, notado como limitación
  conocida.
- El freeze por starvation del event-loop de la TUI — eso es la
  spec **051**.
- Memoria de prefetch de fuente de metadata
  (`metadata.prefetch_enabled`).
- `batches_in_flight > 2` (sigue POST-MVP §7).

## Criterios de aceptación

- `_run_overlapped` nunca materializa la lista completa de triggers
  ni la lista completa de chunks — verificado con un test de
  iterador lazy/contador.
- `--total N` sobre una fuente grande tira a lo sumo ~N triggers
  del iterador (islice), no de la fuente completa.
- Los runs N=1 frescos (`batches_in_flight=1`) streamean
  chunk-por-chunk vía el nuevo camino `_run_sequential`; los runs
  resume / `from_stage>1` son byte-idénticos a pre-050
  (`StagedPipeline.run` monolítico).
- `TabularDataSource.get_all` rinde sin construir la lista
  completa de dicts — verificado por un test (o inspección de la
  implementación basada en `itertuples`).
- Un test de streaming de N grande confirma que el conteo pico de
  `_StageItem` en vuelo es `O(batch_size × batches_in_flight)`,
  no `O(N)`.
- Suite completa unit + integration verde; mypy + ruff limpios.
- Los configs de staging (`config-staging-rvabrep.yaml` etc.)
  siguen corriendo end-to-end con resultados byte-idénticos —
  re-verify en vivo con `--total 5`.
- Entrada ``CHANGELOG.md [0.53.0]``; `pyproject.toml` 0.52.0 →
  0.53.0.

## Notas sobre estrategia de tests

La propiedad de streaming es la cosa bajo test, así que los tests
usan un **iterador de triggers lazy/contador** — un generator
que graba cuántos items se tiraron — y assertean que el
orchestrator tira en olas de forma `batch_size`, no todo de una
vez. No hace falta AS400 en vivo: la estrategia de trigger se
mockea en el límite del iterador. Los tests de integración
existentes `test_multi_batch.py` / `test_pipeline_*.py` son el
gate de regresión para paridad de comportamiento.

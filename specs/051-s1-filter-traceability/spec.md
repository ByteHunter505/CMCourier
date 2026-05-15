# 051 — Trazabilidad de filtros de S1 (filas RVABREP con código de borrado)

## Por qué

Un run de staging `--total 2000` mostró que S1 procesaba 1000
triggers por chunk pero solo ~943 / ~954 docs llegaban a S2–S5.
~57 / ~46 docs por chunk **se evaporaron sin trazabilidad** — sin
conteo, sin log, sin surface en la TUI. Las palabras del operador:
*"necesito mirar qué pasa, no simplemente que desaparezca."*

Causa raíz, trazada en el código:

`IndexingService._enrich_known_row` (`indexing.py:133`) — para un
`RvabrepRowTrigger` / `LocalScanTrigger`, si la fila RVABREP lleva
un código de borrado hace **`return []` silenciosamente**. Sin
excepción, sin log, sin contador. En `_stage_s0_s1` el loop
`for doc in docs:` simplemente no corre para ese trigger, así que
el doc no es ni `done`, ni `skipped` (cross-batch), ni `failed` —
es un **cuarto outcome al que el pipeline no le tiene nombre**.

(El camino `ClientTrigger` es inconsistente: `find_documents`
*levanta* `RVABREPDeletedError`, lo cual `_stage_s0_s1`
actualmente trata como una **falla** de S1 — también incorrecto:
un doc borrado en la fuente no es una falla del pipeline, está
correctamente excluido.)

## Qué

Hacer de "filtrado en S1 — borrado en la fuente" un **outcome de
primera clase**: contado, logueado per-doc, y surface en el
output headless y la TUI.

### 1. `IndexingService` — dejar de tragarse el filtro

`_enrich_known_row` levanta `RVABREPDeletedError` para una fila
con código de borrado en vez de `return []` — consistente con
`find_documents` (el camino `ClientTrigger` ya lo levanta). El
caso "no hay docs en absoluto" queda como `return []` solo para
input genuinamente vacío, lo cual no puede ocurrir para una sola
fila conocida.

### 2. `_stage_s0_s1` — un tally `filtered`, no una falla

`_stage_s0_s1` gana una rama `except RVABREPDeletedError` que:
- incrementa un contador `filtered` (NO `timer.mark_failed()`),
- emite un log estructurado INFO por doc filtrado: `txn_num` /
  `shortname` + `reason="deleted_at_source"`,
- hace `continue` (el doc no produce item).

`RVABREPDeletedError` pasa a ser entonces un **filtro**, no una
falla, para **ambos** caminos de trigger — un fix de consistencia.
`RVABREPNotFoundError` (un `ClientTrigger` apuntando a una fila
RVABREP inexistente) queda como una **falla** de S1 — eso sí es
genuinamente un error de integridad de data, fuera de alcance.

`_stage_s0_s1` devuelve `(items, skipped_cross_batch, filtered)`.

### 3. Pasar el conteo a través de los tipos de reporte

- `RunReport` gana `s1_filtered: int`.
- `StagedPipeline.run` + `prep_chunk` pasan `s1_filtered`
  (`prep_chunk` devuelve `(items, skipped, s1_done, s1_filtered,
  s2_failed, s3_failed, s4_failed)`).
- `MultiBatchRunReport` gana una propiedad agregada
  `s1_filtered`.
- `ChunkState` gana `prep_filtered: int = 0`; `_prep_one_chunk`
  lo puebla.

### 4. Surfacearlo

- **Output headless** (`_emit_outcome` en `cli/app.py`): la línea
  final de resumen gana `s1_filtered=N`.
- **Tab PREP de la TUI** (`render_prep`): una línea
  `FILTERED (S1, deleted at source)   N` debajo de la tabla del
  stage.
- **Tab CHUNKS de la TUI** (`render_chunks`): la columna
  `PREP d/s/f` por-chunk pasa a `PREP d/s/f/x` (x = filtered); la
  fila TOTAL también.
- **`data_provider`** (`_chunks_state_snapshot`): incluir
  `prep_filtered`.

## Fuera de alcance

- **El filtro de filas en blanco de `DirectRvabrepTriggerStrategy.acquire`.**
  Las filas con shortname/system_id en blanco se descartan en S0
  *antes* de pasar a ser triggers (no están en el conteo de 1000
  de S1), así que no son el gap observado del operador.
  `acquire` ya emite un log INFO de resumen. Pasar ese conteo
  es un follow-up separado, más chico.
- **Drill-down per-doc en la TUI** (el issue #4 del operador —
  seleccionar un chunk, listar cada archivo con
  name/size/status/reason). Eso es un feature más grande por sí
  solo; 051 entrega los *conteos + log per-doc*, no una lista
  interactiva de archivos.
- **Reclasificación de `RVABREPNotFoundError`.** Queda como una
  falla de S1.
- El display de MB/s + docs/s del chunk (#2), el freeze del timer
  de upload (#3), y el clasificador de cuellos de botella —
  todos items separados.

## Criterios de aceptación

- `_enrich_known_row` levanta `RVABREPDeletedError` para una fila
  con código de borrado; un test unitario lo assertea.
- `_stage_s0_s1` cuenta un `RvabrepRowTrigger` con código de
  borrado como `filtered`, no `failed`, no `done` — y emite un
  log INFO con `txn_num` + `reason="deleted_at_source"`.
- Para un chunk de N triggers donde K filas tienen código de
  borrado: `s1_done + s1_filtered == N` (cada trigger contado) —
  un test assertea esta conservación.
- `RunReport.s1_filtered`, `MultiBatchRunReport.s1_filtered`,
  `ChunkState.prep_filtered` todos llevan el conteo.
- La línea de resumen headless muestra `s1_filtered=N`.
- `render_prep` muestra la línea FILTERED; `render_chunks` muestra
  el desglose `d/s/f/x` — tests sobre los renderers.
- Suite completa unit + integration verde; mypy + ruff limpios.
- `CHANGELOG.md [0.54.0]`; `pyproject.toml` 0.53.0 → 0.54.0.

## Notas sobre estrategia de tests

Sin Alfresco en vivo necesario — esto es filtering a nivel S1,
completamente cubierto por tests unitarios (`IndexingService`,
`_stage_s0_s1`) + tests de integración (orchestrator pasando el
conteo, los renderers). Las suites existentes `test_indexing.py`
/ `test_multi_batch.py` / `test_tabs.py` / `test_chunks_tab.py`
son el gate de regresión; los tests nuevos assertean el outcome
`filtered` end to end.

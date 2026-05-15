# 041 — TUI: corrección de redirección de logs + bytes/timer en UPLOAD + estadísticas expandidas de CHUNKS

## Por qué

Surgieron tres carencias visibles para el operador en la TUI en vivo durante
el dry-run de staging de 042/043:

1. **Los logs ensucian el frame de la TUI.** Textual repinta la terminal
   cada ~250 ms, pero cada ``log.info()`` del pipeline / adapters /
   uploader escribe a stderr, rompiendo el frame a mitad de render.
   El operador apenas puede leer el dashboard. Peor en `batches` >50
   docs donde cada línea `stage_complete` inunda cada refresh.

2. **El tab UPLOAD cuenta documentos, no rastrea bytes.** La barra
   de progreso muestra ``count / target`` en documentos (p. ej.
   ``5 / 10``). Los operadores quieren correctamente **bytes** ("MB
   subidos / MB restantes") porque (a) los documentos varían 20× en
   tamaño (PDF de 1 KB vs stack TIFF de 500 KB) y (b) los techos
   de ancho de banda son por bytes. También quieren un **timer
   acotado al `chunk`** — el display actual es elapsed global del
   run; con el solapamiento multi-batch (028) el wall-clock
   por-chunk es la métrica que mapea a "¿cuánto tarda un `batch`?".

3. **El tab CHUNKS es una lista de estado, no un desglose.** Hoy
   muestra ``idx / batch_id / status / s5_done / s5_failed`` por
   `chunk`. Los operadores quieren el **desglose completo de stages**
   por chunk (PREP done/failed/skipped/elapsed +
   UPLOAD done/failed/skipped/elapsed) más los totales agregados
   (cantidad de docs, bytes totales) para que un vistazo al tab
   responda "¿qué hizo realmente este run?".

## Qué

### 1. Redirección de logs cuando la TUI está activa

`observability/setup.py` gana una flag ``tui_active: bool`` que se
propaga desde la CLI. Cuando es ``True``:

- El ``StreamHandler`` que escribe a ``stderr`` **no se agrega** al
  root logger. Solo queda el ``FileHandler`` rotativo a
  ``observability.log_dir/app-YYYY-MM-DD.log``.
- Las actualizaciones de estado propias de la TUI escriben a sus
  widgets, nunca al stream de la terminal, así el frame queda limpio.
- Cuando se setea ``--no-tui``, el comportamiento es idéntico al de hoy.

Es un fix chico y quirúrgico — sin cambios al formato de log, sin
nueva estructura de archivos, sin cambios a la política de rotación.

### 2. Tab UPLOAD — progreso de bytes + timer del `chunk`

La barra de progreso **se mantiene en docs** (intuitivo para el
operador), pero la línea gana un ratio de MB a la derecha y una
nueva línea muestra velocidad promedio por-chunk + elapsed + ETA:

```
  S5 UPLOAD     ████████░░░░░░░░░░░░░░░░░░░░     9 / 22 docs   127.3 MB / 312.8 MB
                chunk elapsed 00:02:14   avg 2.13 MB/s   est remaining 00:03:18
                p50 234.1 ms   p95 1,205.3 ms   p99 3,401.2 ms
```

Para que esto funcione, el data provider gana cinco nuevos campos de snapshot:

- ``current_chunk_bytes_uploaded: int`` — bytes acumulados ACKed
  para el chunk activo (de los eventos ``stage_complete`` de S5).
- ``current_chunk_bytes_total: int`` — bytes planificados para el
  chunk (suma de ``StagedFile.size_bytes`` post-S4).
- ``current_chunk_elapsed_s: float`` — wall-clock desde que el chunk
  entró a S5 PREP (no desde el inicio global del run).
- ``current_chunk_avg_mbps: float`` — ``bytes_uploaded /
  elapsed_s`` (MB/s). Distinto del ``bandwidth_current_mbps``
  existente, que es una muestra rolling de 1s — este es el promedio
  por-chunk desde el inicio.
- ``current_chunk_eta_s: float | None`` — proyección lineal naive
  (``elapsed * (1 - progress) / progress``). Solo se muestra cuando
  ``progress > 0.05`` para evitar conjeturas alocadas.

### 3. Tab CHUNKS — desglose completo de stages por chunk

Re-renderizado como una tabla más ancha con desglose por-chunk
por-stage más una fila de agregado al fondo:

```
CHUNKS — pipeline csv-trigger-pipeline
──────────────────────────────────────────────────────────────────────────────
  idx  batch_id        docs    MB    PREP done/skip/fail (s)   UPLOAD done/skip/fail (s)
  ── ─ ────────────── ── ── ── ─── ──────────────────────── ────────────────────────────
  0    a1b2c3d4         95   42.1   95/0/0   (12.4s)         95/0/0   (8.9s)    ✓ DONE
  1    e5f6g7h8         88   38.7   88/0/0   (11.8s)         88/0/0   (8.2s)    ✓ DONE
  2    i9j0k1l2         91   40.3   91/0/0   (12.1s)         87/0/4   (9.4s)    ▲ UPLOAD
  3    m3n4o5p6         93   41.9    —        —                —        —       · QUEUED
  ── ─ ────────────── ── ── ── ─── ──────────────────────── ────────────────────────────
TOTAL  (4 chunks)      367  163.0   274/0/0  (36.3s)         270/0/4  (26.5s)
```

Nuevos campos por-chunk que rastrea el data provider:

- ``doc_count: int`` — total de docs encolados para este chunk.
- ``total_bytes: int`` — suma de tamaños de archivos staged (post-S4).
- ``prep_done / prep_skipped / prep_failed: int`` — outcomes S1..S4.
- ``prep_elapsed_s: float`` — wall-clock solo para la fase PREP.
- ``upload_skipped: int`` — docs de S5 que el uploader salteó
  (hit de idempotencia, etc). Los campos ``s5_done`` y ``s5_failed``
  ya existen.
- ``upload_elapsed_s: float`` — wall-clock solo para la fase S5.

La fila TOTAL agrega a través de todos los chunks para el vistazo
del operador "¿qué hizo realmente todo el run?".

## Fuera de alcance

- Nueva recolección de métricas en el pipeline mismo. La data que
  necesitamos ya aterriza en ``metrics.jsonl`` (cada evento
  ``stage_complete`` de S1..S5 tiene ``outcome``, ``duration_ms`` y
  ``size_bytes`` donde aplica). El data provider solo necesita agregarla.
- Re-diseño de los gráficos de ancho de banda en tiempo real (el sparkline se queda).
- Una tecla para pausar/reanudar / drill into a chunk — spec futura.
- Persistir el estado de CHUNKS entre runs (es solo en vivo).
- Cambios en el tema de color. Mismo texto ASCII monocromo.

## Criterios de aceptación

- Con la TUI activa, ``pipeline run`` muestra un dashboard limpio. No
  hay líneas de log que se filtren a la terminal. El archivo
  ``sample/logs/app-YYYY-MM-DD.log`` sigue recibiendo todos los eventos.
- Con ``--no-tui``, el comportamiento es idéntico a pre-041 (logs a
  stderr como antes).
- El tab UPLOAD muestra progreso de MB + timer del chunk + ETA cuando
  el chunk pasó el 5% de progreso.
- El tab CHUNKS muestra por-chunk doc_count + total_bytes + desglose
  de PREP + desglose de UPLOAD + fila TOTAL agregada.
- Los tests de snapshot existentes de la TUI pasan sin cambios donde
  no se intersectan con los nuevos campos.
- Nuevos tests de snapshot cubren ambos tabs renderizados contra
  instancias sintéticas de ``TUISnapshot`` (sin pipeline en vivo requerido).
- mypy + ruff limpios.
- Entrada ``[0.44.0]`` en el CHANGELOG.

## Notas sobre estrategia de tests

Las TUIs de Textual son notoriamente difíciles de testear unitariamente.
No vamos a tratar de manejar Textual mismo en tests; vamos a testear
las **funciones puras de render** (``render_upload`` / ``render_chunks``)
contra instancias sintéticas de ``TUISnapshot``. Eso refleja cómo
``tests/unit/tui/test_*.py`` ya funciona en este codebase.

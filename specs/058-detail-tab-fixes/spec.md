# 058 — Fixes del tab DETAIL: persistir metadata de staged-file + panel scrolleable

## Por qué

Dos bugs en el tab DETAIL (spec 052) que el operador encontró
durante un run de staging real:

1. La columna `size` siempre muestra `—`. El peso de los
   archivos **nunca llega a la pantalla**.
2. El panel no scrollea. Los chunks con más docs que los que
   entran en una pantalla quedan visualmente truncados — el
   operador no puede ver las filas debajo del fold.

Los dos están presentes en cada run, en cada chunk.

### Bug 1 — `file_size_bytes` nunca persiste

`_build_record` (`staged.py:478-480`) toma la metadata del
staged-file (`source_file_path`, `page_count`,
`file_size_bytes`) de `item.staged_file`. Pero ese campo es
`None` hasta que **S4** termina de armar — y la fila se
**inserta por primera vez en S1** (`staged.py:566`), donde
`item.staged_file is None`. Así que el INSERT inicial escribe
`None`. Peor: `mark_stage_pending` usa
**`INSERT OR IGNORE`** (`sqlite.py:335`), así que la llamada
en S4 — que llevaría los valores reales — se ignora
silenciosamente: la fila ya existe. Y ningún `UPDATE`
posterior toca esas columnas (`mark_stage_done` solo escribe
`status` / `completed_at` / `cm_object_id`;
`mark_stage_failed` solo escribe `status` / `error_message` /
`retry_count`).

Estado final: `file_size_bytes` queda `NULL` para siempre.
`list_docs_for_batch` hace COALESCE a `0`. `render_detail`
llama a `_human_size(0)` que devuelve `"—"`. Mismo destino
para `source_file_path` y `page_count` — los tres se conocen
en S4 pero nunca se escriben.

### Bug 2 — El panel DETAIL no scrollea

`app.py:82-83`:
```python
with TabPane("DETAIL", id="detail"):
    yield Container(Static(id="detail_body", classes="tab_body"))
```

`Container` de `textual.containers` es una caja plana — **no
scrollea**. El CSS `Static.tab_body { height: 1fr }` hace que
el widget interno llene el pane; el contenido más allá de la
altura visible queda **cropeado, no scrolleable**. Eso es por
qué 052 trunca a `_MAX_ROWS = 100` — un workaround para el
scroll faltante, no un feature.

## Qué

### 1. Persistir la metadata del staged-file cuando S4 tiene éxito

Un nuevo método de port en `ITrackingStore`:

```python
def record_staged_file_metadata(
    self,
    txn_num: str,
    batch_id: str,
    *,
    source_file_path: str,
    page_count: int,
    file_size_bytes: int,
) -> None:
```

Implementado en `SQLiteTrackingStore` como un único
`UPDATE migration_log SET source_file_path = ?, page_count = ?,
file_size_bytes = ?` keyeado en `(rvabrep_txn_num, batch_id)`,
encolado a través del async writer existente para que quede
consistente con el resto de los writes del store.

`_s4_one` (`staged.py`) lo llama después de que el assembler
devuelve exitosamente — **afuera** del guard
`if not is_stage_done`, así que un re-run de resume que
encuentra S4 ya hecho **también** back-fillea la metadata. La
llamada es idempotente: reescribir los mismos valores es un
no-op.

### 2. Hacer el panel DETAIL scrolleable

- `app.py`: el `TabPane` DETAIL rinde
  `VerticalScroll(Static(...))` en vez de
  `Container(Static(...))`. `VerticalScroll` de
  `textual.containers` es la caja scrolleable estándar.
- CSS: una regla `#detail_body` con `height: auto` y
  `padding: 0 1`, así el `Static` interno se dimensiona a su
  contenido y el scroll del padre puede moverse a través de
  él. La regla `Static.tab_body` (usada por PREP / UPLOAD /
  CHUNKS — todos dashboards de tamaño fijo) mantiene
  `height: 1fr` y **no** se aplica a `#detail_body`.
- `render_detail`: subir `_MAX_ROWS` de `100` a `2000`. Un
  chunk está topado en `batch_size` (default 1000); 2000 es
  un techo de seguridad generoso. El hint
  `… N más — lista completa: cmcourier batch show ...` se
  queda para el caso de overflow genuino.

## Fuera de alcance

- Optimizaciones de re-renderizado para chunks muy grandes.
  El panel DETAIL se re-renderiza cada 250 ms con el resto
  del dashboard, y un render de string de 2000 filas está
  bien dentro del budget de Textual. Si la performance pasa a
  ser un issue podemos agregar un guard "solo re-renderizar
  cuando el chunk seleccionado o su lista de docs cambió" —
  pero es un cambio separado.
- Los paneles PREP / UPLOAD / CHUNKS — son dashboards de
  tamaño fijo que entran en pantalla y no necesitan scroll.
- Un backfill retroactivo para las filas escritas antes de
  058. Los runs nuevos llevarán la metadata correctamente;
  las filas viejas se pueden back-fillear con un SQL update
  de un tiro si alguien lo necesita.

## Criterios de aceptación

- Existe un nuevo método de port
  `ITrackingStore.record_staged_file_metadata`, implementado
  en `SQLiteTrackingStore` vía la cola del async writer. Un
  test del adapter arranca un batch, inserta una fila
  S1-pending (file_size = NULL), llama al método nuevo, y
  assertea que `file_size_bytes` / `source_file_path` /
  `page_count` de la fila son ahora los valores pasados.
- `_s4_one` invoca el método después de un `assemble()`
  exitoso — un test a nivel pipeline corre un batch de un
  solo doc, quereya la fila de `migration_log`, y assertea
  `file_size_bytes > 0`.
- El `TabPane` DETAIL rinde un `VerticalScroll` conteniendo
  `#detail_body` — un test de TUI assertea que
  `detail_body.parent` es una instancia de `VerticalScroll`.
- `render_detail` muestra hasta 2000 filas; un test de
  rendering pasa 1500 `DocDetail`s y assertea que todos
  aparecen en el output (sin hint de truncamiento).
- Suite completa unit + integration verde; mypy + ruff
  limpios.
- `CHANGELOG.md [0.61.0]`; `pyproject.toml` 0.60.0 → 0.61.0.

## Notas sobre estrategia de tests

El Bug 1 se ejercita en dos niveles — un test estilo-unitario
de adapter que clava las semánticas del nuevo `UPDATE`, más
un run real de pipeline asserteando que `file_size_bytes` de
la fila es no-cero después de que S4 completa. El Bug 2 se
ejercita montando la app Textual bajo `App.run_test()` (el
piloto de test async incorporado de Textual) e inspeccionando
el árbol de widgets.

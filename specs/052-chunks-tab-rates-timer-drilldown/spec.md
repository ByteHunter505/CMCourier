# 052 — Tab CHUNKS: rates en vivo, timer frozen, drill-down por-chunk

## Por qué

Un run de staging `--total 2000` con la TUI hizo surface a tres
gaps que el operador encontró, todos en el dashboard:

- **#2** El tab CHUNKS muestra conteos por-stage pero **no
  throughput** — sin MB/s, sin docs/s por chunk. El operador no
  puede decir qué tan rápido se movió un chunk realmente.
- **#3** El timer de UPLOAD **nunca para**. Después de que el
  último chunk termina, el `elapsed` del footer sigue contando
  hacia arriba — el operador no puede leer el wall-clock real del
  run de la pantalla.
- **#4** **No hay manera de inspeccionar un chunk**. El operador
  ve `chunk 1: 943/0/0/57` pero no puede drill in para ver
  *cuáles* archivos se subieron / skippearon / fallaron /
  filtraron, sus nombres, tamaños, y la razón de un fail o skip.

## Qué

### #3 — Freezear el timer del run en completion

`TUIDataProvider` computa
`elapsed = time.monotonic() - _batch_started_monotonic` en cada
snapshot — así que tickea para siempre. Agregar
`_batch_completed_monotonic`: `mark_batch_started` lo resetea a
`None`, `mark_batch_complete` lo stampea con `time.monotonic()`,
y `snapshot()` usa el end time **frozen** una vez que el run
está completo: `end = _batch_completed_monotonic or time.monotonic()`.

### #2 — Throughput por-chunk en el tab CHUNKS

`render_chunks` ya tiene cada input que necesita por chunk
(`total_bytes`, `s5_done`, `upload_elapsed_s`). Agregar una
columna **RATE**: `MB/s` y `docs/s` para la fase UPLOAD
(`total_bytes / upload_elapsed_s`, `s5_done / upload_elapsed_s`),
renderizadas por chunk y en la fila TOTAL. Un `upload_elapsed_s`
de cero (no arrancado / instantáneo) renderiza un guión, nunca un
divide-by-zero.

### #4 — Drill-down por-chunk (respaldado por la tracking-DB)

El detalle per-doc NO debe ser mantenido en memoria — spec 050
hizo el pipeline bounded-memory, y mantener estado per-doc para
cada chunk reintroduciría `O(total docs)`. En su lugar el
drill-down **lee desde el SQLite tracking store**, que ya tiene
una fila `migration_log` por doc y está acotado en disco.

- **`ITrackingStore.list_docs_for_batch(batch_id) -> list[DocDetail]`**
  — nuevo método de port. `DocDetail` es un dataclass frozen:
  `txn_num`, `file_name`, `status`, `error_message`,
  `file_size_bytes`. `SQLiteTrackingStore` lo implementa con
  `SELECT rvabrep_txn_num, rvabrep_file_name, status, error_message,
  file_size_bytes FROM migration_log WHERE batch_id = ?
  ORDER BY rvabrep_txn_num`.
- **`StagedPipeline.tracking_store`** — una propiedad pública
  (hoy el store es `_tracking_store`, alcanzado vía
  `# noqa: SLF001`).
- **`TUIDataProvider`** gana un arg `tracking_store` en el
  constructor y un método
  `docs_for_batch(batch_id) -> list[DocDetail]` que delega al
  store. Wireado en `cli/app.py`.
- **TUI** — un nuevo `TabPane("DETAIL", id="detail")` y un
  cursor de selección de chunk en la app:
  - `[` / `]` mueven la selección al chunk anterior / siguiente;
  - `d` salta al tab DETAIL;
  - `_refresh_panels` resuelve el `batch_id` del chunk seleccionado
    desde el `chunks_state` del snapshot, llama
    `provider.docs_for_batch(batch_id)`, y lo renderiza.
  - `tui/detail_tab.py` — `render_detail(...)`: un header (chunk
    idx / batch_id / status / counts) más una tabla per-doc —
    `txn_num`, `file_name`, size, status, y la razón del fail/skip
    (`error_message`).
  - La navegación con cursor `[` / `]` maneja cualquier conteo de
    chunks; sin chunk seleccionado el panel solicita al operador
    elegir uno.

## Fuera de alcance

- Una reescritura del tab CHUNKS con `DataTable` clickeable por
  mouse. El enfoque `Static` + cursor `[`/`]` es de menor riesgo
  (la TUI hoy funciona) y suficiente para un dashboard de
  operador en vivo. Un post-mortem completo de un run terminado
  sigue perteneciendo a la CLI (`cmcourier batch show`,
  `cmcourier inspect`).
- Streamear el detalle per-doc en vivo mientras un chunk sube —
  el drill-down lee filas committeadas de `migration_log`, así
  que el detalle de un chunk se llena a medida que sus docs
  llegan a estados terminales. Suficiente.
- Paginación de la tabla DETAIL para chunks muy grandes —
  `batch_size` es el techo (default 1000); la tabla renderiza lo
  que entra y el operador scrollea.

## Criterios de aceptación

- Después de `mark_batch_complete`, `snapshot().elapsed_s` es
  **constante** a lo largo de snapshots posteriores — un test
  assertea que dos snapshots post-completion devuelven el mismo
  `elapsed_s`.
- `render_chunks` muestra una figura de `MB/s` y `docs/s` por
  chunk y en la fila TOTAL; un chunk con
  `upload_elapsed_s == 0` muestra un guión, sin excepción.
- `SQLiteTrackingStore.list_docs_for_batch` devuelve un
  `DocDetail` por fila `migration_log` del batch, llevando
  status + `error_message`; un test lo assertea contra un store
  poblado.
- `TUIDataProvider.docs_for_batch` delega al store.
- La TUI montea un panel DETAIL; `[` / `]` mueven la selección;
  un test piloto `run_test()` assertea que la selección se mueve
  y el panel renderiza los docs del chunk seleccionado.
- Suite completa unit + integration verde; mypy + ruff limpios.
- `CHANGELOG.md [0.55.0]`; `pyproject.toml` 0.54.0 → 0.55.0.

## Notas sobre estrategia de tests

Sin Alfresco en vivo. #3 es un test unitario de
`TUIDataProvider`. #2 es un test del renderer `render_chunks`.
#4: un test de integración de `SQLiteTrackingStore` (poblar
`migration_log`, assertear `list_docs_for_batch`), un test
unitario de `TUIDataProvider.docs_for_batch`, un test del
renderer `render_detail`, y un test piloto `run_test()` para la
selección + panel DETAIL. Las suites existentes
`test_chunks_tab.py` / `test_data_provider.py` / `test_tabs.py`
/ `test_sqlite*.py` son el gate de regresión.

# 041 — Plan

Cuatro fases, ~5h total. La Fase 1 entrega el bug fix aislado para que
los operadores puedan usar la TUI a mitad de batch apenas aterriza la
Fase 1. Las Fases 2-3 agregan las nuevas métricas. La Fase 4 son docs + bump.

## Fase 1 — Redirección de logs cuando la TUI está activa (~1h)

### Archivos

- `src/cmcourier/observability/setup.py`
  - `configure_logging(...)` acepta nuevo kwarg ``tui_active: bool = False``.
  - Cuando es ``True``, omitir el agregado del ``StreamHandler(sys.stderr)``.
    Solo se adjunta el ``FileHandler`` rotativo.
- `src/cmcourier/cli/_tui_runner.py`
  - Antes de lanzar la App de Textual, llamar a ``configure_logging(..., tui_active=True)``.
  - Cuando la app sale (el operador sale o el batch completa), el
    proceso termina de todos modos — no hace falta "restaurar" handlers.
- `src/cmcourier/cli/commands/*.py` (cada comando que respeta
  `--no-tui`)
  - Cuando ``--no-tui`` es el camino elegido, se llama a
    ``configure_logging(...)`` con ``tui_active=False`` (comportamiento actual).
  - Cuando se elige el camino de TUI, el runner de arriba lo maneja.

### Tests

- `tests/unit/observability/test_setup.py`
  - Con ``tui_active=True``, el root logger tiene exactamente 1 handler
    y es un ``FileHandler``.
  - Con ``tui_active=False``, el root logger tiene tanto ``FileHandler``
    como ``StreamHandler``.
- Integración: un test de CliRunner que invoca un run de pipeline mini
  en modo TUI y asserta ``result.stderr == ""`` mientras la TUI está activa.

### Commit

```
fix(observability,tui): silence stderr logging while TUI is active (041 Phase 1)
```

## Fase 2 — Tab UPLOAD: progreso de MB + timer del chunk (~1.5h)

### Archivos

- `src/cmcourier/tui/data_provider.py`
  - Agregar a ``TUISnapshot``:
    - ``current_chunk_bytes_uploaded: int``
    - ``current_chunk_bytes_total: int``
    - ``current_chunk_elapsed_s: float``
    - ``current_chunk_eta_s: float | None``
  - El provider incrementa ``current_chunk_bytes_uploaded``
    en cada evento ``stage_complete`` de S5 cuyo
    ``outcome == "ok"`` (el evento existente ya lleva
    ``size_bytes``). Para ``current_chunk_bytes_total`` suma
    ``size_bytes`` de eventos ``stage_complete`` de S4 a medida
    que llegan (el total del chunk se conoce cuando PREP cierra).
  - ``current_chunk_elapsed_s`` es el wall-clock desde que el chunk
    transicionó a PREP — trackear ``chunk_prep_started_at`` por
    chunk.
- `src/cmcourier/tui/upload_tab.py`
  - Reemplazar la barra de progreso por cantidad de docs con la barra
    de progreso por bytes (manteniendo el contador de docs como segunda
    línea para contexto).
  - Agregar la línea "chunk elapsed / est remaining".

### Tests

- `tests/unit/tui/test_upload_tab.py`
  - Snapshot con progreso al 0% → barra vacía, sin línea ETA.
  - Snapshot al 40% → barra al 40%, ETA mostrada.
  - Snapshot al 100% (batch completo) → barra llena, ETA oculta.
  - Valores de MB formateados con un decimal hasta escala GB.

### Commit

```
feat(tui,observability): UPLOAD tab MB progress + chunk timer (041 Phase 2)
```

## Fase 3 — Tab CHUNKS: desglose completo de stages (~2h)

### Archivos

- `src/cmcourier/tui/data_provider.py`
  - Extender cada entrada en ``chunks_state`` con:
    - ``doc_count`` (ya conocido después de S1)
    - ``total_bytes`` (suma de tamaños de archivos staged de S4)
    - ``prep_done`` / ``prep_skipped`` / ``prep_failed``
    - ``prep_elapsed_s``
    - ``upload_skipped`` (s5_done / s5_failed ya están)
    - ``upload_elapsed_s``
  - El provider agrega eventos ``stage_complete`` por stage
    por chunk_id, contando outcomes y acumulando duration.
- `src/cmcourier/tui/chunks_tab.py`
  - Re-renderizar como tabla más ancha con el desglose por-chunk +
    una fila TOTAL agregada al fondo.
  - Anchos de columna ajustados para encajar en terminales de ~80
    columnas (el resto de la TUI asume ancho 76-80).
  - Los chunks vacíos (status QUEUED) muestran placeholders ``—`` en
    las columnas PREP/UPLOAD para evitar conteos espurios de cero.

### Tests

- `tests/unit/tui/test_chunks_tab.py`
  - Snapshot con 4 chunks en distintos stages (uno DONE, uno
    UPLOAD, uno PREP, uno QUEUED) — assertea la forma de la tabla +
    los totales de la fila agregada.
  - Snapshot all-DONE — la fila TOTAL suma correctamente.
  - chunks_state vacío — header + mensaje "(no chunks yet)"
    preservado.

### Commit

```
feat(tui,observability): CHUNKS tab expanded per-stage breakdown + totals (041 Phase 3)
```

## Fase 4 — Docs + CHANGELOG 0.44.0 + bump de versión + FF (~30min)

### Archivos

- `docs/how-to/local-staging-simulation.md` Step 6 — actualizar el
  hint "What to watch in TUI" con el nuevo MB / timer / breakdown.
- `CHANGELOG.md [0.44.0]` — Agregado (progreso de MB, timer del chunk,
  breakdown de CHUNKS, fila TOTAL), Cambiado (redirección de logs
  cuando la TUI está activa), sin Removidos.
- `README.md` tick en la fila de features.
- `pyproject.toml` 0.43.0 → 0.44.0.

### Smoke

```bash
.venv/bin/cmcourier csv-trigger-pipeline run --config sample/config-staging.yaml --total 10
# (TUI ON por default)
```

Chequeo visual:
- Sin spam de logs encima del dashboard.
- El tab UPLOAD muestra progreso de MB + timer del chunk.
- El tab CHUNKS muestra la tabla de breakdown.

### Commit

```
docs(041): TUI runbook + CHANGELOG 0.44.0 + version bump (041 Phase 4)
```

### FF a main.

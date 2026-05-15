# 054 — Plan

Dos fases (~1 h total). Un solo archivo de fuente, quirúrgico.

## Fase 1 — Arreglar el wiring + tests de regresión (~40 min)

### Archivos

- `src/cmcourier/tui/data_provider.py`
  - **`snapshot()`** — cuatro campos se mueven de
    `self._metrics` a `self._upload_metrics`:
    - `bandwidth_current_mbps`
    - `bandwidth_peak_mbps`
    - `bandwidth_series`
    - `slow_ops_all`
    `self._upload_metrics` ya hace fallback a `self._metrics`
    cuando ningún `upload_recorder_provider` está wireado —
    single-batch sin cambios. Dejar `auto_tune_observed_p95_ms`
    como está (lee `current_stage_p95` y 043 wirea el p95 del
    AIMD por separado — fuera de alcance acá; el *bloque* de
    percentiles de S5 ya se sobrescribe vía
    `_upload_recorder_provider` más arriba en `snapshot()`).
  - **`_current_chunk_progress`** — reemplazar la rama de
    `prep_started_monotonic`. Resolver `elapsed_s` desde el
    `status` del chunk activo:
    - `UPLOAD` → `max(0.0, time.monotonic() − upload_started_monotonic)`
    - `DONE` → `float(upload_elapsed_s)`
    - `PREP` / desconocido → `0.0`
    - `active is None` (single-batch) → sin cambios:
      `global_elapsed_s`
    La resolución de `bytes_total` (desde `total_bytes`) queda
    sin cambios. La derivación de `avg_mbps` / `eta_s` queda
    sin cambios — solo consumen el `elapsed_s` corregido.

### Tests — `tests/unit/tui/test_data_provider.py`

Agregar un helper que construye el provider con **dos
recorders distintos** (un `recorder_provider` devolviendo un
recorder de PREP, un `upload_recorder_provider` devolviendo un
recorder de UPLOAD) más un `chunks_provider`.

- `test_bandwidth_reads_upload_recorder_not_prep` — recorder
  de UPLOAD alimentado con un evento de upload, recorder de
  PREP dejado vacío → `bandwidth_current_mbps` /
  `bandwidth_peak_mbps` del snapshot no-cero,
  `bandwidth_series` no-vacío.
- `test_slow_ops_read_upload_recorder_not_prep` —
  `cmis_upload` lento ruteado a través del logger de red del
  recorder de UPLOAD → aparece en `slow_ops_all`; el recorder
  de PREP queda vacío.
- `test_current_chunk_elapsed_measures_from_upload_start` —
  chunk en status `UPLOAD` con `prep_started_monotonic` muy
  en el pasado y `upload_started_monotonic` reciente →
  `current_chunk_elapsed_s` es el gap chico (de upload), no el
  grande (de prep).
- `test_current_chunk_elapsed_done_uses_frozen_upload_elapsed`
  — chunk en `DONE` → `current_chunk_elapsed_s == upload_elapsed_s`.
- `test_current_chunk_elapsed_prep_is_zero` — chunk en `PREP`
  → `current_chunk_elapsed_s == 0.0`.
- `test_current_chunk_avg_mbps_uses_upload_window` — bytes
  subidos / upload elapsed, no / prep+upload elapsed.

Los tests existentes de single-batch (`_make_provider` sin
`upload_recorder_provider`) son el gate de regresión — deben
quedar verdes sin tocarlos.

### Verify

Suite completa unit + integration + ruff + mypy.

### Commit

```
fix(tui): UPLOAD-tab reads the upload recorder for bandwidth/slow-ops + per-chunk timer measures from S5 start (054 Phase 1)
```

## Fase 2 — CHANGELOG 0.57.0 + bump de versión + README + FF (~20 min)

### Archivos

- `CHANGELOG.md` `[0.57.0]` — Fixed (el tab UPLOAD mostraba 0
  bandwidth / sparkline en blanco / sin slow ops en runs N=2
  porque cuatro campos de snapshot leían el recorder de PREP en
  vez del de UPLOAD; el timer por-chunk contaba desde el
  arranque de PREP en vez del de S5).
- `pyproject.toml` 0.56.0 → 0.57.0.
- Tick en fila de features de `README.md`.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.57.0
```

### Commit

```
docs(054): CHANGELOG 0.57.0 + version bump (054 Phase 2)
```

### FF a main.

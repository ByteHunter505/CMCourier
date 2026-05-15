# 053 — Plan

Dos fases (~1.75 h total).

## Fase 1 — Clasificador stage-aware + asociación de logs por ventana de tiempo (~1.25 h)

### Archivos

- `src/cmcourier/services/analyze.py`
  - **`classify_bottleneck`** — reescribir. Liderar con
    `stage_summary`:
    - Helper `_stage_dominance(stage_summary) -> (stage, share)`
      — sumar el `sum_ms` de cada stage, encontrar el stage
      dominante + su share del total.
    - Nueva constante `_STAGE_DOMINANCE = 0.45`.
    - Nuevo mapa `_STAGE_TO_CLASS`: `S5 → upload-bound`
      (afuera), `S4 → assembly-bound`, `S3 → metadata-bound`,
      `S2 → mapping-bound`, `S1 → indexing-bound`,
      `S0 → trigger-bound` (todos adentro).
    - Cuando un stage domina → clasificar por stage;
      `confidence` = share; `reasons` lidera con el veredicto
      del stage (nombre, share, p50/p95, adentro/afuera).
    - Las señales de métricas de sistema pasan a ser **razones
      apendizadas**, no el veredicto: `worker-saturated` → una
      razón de síntoma; cpu/mem/disk-bound → razones
      corroborantes. Solo pasan a ser la *clasificación*
      cuando ningún stage domina.
    - `under-utilized` solo cuando no hay stage dominante Y no
      hay señal de sistema.
    - Descartar el `# noqa: ARG001` muerto sobre `stage_summary`;
      mantener los params `cmis_max_bandwidth_mbps` /
      `pool_capacity` (todavía bindeados en tiempo de
      agregación, usados por el camino de sistema).
  - **`LogReader.read_batch`** — leer primero el
    `metrics-*.jsonl` batch-tagged; derivar la ventana
    `[ts − elapsed_s, ts]` del `batch_summary`; pasarla a
    `_read_windowed("network-*.jsonl", window, ts_field="ts")` y
    `_read_windowed("system-*.jsonl", window, ts_field="ts_iso")`.
  - Nuevo `_read_windowed(glob, window, *, ts_field)` —
    reemplaza el filtro de igualdad por `batch_id` para los
    tiers network/sistema; parsear el timestamp ISO de cada
    record, mantener los que están dentro de la ventana.
    `_read_filtered` (por `batch_id`) se queda para el tier
    `pipeline`.
  - Cuando el batch no tiene `batch_summary` (ventana no
    derivable) los tiers network/sistema vuelven vacíos —
    graceful, nunca levanta.

### Tests

- `tests/unit/services/test_analyze.py` (o donde vivan los
  tests del analyzer):
  - `test_classify_upload_bound_from_stage_dominance` — la
    forma del run de 95 docs (S5 `sum_ms` ≫ resto) →
    `upload-bound`, razón nombra S5 + "afuera del programa".
    **Test de regresión nombrado** para el bug
    "under-utilized".
  - `test_classify_assembly_bound` — S4-dominante →
    `assembly-bound` ("adentro").
  - `test_classify_under_utilized_when_balanced` — sin stage
    dominante, sin señal de sistema → `under-utilized`.
  - `test_worker_saturation_is_a_reason_not_the_verdict` —
    data de sistema con saturación + un desglose de stages
    S5-dominante → `upload-bound`, con la worker-saturation
    como una línea de razón.
  - `test_network_bound_surfaces_with_zero_bandwidth_cap` —
    dominancia de S5 + `cmis_max_bandwidth_mbps == 0` →
    todavía `upload-bound` (la regresión vieja se fue).
  - `LogReader`: `test_network_records_associated_by_time_window`
    — fixtures JSONL con `ts` cruzando la ventana; assertear
    que solo los records dentro de la ventana aterrizan en
    `network_summary`. Lo mismo para `system` vía `ts_iso`.

### Commit

```
feat(analyze): stage-aware bottleneck classifier + time-window log association (053 Phase 1)
```

## Fase 2 — CHANGELOG 0.56.0 + bump de versión + docs + FF (~30 min)

### Archivos

- `CHANGELOG.md` `[0.56.0]` — Fixed (el clasificador ignoraba
  el desglose de stages y reportaba "under-utilized" sobre un
  run upload-bound; los records network/sistema nunca se
  asociaban con el batch), Changed (la clasificación es
  stage-led; las métricas de sistema refinan en vez de gateear;
  `upload-bound` / `assembly-bound` / … nombran si el cuello de
  botella está adentro o afuera del programa).
- `pyproject.toml` 0.55.0 → 0.56.0.
- Tick en fila de features de `README.md`.
- `docs/how-to/log-analysis.md` (o el how-to de analyze) —
  documentar la nueva clasificación stage-led + los labels
  adentro/afuera-del-programa + el caveat de asociación por
  ventana de tiempo para runs solapados.

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.56.0
```

### Verify

Suite completa unit + integration + ruff + mypy.
`classify_bottleneck` es una función pura; `LogReader` se
testea por fixtures — sin Alfresco en vivo necesario.
Opcionalmente re-correr `analyze batch` sobre los logs de un
batch existente y mirar a ojo que ahora nombra el stage
dominante.

### Commit

```
docs(053): CHANGELOG 0.56.0 + version bump + bottleneck-classifier docs (053 Phase 2)
```

### FF a main.

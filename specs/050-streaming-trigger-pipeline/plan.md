# 050 — Plan

Dos fases (~2 h total).

## Fase 1 — Orchestrator en streaming + fuente + tests (~1.5 h)

### Archivos

- `src/cmcourier/orchestrators/multi_batch.py`
  - `_run_overlapped`:
    - `triggers = list(acquire(...))` → `triggers = acquire(...)`
      (mantener el iterador).
    - `--total`: `triggers[:max(0, total)]` →
      `itertools.islice(triggers, total)` cuando `total is not None`.
    - Descartar `chunk_list = list(chunked(...))`; pasar el
      iterador lazy `chunked(triggers, batch_size)` directo a
      `_prep_loop`.
    - Remover la siembra upfront de chunk-state
      `for idx in range(len(chunk_list))`. `_prep_loop` siembra
      el estado de cada chunk el momento que lo tira (`enumerate`
      sobre el iterador lazy de chunks).
    - Input vacío: manejado naturalmente (cero chunks → reporte
      vacío).
  - `_run_single` → separar por intención:
    - `resume_batch_id is not None or from_stage > 1` → sin
      cambios (`StagedPipeline.run()` monolítico).
    - sino (N=1 fresco) → nuevo `_run_sequential`: streamear
      `chunked(islice(acquire(...), total), batch_size)`, correr
      `prep_chunk` + `upload_chunk` por chunk, acumular
      `RunReport`s. Siembra chunk-state por chunk como
      `_prep_loop`.
- `src/cmcourier/adapters/sources/tabular.py`
  - `get_all`: reemplazar
    `for row in self._df.to_dict(orient="records")` con una
    iteración lazy per-row (`itertuples` → dict) así no se
    construye una lista completa de dicts.

### Tests

- `tests/integration/orchestrators/test_multi_batch.py` (o el
  archivo de test multi-batch existente):
  - `test_overlapped_streams_triggers` — un generator contador
    como fuente de triggers; assertear que el orchestrator nunca
    tira más de `batch_size × batches_in_flight` adelante de lo
    que se procesó.
  - `test_total_islices_the_source` — `--total N` sobre un
    generator contador de 10×N items tira ~N, no 10×N.
  - `test_sequential_n1_streams` — el camino N=1 fresco
    streamea chunk-por-chunk; los reportes por-chunk acumulados
    correctamente.
  - `test_resume_path_unchanged` — resume / `from_stage>1`
    sigue ruteado a través de `StagedPipeline.run`
    (byte-idéntico).
  - `test_empty_source_yields_empty_report` — iterador vacío →
    `MultiBatchRunReport` vacío, sin hang.
- `tests/unit/adapters/sources/test_tabular.py`:
  - `test_get_all_does_not_materialize` — `get_all` sobre un
    DataFrame rinde lazy (assertear vía una sonda de consumo de
    generator).
  - los tests existentes de comportamiento de `get_all` quedan
    verdes (mismas filas, mismo orden, misma normalización a
    `None`).

### Commit

```
feat(orchestrators,sources): stream triggers in bounded-memory chunks (050 Phase 1)
```

## Fase 2 — CHANGELOG 0.53.0 + bump de versión + docs + re-verify en vivo + FF (~30 min)

### Archivos

- `CHANGELOG.md` `[0.53.0]` — Fixed (los cuatro puntos de
  materialización), Changed (split de `_run_single`; `get_all`
  lazy), Notes (fuente CSV bounded-memory-por-diseño; resume
  re-iteration como limitación conocida; el camino de 20M es la
  fuente AS400).
- `pyproject.toml` 0.52.0 → 0.53.0.
- Tick en fila de features de `README.md` (052 / 050).
- `docs/how-to/validation-checklist.md` — notar que los runs
  grandes son bounded-memory y que la migración de 20M usa
  `indexing.source.kind: as400`.
- `docs/samples/config-reference.yaml` — anotar
  `indexing.batch_size` + `processing.batches_in_flight` con el
  contrato de memoria
  (`peak ≈ batch_size × batches_in_flight`).

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # esperar 0.53.0
```

### Re-verify en vivo (gate de regresión — el camino CSV de staging)

```bash
CMIS_USERNAME=admin CMIS_PASSWORD=admin .venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml --total 5 --no-tui
```

Aceptación: misma forma que los verifies de 048/049 — 5 triggers,
end-to-end limpio, sin cambio de comportamiento. (`--no-tui`
headless; el freeze de la TUI es problema de 051, no una
regresión acá.)

### Commit

```
docs(050): CHANGELOG 0.53.0 + version bump + bounded-memory docs (050 Phase 2)
```

### FF a main.

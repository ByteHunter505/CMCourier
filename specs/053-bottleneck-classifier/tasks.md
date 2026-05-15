# 053 — Tasks

## Fase 1 — Clasificador stage-aware + asociación de logs por ventana de tiempo

- [x] 1.1 `analyze.py`: helper `_stage_dominance(stage_summary)` +
      constante `_STAGE_DOMINANCE` + mapa `_STAGE_TO_CLASS`.
- [x] 1.2 `analyze.py`: reescribir `classify_bottleneck` —
      desglose de stages PRIMARIO; las métricas de sistema pasan
      a ser razones apendizadas; `worker-saturated` es una razón
      de síntoma, no el veredicto; `under-utilized` solo cuando
      nada domina.
- [x] 1.3 `analyze.py`: `_read_windowed(glob, window, *, ts_field)`;
      `read_batch` deriva la ventana del batch desde el
      `batch_summary` y la usa para los tiers de red (`ts`) +
      sistema (`ts_iso`).
- [x] 1.4 Tests: `classify_bottleneck` — regresión upload-bound
      (forma del run de 95 docs), assembly-bound,
      under-utilized-cuando-balanceado,
      worker-saturation-es-una-razón,
      network-bound-con-cap-cero.
- [x] 1.5 Tests: asociación por ventana de tiempo del
      `LogReader` para network (`ts`) + sistema (`ts_iso`).
- [x] 1.6 Suite completa unit + integration verde; mypy + ruff
      limpios. (1199 pasados; la única falla de dual-lane-throughput
      es un test conocido como timing-flaky — pasa aislado, no
      relacionado a analyze.)
- [x] 1.7 Commit
      `feat(analyze): stage-aware bottleneck classifier + time-window log association (053 Phase 1)`.

## Fase 2 — CHANGELOG 0.56.0 + bump de versión + docs + FF

- [x] 2.1 `CHANGELOG.md [0.56.0]` — Fixed / Changed.
- [x] 2.2 `pyproject.toml` 0.55.0 → 0.56.0.
- [x] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [x] 2.4 `cmcourier --version` reporta 0.56.0.
- [x] 2.5 Tick en fila de features de `README.md`.
- [x] 2.6 `docs/how-to/log-analysis.md` — clasificación
      stage-led + labels adentro/afuera-del-programa + caveat
      de ventana de tiempo + el gate de regresión de CI
      reframeado alrededor de stages ADENTRO-del-programa.
- [x] 2.7 Suite completa + ruff + mypy limpios (verificado en
      Fase 1; la Fase 2 no toca código — solo
      docs/CHANGELOG/version/README).
- [x] 2.8 Commit
      `docs(053): CHANGELOG 0.56.0 + version bump + bottleneck-classifier docs (053 Phase 2)`.
- [ ] 2.9 FF a main.

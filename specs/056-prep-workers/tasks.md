# 056 — Tasks

## Fase 1 — Config de prep_workers + paralelizar S2/S3/S4 + tests

- [x] 1.1 `config/schema.py`: `ProcessingConfig.prep_workers: int =
      Field(default=1, ge=1)`.
- [x] 1.2 `staged.py`: `__init__` toma `prep_workers: int = 1`,
      guarda `self._prep_workers`.
- [x] 1.3 `staged.py`: extraer helpers per-item `_s2_one` /
      `_s3_one` / `_s4_one` devolviendo
      `tuple[_StageItem | None, bool]` (survivor,
      falla-contada) — excepciones de dominio atrapadas
      adentro.
- [x] 1.4 `staged.py`: dispatch
      `_run_prep_stage(items, worker)` — serial cuando
      `prep_workers == 1`, `ThreadPoolExecutor` +
      `pool.map` (preservando orden) cuando `> 1`.
- [x] 1.5 `staged.py`: `_stage_s2` / `_stage_s3` / `_stage_s4`
      pasan a ser wrappers finos sobre `_run_prep_stage`.
- [x] 1.6 La capa de wiring (`config/wiring.py`) pasa
      `config.processing.prep_workers` a `StagedPipeline(...)`.
- [x] 1.7 Tests: default=1 + rechazo de `<1` (`test_schema.py`);
      el run de fixture de 6 docs es byte-idéntico serial vs
      4-thread — parametrizado sobre `prep_workers ∈ {1, 4}`,
      asserteando los mismos conteos de falla per-stage
      (S2/S3/S4 cada uno falla uno) + S5_DONE=3, lo cual
      prueba ordenamiento + sin double-counting.
- [x] 1.8 Suite completa unit + integration verde (1212
      pasados); mypy + ruff limpios.
- [x] 1.9 Commit
      `feat(prep): configurable prep_workers — parallelize S2/S3/S4 on a fixed thread pool (056 Phase 1)`.

## Fase 2 — CHANGELOG 0.59.0 + bump de versión + docs + FF

- [x] 2.1 `CHANGELOG.md [0.59.0]` — Added.
- [x] 2.2 `pyproject.toml` 0.58.0 → 0.59.0.
- [x] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [x] 2.4 `cmcourier --version` reporta 0.59.0.
- [x] 2.5 Tick en fila de features de `README.md`.
- [x] 2.6 `docs/samples/config-reference.yaml` documenta
      `processing.prep_workers`.
- [x] 2.7 Suite completa + ruff + mypy limpios (verificado en
      Fase 1, 1212 pasados; la Fase 2 no toca código — solo
      docs/CHANGELOG/version).
- [x] 2.8 Commit
      `docs(056): CHANGELOG 0.59.0 + version bump + prep_workers config docs (056 Phase 2)`.
- [ ] 2.9 FF a main.

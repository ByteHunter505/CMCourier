# 062 — Tasks

## Fase 1 — Persistencia + tests

- [x] 1.1 `domain/models.py`: `StageStatus.S1_FILTERED` y
      `S1_SKIPPED`.
- [x] 1.2 `domain/ports.py`: método abstracto
      `ITrackingStore.mark_stage_terminal`.
- [x] 1.3 `adapters/tracking/sqlite.py`: implementación de
      `mark_stage_terminal` (UPDATE status + error_message +
      completed_at, SIN bump de retry); el validator acepta
      sufijos FAILED/FILTERED/SKIPPED.
- [x] 1.4 `orchestrators/staged.py`: `_stage_s0_s1`
      persiste filtered (txn_num sintético) + skipped
      cross-batch vía `mark_stage_pending` +
      `mark_stage_terminal`.
- [x] 1.5 `orchestrators/staged.py`: actualizar líneas 10-12
      del docstring del módulo.
- [x] 1.6 Tests: `test_ports.py` agrega
      `mark_stage_terminal` al set de métodos abstractos.
- [x] 1.7 Tests: `test_sqlite_tracking_store.py` —
      happy paths de mark_stage_terminal (FILTERED +
      SKIPPED), retry no bumpeado, rechaza stage
      no-terminal.
- [x] 1.8 Tests: `test_staged_pipeline.py` run filtered →
      fila `S1_FILTERED` con txn sintético + reason.
- [x] 1.9 Tests: segundo run de `TestCrossBatchSkip` →
      filas `S1_SKIPPED` con reason.
- [x] 1.10 Suite completa unit + integration verde; mypy +
      ruff limpios.
- [x] 1.11 Commit
      `feat(s1): persist filtered + cross-batch-skipped docs to migration_log (062 Phase 1)`.

## Fase 2 — CHANGELOG 0.64.0 + version + README + FF

- [x] 2.1 `CHANGELOG.md [0.64.0]` — Changed (skip
      cross-batch) + Added (filas filtered).
- [x] 2.2 `pyproject.toml` 0.63.0 → 0.64.0.
- [x] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [x] 2.4 `cmcourier --version` reporta 0.64.0.
- [x] 2.5 Tick en fila de features de `README.md`.
- [x] 2.6 Suite completa + ruff + mypy limpios.
- [x] 2.7 Commit
      `docs(062): CHANGELOG 0.64.0 + version bump (062 Phase 2)`.
- [x] 2.8 FF a main.

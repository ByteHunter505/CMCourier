# 054 — Tasks

## Fase 1 — Arreglar el wiring + tests de regresión

- [x] 1.1 `data_provider.py` `snapshot()`: `bandwidth_current_mbps`,
      `bandwidth_peak_mbps`, `bandwidth_series`, `slow_ops_all`
      leen de `self._upload_metrics`.
- [x] 1.2 `data_provider.py` `_current_chunk_progress`: resolver
      `elapsed_s` por status del chunk activo — UPLOAD → desde
      `upload_started_monotonic`; DONE → `upload_elapsed_s`
      frozen; PREP → 0.0; sin chunk activo → `global_elapsed_s`
      (sin cambios).
- [x] 1.3 Tests: bandwidth + slow-ops leen del recorder de
      UPLOAD, no de PREP — provider wireado con dos recorders
      divergentes.
- [x] 1.4 Tests: timer por-chunk — UPLOAD mide desde el
      arranque de S5, DONE usa `upload_elapsed_s` frozen, PREP
      es 0.0; avg_mbps usa la ventana de upload.
- [x] 1.5 Suite completa unit + integration verde (1206
      pasados); mypy + ruff limpios.
- [x] 1.6 Commit
      `fix(tui): UPLOAD-tab reads the upload recorder for bandwidth/slow-ops + per-chunk timer measures from S5 start (054 Phase 1)`.

## Fase 2 — CHANGELOG 0.57.0 + bump de versión + README + FF

- [x] 2.1 `CHANGELOG.md [0.57.0]` — Fixed.
- [x] 2.2 `pyproject.toml` 0.56.0 → 0.57.0.
- [x] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [x] 2.4 `cmcourier --version` reporta 0.57.0.
- [x] 2.5 Tick en fila de features de `README.md`.
- [x] 2.6 Suite completa + ruff + mypy limpios (verificado en
      Fase 1, 1206 pasados; la Fase 2 no toca código — solo
      docs/CHANGELOG/version).
- [x] 2.7 Commit
      `docs(054): CHANGELOG 0.57.0 + version bump (054 Phase 2)`.
- [ ] 2.8 FF a main.

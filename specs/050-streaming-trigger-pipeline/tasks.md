# 050 — Tasks

## Fase 1 — Orchestrator en streaming + fuente + tests

- [ ] 1.1 `multi_batch.py` `_run_overlapped`: mantener el iterador
      de triggers (descartar `list(acquire(...))`).
- [ ] 1.2 `_run_overlapped`: `--total` vía `itertools.islice`.
- [ ] 1.3 `_run_overlapped`: pasar `chunked(...)` lazy a
      `_prep_loop`; descartar `chunk_list = list(...)`.
- [ ] 1.4 `_run_overlapped` / `_prep_loop`: siembra de chunk-state
      lazy por-chunk; remover el loop upfront
      `range(len(chunk_list))`.
- [ ] 1.5 `_run_single`: separar — resume / `from_stage>1` queda
      monolítico; N=1 fresco rutea al nuevo `_run_sequential`.
- [ ] 1.6 Nuevo `_run_sequential`: streamear
      `chunked(islice(acquire(...), total), batch_size)`,
      `prep_chunk` + `upload_chunk` por chunk, acumular reportes.
- [ ] 1.7 `tabular.py` `get_all`: iteración lazy per-row, sin
      materialización completa de `to_dict(orient="records")`.
- [ ] 1.8 Tests: streaming de `_run_overlapped` + islice de
      `--total` + fuente vacía + `_run_sequential` N=1 +
      camino-resume-sin-cambios.
- [ ] 1.9 Tests: `TabularDataSource.get_all` lazy + paridad de
      comportamiento existente.
- [ ] 1.10 Suite completa unit + integration verde; mypy + ruff
      limpios.
- [ ] 1.11 Commit
      `feat(orchestrators,sources): stream triggers in bounded-memory chunks (050 Phase 1)`.

## Fase 2 — CHANGELOG 0.53.0 + bump de versión + docs + re-verify en vivo + FF

- [ ] 2.1 `CHANGELOG.md [0.53.0]` — Fixed / Changed / Notes.
- [ ] 2.2 `pyproject.toml` 0.52.0 → 0.53.0.
- [ ] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 2.4 `cmcourier --version` reporta 0.53.0.
- [ ] 2.5 Tick en fila de features de `README.md`.
- [ ] 2.6 `docs/how-to/validation-checklist.md` — nota de
      bounded-memory + camino de 20M usa fuente AS400.
- [ ] 2.7 `docs/samples/config-reference.yaml` — anotar el
      contrato de memoria `batch_size × batches_in_flight`.
- [ ] 2.8 Re-verify en vivo: `config-staging-rvabrep.yaml`
      `--total 5` `--no-tui`, misma forma que los verifies de
      048/049.
- [ ] 2.9 Suite completa + ruff + mypy limpios.
- [ ] 2.10 Commit
      `docs(050): CHANGELOG 0.53.0 + version bump + bounded-memory docs (050 Phase 2)`.
- [ ] 2.11 FF a main.

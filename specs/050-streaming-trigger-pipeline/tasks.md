# 050 — Tasks

## Phase 1 — Streaming orchestrator + source + tests

- [ ] 1.1 `multi_batch.py` `_run_overlapped`: keep the trigger
      iterator (drop `list(acquire(...))`).
- [ ] 1.2 `_run_overlapped`: `--total` via `itertools.islice`.
- [ ] 1.3 `_run_overlapped`: pass lazy `chunked(...)` into
      `_prep_loop`; drop `chunk_list = list(...)`.
- [ ] 1.4 `_run_overlapped` / `_prep_loop`: lazy per-chunk
      chunk-state seeding; remove the upfront
      `range(len(chunk_list))` loop.
- [ ] 1.5 `_run_single`: split — resume / `from_stage>1` stays
      monolithic; fresh N=1 routes to new `_run_sequential`.
- [ ] 1.6 New `_run_sequential`: stream
      `chunked(islice(acquire(...), total), batch_size)`,
      `prep_chunk` + `upload_chunk` per chunk, accumulate reports.
- [ ] 1.7 `tabular.py` `get_all`: per-row lazy iteration, no
      `to_dict(orient="records")` full materialization.
- [ ] 1.8 Tests: `_run_overlapped` streaming + `--total` islice +
      empty-source + `_run_sequential` N=1 + resume-path-unchanged.
- [ ] 1.9 Tests: `TabularDataSource.get_all` lazy + existing
      behavior parity.
- [ ] 1.10 Full unit + integration suite green; mypy + ruff clean.
- [ ] 1.11 Commit
      `feat(orchestrators,sources): stream triggers in bounded-memory chunks (050 Phase 1)`.

## Phase 2 — CHANGELOG 0.53.0 + version bump + docs + live re-verify + FF

- [ ] 2.1 `CHANGELOG.md [0.53.0]` — Fixed / Changed / Notes.
- [ ] 2.2 `pyproject.toml` 0.52.0 → 0.53.0.
- [ ] 2.3 `.venv/bin/pip install -e . --no-deps`.
- [ ] 2.4 `cmcourier --version` reports 0.53.0.
- [ ] 2.5 `README.md` feature row tick.
- [ ] 2.6 `docs/how-to/validation-checklist.md` — bounded-memory note
      + 20M path uses AS400 source.
- [ ] 2.7 `docs/samples/config-reference.yaml` — annotate the
      `batch_size × batches_in_flight` memory contract.
- [ ] 2.8 Live re-verify: `config-staging-rvabrep.yaml` `--total 5`
      `--no-tui`, same shape as 048/049 verifies.
- [ ] 2.9 Full suite + ruff + mypy clean.
- [ ] 2.10 Commit
      `docs(050): CHANGELOG 0.53.0 + version bump + bounded-memory docs (050 Phase 2)`.
- [ ] 2.11 FF to main.

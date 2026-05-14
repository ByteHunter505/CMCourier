# 050 — Plan

Two phases (~2 h total).

## Phase 1 — Streaming orchestrator + source + tests (~1.5 h)

### Files

- `src/cmcourier/orchestrators/multi_batch.py`
  - `_run_overlapped`:
    - `triggers = list(acquire(...))` → `triggers = acquire(...)`
      (keep the iterator).
    - `--total`: `triggers[:max(0, total)]` →
      `itertools.islice(triggers, total)` when `total is not None`.
    - Drop `chunk_list = list(chunked(...))`; pass the lazy
      `chunked(triggers, batch_size)` iterator straight into
      `_prep_loop`.
    - Remove the upfront `for idx in range(len(chunk_list))`
      chunk-state seeding. `_prep_loop` seeds each chunk's state the
      moment it pulls it (`enumerate` over the lazy chunk iterator).
    - Empty-input: handled naturally (zero chunks → empty report).
  - `_run_single` → split on intent:
    - `resume_batch_id is not None or from_stage > 1` → unchanged
      (`StagedPipeline.run()` monolithic).
    - else (fresh N=1) → new `_run_sequential`: stream
      `chunked(islice(acquire(...), total), batch_size)`, run
      `prep_chunk` + `upload_chunk` per chunk, accumulate
      `RunReport`s. Seeds chunk-state per chunk like `_prep_loop`.
- `src/cmcourier/adapters/sources/tabular.py`
  - `get_all`: replace `for row in self._df.to_dict(orient="records")`
    with a per-row lazy iteration (`itertuples` → dict) so no full
    dict list is built.

### Tests

- `tests/integration/orchestrators/test_multi_batch.py` (or the
  existing multi-batch test file):
  - `test_overlapped_streams_triggers` — a counting generator as the
    trigger source; assert the orchestrator never pulls more than
    `batch_size × batches_in_flight` ahead of what's been processed.
  - `test_total_islices_the_source` — `--total N` over a 10×N-item
    counting generator pulls ~N, not 10×N.
  - `test_sequential_n1_streams` — fresh N=1 path streams
    chunk-by-chunk; per-chunk reports accumulated correctly.
  - `test_resume_path_unchanged` — resume / `from_stage>1` still
    routes through `StagedPipeline.run` (byte-identical).
  - `test_empty_source_yields_empty_report` — empty iterator → empty
    `MultiBatchRunReport`, no hang.
- `tests/unit/adapters/sources/test_tabular.py`:
  - `test_get_all_does_not_materialize` — `get_all` on a DataFrame
    yields lazily (assert via a generator-consumption probe).
  - existing `get_all` behavior tests stay green (same rows, same
    order, same `None`-normalization).

### Commit

```
feat(orchestrators,sources): stream triggers in bounded-memory chunks (050 Phase 1)
```

## Phase 2 — CHANGELOG 0.53.0 + version bump + docs + live re-verify + FF (~30 min)

### Files

- `CHANGELOG.md` `[0.53.0]` — Fixed (the four materialization
  points), Changed (`_run_single` split; `get_all` lazy), Notes
  (CSV source bounded-memory-by-design; resume re-iteration known
  limitation; 20M path = AS400 source).
- `pyproject.toml` 0.52.0 → 0.53.0.
- `README.md` feature row tick (052 / 050).
- `docs/how-to/validation-checklist.md` — note that large runs are
  bounded-memory and the 20M migration uses `indexing.source.kind:
  as400`.
- `docs/samples/config-reference.yaml` — annotate `indexing.batch_size`
  + `processing.batches_in_flight` with the memory contract
  (`peak ≈ batch_size × batches_in_flight`).

### Release dance

```bash
.venv/bin/pip install -e . --no-deps
.venv/bin/cmcourier --version    # expect 0.53.0
```

### Live re-verify (regression gate — the CSV staging path)

```bash
CMIS_USERNAME=admin CMIS_PASSWORD=admin .venv/bin/cmcourier rvabrep-pipeline run \
  --config sample/config-staging-rvabrep.yaml --total 5 --no-tui
```

Acceptance: same shape as the 048/049 verifies — 5 triggers, end-to-end
clean, no behavioral change. (Headless `--no-tui`; the TUI freeze is
051's problem, not a regression here.)

### Commit

```
docs(050): CHANGELOG 0.53.0 + version bump + bounded-memory docs (050 Phase 2)
```

### FF to main.

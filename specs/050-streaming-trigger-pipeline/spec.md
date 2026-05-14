# 050 — Streaming trigger pipeline (bounded memory for 20M+ RVABREP)

## Why

The bank's real RVABREP table is ~20 million rows. The current
pipeline materializes the **entire** trigger set in RAM before doing
any work — it would OOM long before the first upload.

The trigger strategies (`csv`, `direct_rvabrep`, `local_scan`,
`single_doc`) are all **generators** — they `yield` row by row. That
laziness is correct. It is **defeated downstream** at four points:

1. **`MultiBatchOrchestrator._run_overlapped`** (`multi_batch.py:363`)
   — `triggers = list(self._pipeline._trigger_strategy.acquire(...))`
   materializes every trigger, then `chunk_list = list(chunked(...))`
   materializes every chunk, then `for idx in range(len(chunk_list))`
   seeds the chunk-state machine for all of them upfront.
2. **`MultiBatchOrchestrator._run_single`** → `StagedPipeline.run`
   (`staged.py:306`) — `triggers = list(acquire(...))`, then S0–S4 are
   run over the whole batch monolithically; `_stage_s0_s1` builds a
   `list[_StageItem]` of every doc and threads it through S2/S3/S4.
3. **`TabularDataSource.get_all`** (`tabular.py:138`) —
   `self._df.to_dict(orient="records")` builds a full Python list of
   every row's dict before the generator yields anything.
4. **`--total`** — `triggers[:total]` slices *after* the full list is
   already materialized.

Net effect: a 20M-row run needs ~20M trigger objects + ~20M
`_StageItem` objects + (for the CSV source) a 20M-row pandas
DataFrame + a 20M-element dict list — tens of GB. The `batch_size`
and `--total` knobs do **not** help; they slice after the fact.

The fix is to let the generator laziness flow through: triggers
stream in `batch_size` chunks, each chunk runs S0→S5, its memory is
released before the next chunk is pulled. Peak memory becomes
`O(batch_size × batches_in_flight)`, not `O(total triggers)`.

## What

### 1. `_run_overlapped` — stream the iterator (N=2 path)

- `triggers = list(acquire(...))` → keep the **iterator**:
  `triggers = self._pipeline._trigger_strategy.acquire(...)`.
- `--total`: `triggers[:total]` → `itertools.islice(triggers, total)`.
- `chunk_list = list(chunked(...))` → consume the **lazy**
  `chunked(triggers, batch_size)` iterator directly. `chunked()`
  (`orchestrators/chunked.py`) already accepts generators and yields
  lazily — no change to the helper.
- The upfront chunk-state seeding loop
  (`for idx in range(len(chunk_list))`) is removed. Each chunk's
  state is seeded **lazily** by `_prep_loop` the moment it pulls that
  chunk (QUEUED→PREP in one step). The TUI's CHUNKS tab no longer
  shows the full plan upfront — that is the necessary trade-off:
  knowing the total count *is* materializing the total.
- The empty-input case falls out naturally: an empty iterator yields
  zero chunks, `_prep_loop` runs zero iterations, the result is an
  empty `MultiBatchRunReport`.

### 2. `_run_single` — split resume from fresh N=1

`_run_single` currently always calls the monolithic
`StagedPipeline.run()`. Split by intent:

- **Resume / `from_stage > 1`** (operator named a specific batch_id):
  unchanged — `StagedPipeline.run()` monolithic. The batch is a
  *previously-created* batch, already bounded by `batch_size`; there
  is no 20M set here.
- **Fresh N=1** (`batches_in_flight=1`, no resume, `from_stage=1` —
  e.g. the heavy-lanes config): a new `_run_sequential` path that
  streams the trigger iterator through `chunked()` and runs
  `prep_chunk` + `upload_chunk` per chunk — the N=1 shape of
  `_run_overlapped` without the producer-consumer thread overlap.
  Per-chunk `RunReport`s are accumulated into the
  `MultiBatchRunReport`.

### 3. `TabularDataSource.get_all` — iterate, don't materialize

`for row in self._df.to_dict(orient="records")` →
iterate the DataFrame row by row (`itertuples` / per-row dict build)
so the generator yields without first building the full dict list.
This halves the CSV source's transient peak.

### 4. Memory contract

After 050, a run of N triggers holds at most
`batch_size × batches_in_flight` `_StageItem` objects + the same
order of trigger objects in flight at once — **constant in N**.
Asserted by a test that runs a large synthetic trigger iterator and
checks the orchestrator never materializes the full set (e.g. an
instrumented/counting iterator, or a peak-RSS assertion).

## Out of scope

- **`TabularDataSource._load_csv` eager DataFrame load.** The CSV
  source is in-memory **by design** (spec 003, "first adapter") — its
  `get_by_fields` random-access lookups (needed by the
  csv-trigger pipeline's S1) *require* the whole table indexed in
  RAM. There is no coherent streaming story for random access. The
  20M production migration runs against `indexing.source.kind: as400`
  (the live AS400 RVABREP table, queried per-lookup) — the AS400
  source already streams (`query_stream` / `fetchmany`). 050 makes
  the **orchestrator** stop defeating that streaming. The CSV source
  stays bounded-memory-by-design and that limit is documented, not
  fixed.
- **Resume re-iterating the full source.** In resume / `from_stage>1`,
  `StagedPipeline.run()` still runs S0 `acquire()` over the whole
  source to reconstruct triggers before `resume_scope` filters them.
  Resume operates on a *recovery* batch (≤ `batch_size`), not the 20M
  happy path — optimizing it (driving resume triggers straight from
  the tracking DB) is a follow-up, noted as a known limitation.
- The TUI event-loop starvation freeze — that is spec **051**.
- Metadata-source prefetch memory (`metadata.prefetch_enabled`).
- `batches_in_flight > 2` (still POST-MVP §7).

## Acceptance criteria

- `_run_overlapped` never materializes the full trigger list nor the
  full chunk list — verified with a counting/lazy iterator test.
- `--total N` over a large source pulls at most ~N triggers from the
  iterator (islice), not the whole source.
- Fresh N=1 runs (`batches_in_flight=1`) stream chunk-by-chunk via
  the new `_run_sequential` path; resume / `from_stage>1` runs are
  byte-identical to pre-050 (`StagedPipeline.run` monolithic).
- `TabularDataSource.get_all` yields without building the full dict
  list — verified by a test (or `itertuples`-based implementation
  inspection).
- A large-N streaming test confirms peak in-flight `_StageItem` count
  is `O(batch_size × batches_in_flight)`, not `O(N)`.
- Full unit + integration suite green; mypy + ruff clean.
- The staging configs (`config-staging-rvabrep.yaml` etc.) still run
  end-to-end with byte-identical results — live re-verify with
  `--total 5`.
- `CHANGELOG.md [0.53.0]` entry; `pyproject.toml` 0.52.0 → 0.53.0.

## Notes on test strategy

The streaming property is the thing under test, so the tests use a
**lazy/counting trigger iterator** — a generator that records how
many items have been pulled — and assert the orchestrator pulls in
`batch_size`-shaped waves, not all-at-once. No live AS400 needed: the
trigger strategy is mocked at the iterator boundary. The existing
`test_multi_batch.py` / `test_pipeline_*.py` integration tests are
the regression gate for behavioral parity.

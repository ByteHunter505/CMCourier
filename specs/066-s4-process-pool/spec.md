# 066 — S4 PDF assembly in a ProcessPoolExecutor (real parallelism)

## Why

Diagnosed during a 5000-doc streaming staging run (`config-staging-rvabrep-streaming.yaml`):

* `processing.prep_workers: 16` configured
* BUCKET tab showed `PREP 16 in-flight` (counter correct)
* BUCKET level stayed near 0 — S5 always faster than PREP
* PREP throughput: **< 5 docs/s** despite 16 producer threads

Diagnosis: S4 (PDF assembly via `img2pdf` + `PIL` + `PyPDF2`) is
CPU-bound. The **GIL serializes Python bytecode execution**, so
multiple threads running `PdfAssembler.assemble()` execute one at a
time at the C-extension boundary. The 16-thread parallelism is real
in terms of *threads existing inside `streaming_prep_one`*, but
aggregate throughput is ~equivalent to a single worker.

The earlier prep stages (S1 indexing, S2 mapping, S3 metadata) are
all dict-lookup-in-memory — they parallelize fine with threading
because they spend most of their time in C-level pandas / dict
operations that release the GIL. Only S4 is the bottleneck.

## What

### 1. `ProcessPoolExecutor` for S4 only

A pool of `N` worker processes runs `PdfAssembler.assemble()` for
every S4 invocation. The producer thread in `StreamingOrchestrator`
calls:

```python
staged = self._s4_pool.submit(_pool_assemble, document).result()
```

The thread blocks waiting for the result, but **releases the GIL
during the wait** — so other producer threads can execute S1/S2/S3
work in parallel. Meanwhile, the N worker processes each have their
own Python interpreter and execute `assemble()` at real OS-level
parallelism.

### 2. Module-level pool helpers (picklability)

```python
# in cmcourier.adapters.assembly.pool

_worker_assembler: PdfAssembler | None = None

def _pool_init(config: AssemblerConfig) -> None:
    global _worker_assembler
    _worker_assembler = PdfAssembler(config)

def _pool_assemble(document: RVABREPDocument) -> StagedFile:
    assert _worker_assembler is not None
    return _worker_assembler.assemble(document)
```

The pool is constructed once in the wiring layer with
`initializer=_pool_init, initargs=(assembler_config,)`. Each worker
reconstructs the assembler in its own process.

### 3. Config

```yaml
processing:
  # 066: when true, S4 assembly runs in a ProcessPoolExecutor with
  # `s4_max_processes` workers (default = os.cpu_count()). When false,
  # S4 runs synchronously inside the producer thread (063/064/065
  # behaviour).
  s4_use_processes: true  # NEW DEFAULT — opt-out for byte-identical-to-pre-066
  s4_max_processes: null  # null → os.cpu_count(); otherwise explicit int
```

### 4. Lifecycle

* **Construction**: wiring layer creates the pool when
  `s4_use_processes=true`. Passes it to `StagedPipeline.__init__`.
* **Use**: `_s4_one` checks for pool presence and dispatches to
  `pool.submit(...).result()` instead of calling `_assembler.assemble`
  directly.
* **Shutdown**: wiring layer (or pipeline `close()`) calls
  `pool.shutdown(wait=True)` after the run completes.

### 5. Picklability requirements

* `RVABREPDocument` — already a `@dataclass(frozen=True)` — picklable.
* `AssemblerConfig` — already a dataclass — picklable.
* `StagedFile` — already a dataclass — picklable.

No new picklability work needed.

## Out of scope

* S2 and S3 in process pool — they are dict-lookup-in-memory work,
  picklecost > computecost. Leave them in threads.
* S1 (indexing) — same reasoning.
* S5 (upload) — already parallelized via httpx + ThreadPool, network-bound
  so no GIL pressure.
* Cross-platform fork vs spawn nuance — `ProcessPoolExecutor` defaults to
  the platform's preferred method; we don't override.
* Logging from the worker processes — workers run silently for 066;
  any log message from inside `assemble()` is lost. A follow-up spec
  can wire a `QueueHandler` if operators need diagnostic logs.

## Acceptance criteria

* `processing.s4_use_processes` defaults to `true`. Setting it to
  `false` restores the 063/064/065 behaviour byte-identically (no
  pool created, S4 runs in producer thread).
* `processing.s4_max_processes` defaults to `None` (=
  `os.cpu_count()`). Explicit `int` overrides.
* `StagedPipeline` accepts an optional `s4_process_pool:
  ProcessPoolExecutor | None`. When set, `_s4_one` dispatches to the
  pool.
* `cmcourier.adapters.assembly.pool` exposes `_pool_init` and
  `_pool_assemble` at module level (importable / picklable).
* The wiring layer constructs the pool when configured and shuts it
  down on pipeline close.
* All existing tests pass. New tests:
  * Unit: pool helper functions are picklable.
  * Unit: `_s4_one` dispatches to the pool when present.
  * Unit: `_s4_one` falls back to direct assembly when pool is None.
  * Integration: 6-doc streaming run with `s4_use_processes=true`
    produces same `S5_DONE` count as without.
* mypy + ruff clean.
* CHANGELOG `[0.68.0]`; pyproject 0.67.0 → 0.68.0.

## Notes on expected impact

* Per-doc S4 latency: roughly the same (slightly higher due to pickle
  + IPC overhead of ~1-5ms per doc).
* Aggregate PREP throughput: should scale with `s4_max_processes` for
  CPU-bound workloads. With `os.cpu_count() = 8`, expect ~8x speedup
  over single-thread S4 for large PDFs.
* Memory: each worker process has its own Python interpreter (~30-50 MB
  RSS each). `s4_max_processes=8` adds ~250-400 MB to total RSS — well
  within budget for the banking servers.
* First-doc latency: pool initialization takes 200-500 ms (importing
  PIL/img2pdf/PyPDF2 in each worker). Amortized to nothing across the
  rest of the run.

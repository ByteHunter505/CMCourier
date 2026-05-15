"""Process-pool wrapper around :class:`PdfAssembler` (066).

Stage S4 (PDF assembly via ``img2pdf`` + ``PIL`` + ``PyPDF2``) is
CPU-bound and dominated by C-extension work that does not always
release the GIL. Running it inside a producer thread therefore
serializes regardless of how many threads exist — the BUCKET tab
shows N threads "in flight" but aggregate throughput is ~equivalent
to a single worker.

This module exposes a :class:`concurrent.futures.ProcessPoolExecutor`
that runs ``PdfAssembler.assemble`` in N worker processes, each with
its own Python interpreter. The producer thread submits and blocks
on ``.result()``; the block releases the GIL so other producers can
make progress on S1/S2/S3 work. The workers themselves execute
``assemble()`` at real OS-level parallelism.

Picklability contract:

* ``RVABREPDocument`` — frozen dataclass, picklable.
* ``StagedFile`` — frozen dataclass, picklable.
* ``AssemblerConfig`` — frozen dataclass, picklable.

The helper functions :func:`_pool_init` and :func:`_pool_assemble`
live at module level (not nested) so ``ProcessPoolExecutor`` can
pickle them by name.
"""

from __future__ import annotations

__all__ = ["build_s4_process_pool", "_pool_assemble", "_pool_init"]

import logging
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor

from cmcourier.adapters.assembly.pdf_assembler import AssemblerConfig, PdfAssembler
from cmcourier.domain.models import RVABREPDocument, StagedFile

_log = logging.getLogger(__name__)

# Per-worker singleton. The pool's ``initializer`` callable runs once
# per worker process and constructs the assembler here; subsequent
# ``_pool_assemble`` calls reuse it.
_worker_assembler: PdfAssembler | None = None


def _pool_init(config: AssemblerConfig) -> None:
    """ProcessPoolExecutor ``initializer`` — runs once per worker.

    Constructs a per-process :class:`PdfAssembler` and stashes it on
    the module-level ``_worker_assembler`` global. The assembler's
    constructor creates the temp dir (idempotent), so workers can
    safely race on it.
    """
    global _worker_assembler  # noqa: PLW0603 — module-level singleton by design
    _worker_assembler = PdfAssembler(config)


def _pool_assemble(document: RVABREPDocument) -> StagedFile:
    """Worker entry point — assemble one document and return the
    :class:`StagedFile`. Raises whatever :meth:`PdfAssembler.assemble`
    raises; the caller's ``Future.result()`` re-raises in the main
    process.
    """
    if _worker_assembler is None:  # pragma: no cover — initializer guarantees this
        raise RuntimeError("066: _pool_assemble called before _pool_init configured the worker")
    return _worker_assembler.assemble(document)


def build_s4_process_pool(
    config: AssemblerConfig,
    max_workers: int | None = None,
) -> ProcessPoolExecutor:
    """Construct a process pool sized to ``max_workers`` (default
    ``os.cpu_count()``). Every worker runs :func:`_pool_init` once
    with the supplied :class:`AssemblerConfig`.

    Caller owns lifecycle — must call ``pool.shutdown(wait=True)``
    when the pipeline run completes.
    """
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    workers = max(1, int(workers))
    # 066: force ``spawn`` (not ``fork``) because the parent process
    # runs many threads (producers, S5 pool, AIMD controller, sampler).
    # ``fork`` in a multi-threaded parent can leave the child in an
    # inconsistent lock state (Python 3.12 issues a DeprecationWarning
    # for this); ``spawn`` builds a fresh interpreter and re-runs the
    # module-level pool helpers via ``initializer``.
    spawn_ctx = multiprocessing.get_context("spawn")
    pool = ProcessPoolExecutor(
        max_workers=workers,
        initializer=_pool_init,
        initargs=(config,),
        mp_context=spawn_ctx,
    )
    _log.info(
        "066: S4 process pool started",
        extra={"max_workers": workers, "source_root": str(config.source_root)},
    )
    return pool

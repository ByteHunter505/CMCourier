# 052 — CHUNKS tab: live rates, frozen timer, per-chunk drill-down

## Why

A `--total 2000` staging run with the TUI surfaced three gaps the
operator hit, all on the dashboard:

- **#2** The CHUNKS tab shows per-stage counts but **no throughput** —
  no MB/s, no docs/s per chunk. The operator can't tell how fast a
  chunk actually moved.
- **#3** The UPLOAD timer **never stops**. After the last chunk
  finishes, the footer's `elapsed` keeps counting up — the operator
  can't read the real wall-clock of the run off the screen.
- **#4** There is **no way to inspect a chunk**. The operator sees
  `chunk 1: 943/0/0/57` but can't drill in to see *which* files were
  uploaded / skipped / failed / filtered, their names, sizes, and the
  reason for a fail or skip.

## What

### #3 — Freeze the run timer on completion

`TUIDataProvider` computes `elapsed = time.monotonic() -
_batch_started_monotonic` on every snapshot — so it ticks forever.
Add `_batch_completed_monotonic`: `mark_batch_started` resets it to
`None`, `mark_batch_complete` stamps it `time.monotonic()`, and
`snapshot()` uses the **frozen** end time once the run is complete:
`end = _batch_completed_monotonic or time.monotonic()`.

### #2 — Per-chunk throughput in the CHUNKS tab

`render_chunks` already has every input it needs per chunk
(`total_bytes`, `s5_done`, `upload_elapsed_s`). Add a **RATE** column:
`MB/s` and `docs/s` for the UPLOAD phase
(`total_bytes / upload_elapsed_s`, `s5_done / upload_elapsed_s`),
rendered per chunk and on the TOTAL row. Zero `upload_elapsed_s`
(not started / instant) renders a dash, never a divide-by-zero.

### #4 — Per-chunk drill-down (tracking-DB-backed)

The per-doc detail must NOT be held in memory — spec 050 made the
pipeline bounded-memory, and keeping per-doc state for every chunk
would reintroduce `O(total docs)`. Instead the drill-down **reads
from the SQLite tracking store**, which already has one
`migration_log` row per doc and is bounded on disk.

- **`ITrackingStore.list_docs_for_batch(batch_id) -> list[DocDetail]`**
  — new port method. `DocDetail` is a frozen dataclass:
  `txn_num`, `file_name`, `status`, `error_message`,
  `file_size_bytes`. `SQLiteTrackingStore` implements it with
  `SELECT rvabrep_txn_num, rvabrep_file_name, status, error_message,
  file_size_bytes FROM migration_log WHERE batch_id = ?
  ORDER BY rvabrep_txn_num`.
- **`StagedPipeline.tracking_store`** — a public property (today the
  store is `_tracking_store`, reached via `# noqa: SLF001`).
- **`TUIDataProvider`** gains a `tracking_store` constructor arg and a
  `docs_for_batch(batch_id) -> list[DocDetail]` method that delegates
  to the store. Wired in `cli/app.py`.
- **TUI** — a new `TabPane("DETAIL", id="detail")` and a chunk
  selection cursor on the app:
  - `[` / `]` move the selection to the previous / next chunk;
  - `d` jumps to the DETAIL tab;
  - `_refresh_panels` resolves the selected chunk's `batch_id` from
    the snapshot's `chunks_state`, calls
    `provider.docs_for_batch(batch_id)`, and renders it.
  - `tui/detail_tab.py` — `render_detail(...)`: a header (chunk idx /
    batch_id / status / counts) plus a per-doc table — `txn_num`,
    `file_name`, size, status, and the fail/skip reason
    (`error_message`).
  - `[` / `]` cursor navigation handles any chunk count; with no
    chunk selected the pane prompts the operator to pick one.

## Out of scope

- A mouse-clickable `DataTable` rewrite of the CHUNKS tab. The
  `Static` + `[`/`]` cursor approach is lower-risk (the TUI currently
  works) and sufficient for a live operator dashboard. A full
  post-mortem of a finished run still belongs to the CLI
  (`cmcourier batch show`, `cmcourier inspect`).
- Streaming the per-doc detail live as a chunk uploads — the
  drill-down reads committed `migration_log` rows, so a chunk's
  detail fills in as its docs reach terminal states. Good enough.
- Pagination of the DETAIL table for very large chunks — `batch_size`
  is the cap (default 1000); the table renders what fits and the
  operator scrolls.

## Acceptance criteria

- After `mark_batch_complete`, `snapshot().elapsed_s` is **constant**
  across subsequent snapshots — a test asserts two snapshots post-
  completion return the same `elapsed_s`.
- `render_chunks` shows a `MB/s` and `docs/s` figure per chunk and on
  the TOTAL row; a chunk with `upload_elapsed_s == 0` shows a dash,
  no exception.
- `SQLiteTrackingStore.list_docs_for_batch` returns one `DocDetail`
  per `migration_log` row for the batch, carrying status +
  `error_message`; a test asserts it against a populated store.
- `TUIDataProvider.docs_for_batch` delegates to the store.
- The TUI mounts a DETAIL pane; `[` / `]` move the selection; a
  `run_test()` pilot test asserts selection moves and the pane
  renders the selected chunk's docs.
- Full unit + integration suite green; mypy + ruff clean.
- `CHANGELOG.md [0.55.0]`; `pyproject.toml` 0.54.0 → 0.55.0.

## Notes on test strategy

No live Alfresco. #3 is a `TUIDataProvider` unit test. #2 is a
`render_chunks` renderer test. #4: a `SQLiteTrackingStore` integration
test (populate `migration_log`, assert `list_docs_for_batch`), a
`TUIDataProvider.docs_for_batch` unit test, a `render_detail` renderer
test, and a `run_test()` pilot test for the selection + DETAIL pane.
The existing `test_chunks_tab.py` / `test_data_provider.py` /
`test_tabs.py` / `test_sqlite*.py` suites are the regression gate.

# 058 — DETAIL tab fixes: persist staged-file metadata + scrollable pane

## Why

Two bugs on the DETAIL tab (spec 052) the operator hit during a real
staging run:

1. The `size` column always shows `—`. The peso of the files **never
   makes it to the screen**.
2. The pane does not scroll. Chunks with more than a screen's worth of
   docs are truncated visually — the operator cannot see the rows
   below the fold.

Both are present in every run, every chunk.

### Bug 1 — `file_size_bytes` never persists

`_build_record` (`staged.py:478-480`) takes the staged-file metadata
(`source_file_path`, `page_count`, `file_size_bytes`) from
`item.staged_file`. But that field is `None` until **S4** finishes
assembling — and the row is **first inserted in S1**
(`staged.py:566`), where `item.staged_file is None`. So the initial
INSERT writes `None`. Worse: `mark_stage_pending` uses
**`INSERT OR IGNORE`** (`sqlite.py:335`), so the S4 call —
which would carry the real values — is silently ignored: the row
already exists. And no later `UPDATE` ever touches those columns
(`mark_stage_done` only writes `status` / `completed_at` /
`cm_object_id`; `mark_stage_failed` only writes `status` /
`error_message` / `retry_count`).

End state: `file_size_bytes` stays `NULL` forever. `list_docs_for_batch`
COALESCE's it to `0`. `render_detail` calls `_human_size(0)` which
returns `"—"`. Same fate for `source_file_path` and `page_count` —
all three are S4-known but never written.

### Bug 2 — DETAIL pane is not scrollable

`app.py:82-83`:
```python
with TabPane("DETAIL", id="detail"):
    yield Container(Static(id="detail_body", classes="tab_body"))
```

`Container` from `textual.containers` is a plain box — **it does not
scroll**. The `Static.tab_body { height: 1fr }` CSS makes the inner
widget fill the pane; content beyond the visible height is **cropped,
not scrollable**. That is why 052 truncates to `_MAX_ROWS = 100` —
a workaround for the missing scroll, not a feature.

## What

### 1. Persist the staged-file metadata when S4 succeeds

A new port method on `ITrackingStore`:

```python
def record_staged_file_metadata(
    self,
    txn_num: str,
    batch_id: str,
    *,
    source_file_path: str,
    page_count: int,
    file_size_bytes: int,
) -> None:
```

Implemented in `SQLiteTrackingStore` as a single `UPDATE migration_log
SET source_file_path = ?, page_count = ?, file_size_bytes = ?` keyed
on `(rvabrep_txn_num, batch_id)`, enqueued through the existing async
writer so it stays consistent with the rest of the store's writes.

`_s4_one` (`staged.py`) calls it after the assembler returns
successfully — **outside** the `if not is_stage_done` guard, so a
resume re-run that finds S4 already done **also** backfills the
metadata. The call is idempotent: rewriting the same values is a
no-op.

### 2. Make the DETAIL pane scrollable

- `app.py`: the DETAIL `TabPane` yields `VerticalScroll(Static(...))`
  instead of `Container(Static(...))`. `VerticalScroll` from
  `textual.containers` is the standard scrollable box.
- CSS: a `#detail_body` rule with `height: auto` and `padding: 0 1`,
  so the inner `Static` sizes to its content and the parent's scroll
  can move through it. The `Static.tab_body` rule (used by PREP /
  UPLOAD / CHUNKS — all fixed-size dashboards) keeps `height: 1fr` and
  is **not** applied to `#detail_body`.
- `render_detail`: raise `_MAX_ROWS` from `100` to `2000`. A chunk is
  capped at `batch_size` (default 1000); 2000 is a generous safety
  ceiling. The `… N more — full list: cmcourier batch show ...` hint
  stays for the genuine overflow case.

## Out of scope

- Re-rendering optimisations for very large chunks. The DETAIL pane
  is re-rendered every 250 ms with the rest of the dashboard, and a
  2000-row string render is well within Textual's budget. If
  performance becomes an issue we can add an "only re-render when the
  selected chunk or its doc list changed" guard — but that is a
  separate change.
- The PREP / UPLOAD / CHUNKS panes — they are fixed-size dashboards
  that fit on screen and do not need scroll.
- A retroactive backfill for rows written before 058. New runs will
  carry the metadata correctly; old rows can be backfilled with a one
  shot SQL update if anyone needs it.

## Acceptance criteria

- A new `ITrackingStore.record_staged_file_metadata` port method
  exists, implemented in `SQLiteTrackingStore` via the async writer
  queue. An adapter test starts a batch, inserts an S1-pending row
  (file_size = NULL), calls the new method, and asserts the row's
  `file_size_bytes` / `source_file_path` / `page_count` are now the
  passed values.
- `_s4_one` invokes the method after a successful `assemble()` — a
  pipeline-level test runs a single-doc batch, queries the
  `migration_log` row, and asserts `file_size_bytes > 0`.
- The DETAIL `TabPane` yields a `VerticalScroll` containing
  `#detail_body` — a TUI test asserts `detail_body.parent` is a
  `VerticalScroll` instance.
- `render_detail` shows up to 2000 rows; a rendering test passes 1500
  `DocDetail`s and asserts all of them appear in the output (no
  truncation hint).
- Full unit + integration suite green; mypy + ruff clean.
- `CHANGELOG.md [0.61.0]`; `pyproject.toml` 0.60.0 → 0.61.0.

## Notes on test strategy

Bug 1 is exercised at two levels — a unit-style adapter test that
pins the new `UPDATE` semantics, plus a real pipeline run asserting
the row's `file_size_bytes` is non-zero after S4 completes. Bug 2 is
exercised by mounting the Textual app under `App.run_test()` (Textual's
built-in async test pilot) and inspecting the widget tree.

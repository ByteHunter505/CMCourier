# 041 — Plan

Four phases, ~5h total. Phase 1 ships the bug fix in isolation so
operators can use TUI mid-batch right after Phase 1 lands. Phases
2-3 add the new metrics. Phase 4 docs + bump.

## Phase 1 — Log redirection when TUI is active (~1h)

### Files

- `src/cmcourier/observability/setup.py`
  - `configure_logging(...)` accepts new kwarg ``tui_active: bool = False``.
  - When ``True``, skip adding the ``StreamHandler(sys.stderr)``.
    Only the rotating ``FileHandler`` is attached.
- `src/cmcourier/cli/_tui_runner.py`
  - Before launching the Textual App, call ``configure_logging(..., tui_active=True)``.
  - When the app exits (operator quits or batch completes), the
    process is ending anyway — no need to "restore" handlers.
- `src/cmcourier/cli/commands/*.py` (every command that respects
  `--no-tui`)
  - When ``--no-tui`` is the path chosen, ``configure_logging(...)``
    is called with ``tui_active=False`` (current behavior).
  - When the TUI path is chosen, the runner above handles it.

### Tests

- `tests/unit/observability/test_setup.py`
  - With ``tui_active=True``, root logger has exactly 1 handler
    and it is a ``FileHandler``.
  - With ``tui_active=False``, root logger has both ``FileHandler``
    and ``StreamHandler``.
- Integration: a CliRunner test that invokes a tiny pipeline run
  in TUI mode and asserts ``result.stderr == ""`` for the
  duration the TUI is up.

### Commit

```
fix(observability,tui): silence stderr logging while TUI is active (041 Phase 1)
```

## Phase 2 — UPLOAD tab: MB progress + chunk timer (~1.5h)

### Files

- `src/cmcourier/tui/data_provider.py`
  - Add to ``TUISnapshot``:
    - ``current_chunk_bytes_uploaded: int``
    - ``current_chunk_bytes_total: int``
    - ``current_chunk_elapsed_s: float``
    - ``current_chunk_eta_s: float | None``
  - The provider increments ``current_chunk_bytes_uploaded``
    on each S5 ``stage_complete`` event whose
    ``outcome == "ok"`` (the existing event already carries
    ``size_bytes``). For ``current_chunk_bytes_total`` it sums
    ``size_bytes`` from S4 ``stage_complete`` events as they
    arrive (the chunk's total is known when PREP wraps).
  - ``current_chunk_elapsed_s`` is the wall-clock since the chunk
    transitioned to PREP — track ``chunk_prep_started_at`` per
    chunk.
- `src/cmcourier/tui/upload_tab.py`
  - Replace the doc-count progress bar with the byte-progress
    bar (kept the docs counter as a second line for context).
  - Add the "chunk elapsed / est remaining" line.

### Tests

- `tests/unit/tui/test_upload_tab.py`
  - Snapshot with progress at 0% → bar empty, no ETA line.
  - Snapshot at 40% → bar 40% filled, ETA shown.
  - Snapshot at 100% (batch complete) → bar full, ETA hidden.
  - MB values formatted with one decimal up to GB scale.

### Commit

```
feat(tui,observability): UPLOAD tab MB progress + chunk timer (041 Phase 2)
```

## Phase 3 — CHUNKS tab: full stage breakdown (~2h)

### Files

- `src/cmcourier/tui/data_provider.py`
  - Extend each entry in ``chunks_state`` with:
    - ``doc_count`` (already known after S1)
    - ``total_bytes`` (sum of S4 staged file sizes)
    - ``prep_done`` / ``prep_skipped`` / ``prep_failed``
    - ``prep_elapsed_s``
    - ``upload_skipped`` (s5_done / s5_failed already there)
    - ``upload_elapsed_s``
  - The provider aggregates ``stage_complete`` events per stage
    per chunk_id, counting outcomes and accumulating duration.
- `src/cmcourier/tui/chunks_tab.py`
  - Re-render as a wider table with the per-chunk breakdown +
    a TOTAL aggregate row at the bottom.
  - Column widths tuned to fit ~80-column terminals (the rest
    of the TUI assumes 76-80 width).
  - Empty chunks (status QUEUED) show ``—`` placeholders in the
    PREP/UPLOAD columns to avoid bogus zero counts.

### Tests

- `tests/unit/tui/test_chunks_tab.py`
  - Snapshot with 4 chunks at different stages (one DONE, one
    UPLOAD, one PREP, one QUEUED) — asserts the table shape +
    aggregate row totals.
  - All-DONE snapshot — TOTAL row sums correctly.
  - Empty chunks_state — header + "(no chunks yet)" message
    preserved.

### Commit

```
feat(tui,observability): CHUNKS tab expanded per-stage breakdown + totals (041 Phase 3)
```

## Phase 4 — Docs + CHANGELOG 0.44.0 + version bump + FF (~30min)

### Files

- `docs/how-to/local-staging-simulation.md` Step 6 — update the
  "What to watch in TUI" hint with the new MB / timer / breakdown.
- `CHANGELOG.md [0.44.0]` — Added (MB progress, chunk timer,
  CHUNKS breakdown, TOTAL row), Changed (log redirection when
  TUI active), no Removed.
- `README.md` feature row tick.
- `pyproject.toml` 0.43.0 → 0.44.0.

### Smoke

```bash
.venv/bin/cmcourier csv-trigger-pipeline run --config sample/config-staging.yaml --total 10
# (TUI ON by default)
```

Visual check:
- No log spam over the dashboard.
- UPLOAD tab shows MB progress + chunk timer.
- CHUNKS tab shows the breakdown table.

### Commit

```
docs(041): TUI runbook + CHANGELOG 0.44.0 + version bump (041 Phase 4)
```

### FF to main.

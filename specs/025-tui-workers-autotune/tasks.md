# Tasks — 025-tui-workers-autotune

**Status**: Draft
**Spec**: `specs/025-tui-workers-autotune/spec.md`
**Plan**: `specs/025-tui-workers-autotune/plan.md`

---

## Phase 1 — Schema + worker pool + thread-safety

- [ ] **1.1 (R)** Add 6 schema tests to
  `tests/unit/config/test_schema.py`: defaults, min>max
  threads rejected, min>max timeout rejected, enabled=true
  loads, missing block defaults, all numeric range guards.
- [ ] **1.2 (G)** Edit `config/schema.py`:
  - Add `AutoTuneConfig` model per spec REQ-003.
  - Add `workers` + `auto_tune` to `CmisConfigModel`.
  - Add `@model_validator` per REQ-004.
  - Update `__all__`.
- [ ] **1.3 (G)** Create
  `src/cmcourier/services/worker_pool_stats.py`:
  - `WorkerPoolStatsSnapshot` (frozen dataclass).
  - `WorkerPoolStats` (thread-safe, ~80 LOC).
  - `ResizableWorkerPool` (custom thread pool with target
    semaphore per plan §4.3).
- [ ] **1.4 (R)** Add 4 thread-safety tests for
  `WorkerPoolStats` and `ResizableWorkerPool` in
  `tests/unit/services/test_worker_pool_stats.py`.
- [ ] **1.5 (G)** Edit `observability/metrics.py`:
  - Add `threading.Lock` to `_StageBucket`.
  - Add `threading.Lock` to `_SlowOpAggregator._candidates`.
  - Add `_BandwidthSampler` per plan §4.4.
- [ ] **1.6 (G)** Edit `observability/formatter.py`: add
  `"worker"` to `ALLOWED_EXTRA_FIELDS`.
- [ ] **1.7 (G)** Edit `adapters/upload/cmis_uploader.py`:
  - Add `threading.Lock` for `_folder_cache` and `_warm`.
  - Add `worker` field to every network event
    `extra={...}`.
- [ ] **1.8 (R)** Add 4 thread-safety tests in
  `tests/integration/adapters/test_cmis_uploader.py`:
  concurrent ensure_folder, concurrent _warm, concurrent
  upload no duplicate folder POSTs, network event includes
  worker.
- [ ] **1.9 (R)** Create
  `tests/integration/pipeline/test_s5_worker_pool.py` with
  6 tests: N=1 sequential equivalent, N=4 parallel happy,
  exception isolation, graceful shutdown, p95 under
  concurrency, worker label in slow ops.
- [ ] **1.10 (G)** Edit `orchestrators/staged.py`:
  - Read `cmis.workers` from config.
  - Refactor `_stage_s5` to use `ResizableWorkerPool`
    (or ThreadPoolExecutor if custom pool tests stall —
    see plan §7 R2 fallback).
  - Each upload runs in `_upload_one(item, batch_id)`.
  - WorkerPoolStats hooks before/after each upload.
- [ ] **1.11 (G)** Edit `config/wiring.py`: pass
  `WorkerPoolStats` into `StagedPipeline`.
- [ ] **1.12** Run phase-1 tests + full suite (after
  sed-patching tests that fail due to thread races, if any).
  CHECKPOINT.

---

## Phase 2 — Auto-tune controller

- [ ] **2.1 (R)** Create
  `tests/unit/services/test_auto_tune.py` with 5 tests:
  AI under target, MD over target, noop in band, warmup
  honored, timeout adjustment.
- [ ] **2.2 (G)** Create `src/cmcourier/services/auto_tune.py`:
  - `AutoTuneController` per plan §3.2.
  - `_Decision` frozen dataclass.
  - `_next_decision(observed_p95_ms, elapsed_s) -> _Decision`.
  - Background thread loop with `adjustment_interval_s`
    cadence.
- [ ] **2.3 (G)** Wire controller into `StagedPipeline`
  via config. When `config.cmis.auto_tune.enabled=True`,
  start the controller at batch start, stop at batch end.
- [ ] **2.4 (R+G)** Integration test: 20-doc batch with
  auto_tune.enabled=true and target_p95_ms set artificially
  low; assert at least one `auto_tune_decision` event in
  the app log with the expected `action` value.
- [ ] **2.5** Run phase-2 tests + full suite. CHECKPOINT.

---

## Phase 3 — TUI

- [ ] **3.1 (G)** Update `pyproject.toml`: add `textual`
  dependency (pin to a stable version range).
- [ ] **3.2 (G)** Create `src/cmcourier/tui/__init__.py` with
  `__all__ = ["start_tui", "TUIDataProvider"]`.
- [ ] **3.3 (G)** Create `src/cmcourier/tui/data_provider.py`:
  - `TUISnapshot` frozen dataclass.
  - `TUIDataProvider.snapshot()` pulling from MetricsRecorder
    + WorkerPoolStats + cmis_config + auto_tune state.
- [ ] **3.4 (G)** Create `src/cmcourier/tui/chart.py`:
  - `render_sparkline(series, y_max)` returning a multi-line
    string for the bandwidth chart.
- [ ] **3.5 (G)** Create `src/cmcourier/tui/prep_tab.py`:
  - Textual `Static` widget rendering S0..S4 + slow ops.
- [ ] **3.6 (G)** Create `src/cmcourier/tui/upload_tab.py`:
  - S5 progress + WORKERS panel + NETWORK panel + chart +
    recent uploads + slow ops.
- [ ] **3.7 (G)** Create `src/cmcourier/tui/app.py`:
  - `CMCourierTUI(textual.App)` subclass.
  - Two `TabbedContent` panes.
  - `BINDINGS = [("p", "...", "PREP"), ("u", ...),
    ("q", "...", "Quit")]`.
  - 250 ms refresh tick reading `data_provider.snapshot()`.
- [ ] **3.8 (G)** Create `src/cmcourier/cli/_tui_runner.py`:
  - `start_tui_thread(data_provider) -> Thread`
  - `signal_complete(thread, report)` to flip the overlay.
- [ ] **3.9 (R)** Create
  `tests/unit/tui/test_data_provider.py` with 1 smoke test:
  synthetic recorder + pool_stats → `snapshot()` returns
  expected field values.
- [ ] **3.10** Run phase-3 tests. Visual smoke: run
  `cmcourier csv-trigger-pipeline run` in a real terminal,
  confirm tabs work. CHECKPOINT.

---

## Phase 4 — CLI --tui/--no-tui

- [ ] **4.1 (R)** Create
  `tests/integration/cli/test_tui_flag.py` with 3 tests:
  --no-tui works on csv-trigger; --no-tui works on
  single-doc; --tui in non-TTY exits 2.
- [ ] **4.2 (G)** Edit `cli/app.py`:
  - Add `--tui/--no-tui` Click flag-pair (default `tui=True`)
    to every pipeline run command + single-doc.
  - In `_run_pipeline_command`, when tui=True and
    sys.stdin.isatty(), start the TUI thread before
    `pipeline.run()`.
  - When tui=True and NOT a TTY: exit 2 with clear error.
  - When tui=False: existing headless path.
- [ ] **4.3** sed-patch existing CLI tests with `--no-tui`
  (same pattern as 022's `--skip-doctor`):
  - `sed -i 's/"run", "--config"/"run", "--no-tui", "--config"/g'`
    on the relevant files.
  - Multi-line invocations: separate sed for `"run",\n` →
    `"run",\n  "--no-tui",\n`.
- [ ] **4.4** Run full suite. Iterate until green.
- [ ] **4.5** Verify `background` command (024) does NOT
  accept `--tui`. CHECKPOINT.

---

## Phase 5 — Verification + docs + commit + merge FF

- [ ] **5.1** `ruff check src/ tests/` clean.
- [ ] **5.2** `ruff format --check src/ tests/` clean (or apply).
- [ ] **5.3** `mypy src/cmcourier/` clean.
- [ ] **5.4** `pytest --cov=src/cmcourier --cov-report=term`
  — ≥620 pass, cov on new modules ≥80%.
- [ ] **5.5** `pre-commit run --all-files` clean.
- [ ] **5.6** Smoke:
  - `cmcourier --help` lists every command.
  - `cmcourier csv-trigger-pipeline run --help` shows
    `--tui / --no-tui`.
  - `cmcourier background --help` does NOT show `--tui`.
  - Visual: run `csv-trigger-pipeline run` against test
    fixtures with mocked CMIS, confirm tabs + chart render.
- [ ] **5.7** Update `CHANGELOG.md`:
  - Remove TUI bullet from Planned section.
  - Add `[0.27.0] — 2026-05-10` entry.
- [ ] **5.8** Update `README.md` Status checklist: tick
  "Twenty-fifth change: TUI + worker pool + auto-tune".
- [ ] **5.9** PII grep on new content.
- [ ] **5.10** Stage. Commit:
  `feat(orchestrator,services,tui): S5 worker pool + AIMD auto-tune + textual TUI (the spec MVP, §12)`.
- [ ] **5.11** `git checkout main && git merge --ff-only feat/025-tui-workers-autotune && git branch -d feat/025-tui-workers-autotune`.

---

## Verification mapping (REQ → tasks)

| Spec REQ | Tasks |
|----------|-------|
| REQ-001..005 (schema) | 1.1, 1.2 |
| REQ-006..014 (worker pool) | 1.3, 1.4, 1.9, 1.10, 1.11 |
| REQ-015..021 (auto-tune) | 2.1..2.4 |
| REQ-022..023 (bandwidth sampler) | 1.5 |
| REQ-024..031 (TUI) | 3.1..3.10 |
| REQ-032..035 (CLI flags + tests adaptation) | 4.1..4.3 |
| REQ-036..037 (observability worker field) | 1.6, 1.7 |
| REQ-038..043 (test counts) | covered across phases |
| REQ-044..047 (verification) | 5.1..5.4 |

---

## Estimated effort

- Phase 1: 180 min
- Phase 2: 150 min
- Phase 3: 300 min
- Phase 4: 90 min
- Phase 5: 60 min
- **Total**: ~780 min (~13 h)

If a phase exceeds 1.5× its estimate, I'll checkpoint + ask
before continuing.

---

## Notes for the implementor

- **Phase 1 is the foundation.** Get thread-safety right
  before any concurrency. Add the locks even if Python's GIL
  would protect them — the cost is negligible and the project
  may switch to free-threaded later.
- **The custom `ResizableWorkerPool` is the riskiest piece.**
  The fallback is `ThreadPoolExecutor` with replace-the-pool
  resize. If the custom pool tests aren't green in 90 min,
  switch.
- **AIMD is well-trodden algorithmic territory.** Don't get
  clever. The decision logic is 10 LOC; the tests pin the
  behavior.
- **TUI is the biggest single chunk of code.** Keep widgets
  simple. Resist the urge to add color themes / animations.
  The information density is what matters; rendering quality
  is bonus.
- **Test-suite hygiene from 022 applies.** Same sed pattern
  for `--no-tui` rollout. Don't try to make existing tests
  exercise the TUI path; they'd need TTY simulation.
- **textual's `AppTest` may or may not be stable for our use.**
  If the unit test (3.9 + 4.1) breaks, accept a less-strict
  assertion shape (just that the snapshot fields populate
  correctly).
- **CHECKPOINT after each phase.** This change is too big to
  ship without intermediate validation.

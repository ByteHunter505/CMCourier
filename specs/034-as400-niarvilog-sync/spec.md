# 034 — AS400 NIARVILOG coordination (POST-MVP §4, refined)

> Status: **Proposed** — 2026-05-11
> Author: bitBreaker
> Predecessor: 028 (multi-batch), 029 (shared bandwidth)
> POST-MVP roadmap reference: `docs/roadmap/POST-MVP.md §4`
> Supersedes the original §4 design with a richer model.

---

## 1. Summary

The original POST-MVP §4 proposed `AS400TrackingStore` as a
**replacement** for `SQLiteTrackingStore`. That model is too
narrow for the real situation:

* The bank is evaluating CMCourier (Python) **against a parallel
  Java implementation**. Both write to the same shared AS400
  table `RVILIB.NIARVILOG`. Whoever finishes first uploads the
  doc.
* `NIARVILOG` already exists with a fixed schema (PK
  `(SISCOD, TRNNUM, DOCFRM, IMGARC)`, status column with check
  constraint `IN ('N','I','O','F')`).
* CMCourier still needs `SQLiteTrackingStore` for per-batch
  state (resume, granular stage tracking, TUI live data).

So this change ships **hybrid coordination**: SQLite stays as
the local source of truth for **per-batch state**; AS400 becomes
the distributed source of truth for **cross-batch idempotency +
Java competitor coordination**. A single toggle
(`tracking.as400_sync.enabled`) switches the AS400 path on/off.

---

## 2. Motivation

- **The bank requires centralized tracking in AS400** for the
  production migration. Without §4 we can't be the chosen
  solution.
- **Coordination with Java competitor**: while both run in
  evaluation windows, atomic claim on AS400 prevents
  double-upload races.
- **Cross-batch idempotency hardening**: today SQLite lives on
  one workstation. AS400 is centralized + auditable from the
  bank's existing tools.

---

## 3. Scope

### In scope

- New `As400SyncConfig` Pydantic block under
  `pipeline.tracking.as400_sync` with `enabled` toggle +
  connection details + retry policy.
- New module `cmcourier/adapters/tracking/as400_niarvilog.py`
  with `As400NiarvilogStore` class. NOT an `ITrackingStore`
  implementation — it's a coordination layer on top.
- New module `cmcourier/services/idempotency.py` with
  `IdempotencyCoordinator` that owns both the SQLite store and
  (when enabled) the AS400 store, dispatching reads/writes per
  the documented rules.
- Atomic claim via DB2 `UPDATE … WHERE STSCOD='N'` —
  `rowCount == 1` means we won the race.
- Pre-flight sync at pipeline start: read every `NIARVILOG` row
  for the scope of the current batch and reconcile against
  SQLite. Halt on conflict with operator-friendly resolution
  hint.
- New CLI subcommand `cmcourier sync resolve <txn>
  --prefer-as400 | --prefer-local` and `--all` variants for
  bulk resolution.
- `doctor` extension: validates AS400 reachability + presence of
  the `NIARVILOG` table when `enabled=true`.
- Cleanup of stale `STSCOD='I'` rows on pre-flight (rows whose
  `FINREI` exceeds `stale_in_progress_minutes`).
- Retry / backoff for transient AS400 errors: 3 attempts (5s /
  30s / 5min) then fail with exit 2.
- ≥18 unit tests + ≥3 integration tests (pyodbc faked at the
  driver boundary per Constitution VI — the AS400 *server* is
  not mocked; we mock the connection object).

### Out of scope

- The CSV split refactor (MapeoRVI_CM.csv + MetadatosCM.csv +
  `CMISType` column). Documented as **035 follow-up**. For
  034, we keep reading the consolidated
  `modelo_documental.csv` fixture and add `cmis_type: str = ""`
  to `CMMapping` with a default. The `TIPIDN` column in
  NIARVILOG receives that default empty string until 035
  populates it.
- Multi-page docs are one row per **logical document** in
  NIARVILOG (Option B confirmed by the operator). `IMGARC` is
  the first page's source file. Page-level granularity stays
  in SQLite where the state machine needs it.
- Bidirectional sync (push SQLite → AS400 on first
  enable). Operators can run `cmcourier sync push-local`
  manually if needed (documented as a Phase-4 nice-to-have if
  time permits, else 036).
- Java competitor's contract specifics. We assume they obey
  the same `STSCOD` semantics and atomic UPDATE pattern.
- Schema migration SQL for AS400. Assumed to already exist
  in the bank's environment.

---

## 4. Requirements

### Configuration (Phase 1)

- **REQ-001**: New `As400SyncConfig` Pydantic model under
  `pipeline.tracking.as400_sync`:
  ```
  enabled: bool = False
  connection: As400ConnectionConfig (host, library, etc.)
  library: str = "RVILIB"
  table: str = "NIARVILOG"
  stale_in_progress_minutes: int = Field(default=30, ge=1, le=1440)
  retry_attempts: int = Field(default=3, ge=1, le=10)
  retry_base_delay_s: float = Field(default=5.0, gt=0)
  ```
- **REQ-002**: `tracking.as400_sync.enabled = false` (default)
  preserves byte-identical behavior vs pre-034.
- **REQ-003**: ≥5 schema tests cover defaults, custom values,
  range validation, missing connection when enabled raises.

### Field mapping (Phase 1, locked)

| AS400 column | ← | Source |
|---|---|---|
| `SISCOD CHAR(1)` | ← | `trigger.system_id` |
| `TRNNUM CHAR(7)` | ← | `document.txn_num` |
| `DOCFRM CHAR(30)` | ← | `document.index7` (ABAHCD) |
| `IMGARC CHAR(12)` | ← | `document.file_name` (first page) |
| `IMGTIP CHAR(1)` | ← | `document.image_type` |
| `CTECIF VARCHAR(30)` | ← | `trigger.shortname` |
| `CTENUM DECIMAL(9,0)` | ← | `int(trigger.cif or 0)` |
| `STSCOD CHAR(1)` | ← | derived (`N`/`I`/`O`/`F`) |
| `IDNBAC VARCHAR(10)` | ← | `mapping.id_corto` (== IDCM) |
| `TIPIDN VARCHAR(128)` | ← | `mapping.cmis_type` (defaults to `""` until 035) |
| `OBJIDN VARCHAR(128)` | ← | `record.cm_object_id` (post-S5) |
| `NUMREI INTEGER` | ← | `record.retry_count` |
| `PMRREI TIMESTAMP` | ← | `record.started_at` or `CURRENT_TIMESTAMP` |
| `FINREI TIMESTAMP` | ← | DB2 auto-update |
| `EERRMSG VARCHAR(1024)` | ← | `record.error_message` |

### Status derivation (Phase 2)

- **REQ-004**: STSCOD transitions:
  - `N` — initial state (insert default, document not yet
    claimed by any worker).
  - `I` — claimed by us (any `S0..S4` stage in flight, or
    `S5_PENDING`). Written by `try_claim`.
  - `O` — `S5_DONE`. Written by `mark_uploaded` with the CMIS
    `OBJIDN`.
  - `F` — any `S*_FAILED`. Written by `mark_failed` with the
    error message. `NUMREI` incremented.

### As400NiarvilogStore (Phase 2)

- **REQ-005**: `try_claim(record) -> bool` issues `UPDATE
  NIARVILOG SET STSCOD='I', PMRREI=CURRENT_TIMESTAMP, IDNBAC=?,
  TIPIDN=? WHERE SISCOD=? AND TRNNUM=? AND DOCFRM=? AND
  IMGARC=? AND STSCOD='N'`. Returns `True` if `rowCount==1`,
  else `False`.
- **REQ-006**: When the row doesn't exist yet (first-time
  process for this doc), `try_claim` does an `INSERT` of a row
  with `STSCOD='I'`. Race: two processes inserting at once →
  DB2 unique-constraint violation on PK → catch + retry the
  `UPDATE`-style path → at most one wins.
- **REQ-007**: `mark_uploaded(txn, cm_object_id) -> None`
  issues `UPDATE … SET STSCOD='O', OBJIDN=?, EERRMSG=''`.
  Logs WARNING if `rowCount != 1` (means someone changed our
  row between claim and upload — investigate but don't fail).
- **REQ-008**: `mark_failed(txn, error) -> None` issues
  `UPDATE … SET STSCOD='F', EERRMSG=?, NUMREI=NUMREI+1`.
- **REQ-009**: `read_state(txn) -> NiarvilogRow | None` issues
  a SELECT and returns the row or None.
- **REQ-010**: `cleanup_stale_in_progress() -> int` issues
  `UPDATE … SET STSCOD='N' WHERE STSCOD='I' AND FINREI < (NOW
  - stale_in_progress_minutes)`. Returns row count.

### IdempotencyCoordinator (Phase 3)

- **REQ-011**: `IdempotencyCoordinator(sqlite_store,
  as400_store=None)`. When `as400_store is None`, behavior is
  byte-identical to pre-034 (just delegates to SQLite).
- **REQ-012**: `is_uploaded(txn) -> bool` — when AS400 is
  active, returns `as400.read_state(txn).status == 'O'`. Else
  delegates to SQLite.
- **REQ-013**: `try_claim(record) -> bool` — when AS400 is
  active, calls `as400.try_claim()`. Returns `False` is
  "skip this doc, someone else is doing it or it's done". When
  AS400 inactive, always returns `True` (no distributed
  claim).
- **REQ-014**: `mark_uploaded(record, cm_object_id)` — calls
  SQLite's `mark_stage_done(..., S5_DONE)` AND (when active)
  `as400.mark_uploaded`. Errors on AS400 side trigger retry
  before failing.
- **REQ-015**: `mark_failed(record, stage, error)` — same
  dual-write pattern.
- **REQ-016**: `preflight_sync(batch_scope) -> SyncReport`:
  reads every NIARVILOG row whose `TRNNUM` is in the batch
  scope and reconciles against SQLite. Returns:
  - `imported_from_as400`: txn_nums where AS400 said `O` but
    SQLite had no row — inserted as `S5_DONE` in SQLite with
    OBJIDN.
  - `conflicts`: txn_nums where SQLite says `S5_DONE` but
    AS400 disagrees (or vice versa).
  - `stale_cleaned`: count of `STSCOD='I'` rows reset by the
    cleanup step.

### Pre-flight conflict policy (Phase 3)

- **REQ-017**: If `SyncReport.conflicts` is non-empty, the
  pipeline aborts with exit 2 and a clear message:
  ```
  ConflictError: 3 conflicts between SQLite and AS400.
  Resolve with `cmcourier sync resolve --prefer-as400-all`
  or per-txn `cmcourier sync resolve <txn> --prefer-local`.
  ```
- **REQ-018**: Pre-flight runs only when
  `as400_sync.enabled == true`.

### CLI `sync resolve` (Phase 4)

- **REQ-019**: New CLI group `cmcourier sync`:
  - `cmcourier sync resolve <txn> --prefer-as400 --config c.yaml`:
    overwrite SQLite to match AS400 for the given txn.
  - `cmcourier sync resolve <txn> --prefer-local --config c.yaml`:
    push SQLite state to AS400 (`UPDATE STSCOD=?,
    OBJIDN=?`) for the given txn.
  - `cmcourier sync resolve --all --prefer-as400 --config c.yaml`:
    bulk resolve all conflicts in favor of AS400.
- **REQ-020**: ≥4 CLI tests for the resolve flows.

### Retry / backoff (Phase 5)

- **REQ-021**: All NIARVILOG writes (`try_claim`,
  `mark_uploaded`, `mark_failed`, `cleanup_stale_in_progress`)
  retry on transient errors (`pyodbc.OperationalError`) up to
  `retry_attempts` times with `retry_base_delay_s *
  2^(attempt-1)` capped at 5 minutes.
- **REQ-022**: On final failure, raise
  `As400UnreachableError` with the underlying pyodbc message.
  The pipeline aborts with exit 2.

### Doctor (Phase 1)

- **REQ-023**: `cmcourier doctor --check tracking` (or a new
  `--check as400-sync` group) validates:
  - `as400_sync.enabled == false` → SKIP (no AS400 needed).
  - `enabled == true` → CONNECT to AS400, confirm `NIARVILOG`
    table exists, confirm schema matches (columns + check
    constraint), return PASS/FAIL.

### Tests

- **REQ-024**: ≥5 schema tests.
- **REQ-025**: ≥8 `As400NiarvilogStore` unit tests with
  pyodbc faked at the cursor/connection boundary (same
  pattern as `As400DataSource` tests).
- **REQ-026**: ≥5 `IdempotencyCoordinator` unit tests
  including the AS400-disabled regression path.
- **REQ-027**: ≥3 CLI integration tests for `sync resolve`.
- **REQ-028**: ≥1 end-to-end test where pre-flight sync
  imports an OBJIDN from AS400 into a fresh SQLite.
- **REQ-029**: 1 conflict-detection test asserting exit 2
  with the right hint.

### Verification

- **REQ-030**: `pytest` clean (target ≥770 tests passing
  cumulative).
- **REQ-031**: `mypy src/cmcourier/` clean.
- **REQ-032**: `ruff check` + `ruff format --check` clean.
- **REQ-033**: `docs/how-to/as400-sync.md` exists with
  enabling instructions, conflict resolution playbook, and
  the field mapping table.

---

## 5. Acceptance scenarios

1. **Toggle OFF (default)**: A YAML without
   `tracking.as400_sync.enabled` (or with `enabled: false`)
   produces byte-identical output to pre-034. Existing tests
   keep passing untouched.
2. **Toggle ON, no Java**: With `enabled: true` and a clean
   AS400, the pipeline runs end-to-end, inserts rows in
   NIARVILOG as it claims, transitions them to `O` on S5 done.
3. **Toggle ON, Java already uploaded**: A doc has
   `STSCOD='O'` in NIARVILOG. Pre-flight detects it. SQLite is
   updated as `S5_DONE` with the OBJIDN. The pipeline skips
   that doc.
4. **Toggle ON, race with Java**: Two processes try to claim
   the same `STSCOD='N'` row. Atomic UPDATE means one wins
   (`rowCount==1`), the other gets `rowCount==0` and skips.
5. **Conflict detected**: SQLite says `S5_DONE` for a txn but
   AS400 says `N`. Pre-flight halts with exit 2 + resolution
   hint.
6. **`sync resolve --prefer-as400`**: Operator resolves a
   conflict. SQLite row updated to match AS400; pipeline
   restartable.
7. **AS400 unreachable**: Network drop mid-run triggers retry
   (5s, 30s, 5min). After 3 fails, exit 2 with
   `As400UnreachableError`.
8. **Stale `STSCOD='I'` cleanup**: A row left at `I` for >30
   minutes is reset to `N` by pre-flight. The next run picks
   it up normally.

---

## 6. Risks

- **`stale_in_progress_minutes` tuning**: 30 min default is a
  guess. If a real S5 upload routinely takes >30 min for a
  huge PDF, we'd self-clobber. Documented in how-to; can be
  re-tuned without code changes.
- **`IMGARC` is first page only**: a doc's identity in
  NIARVILOG is tied to `.001`. If RVABREP ever changes that
  convention, the PK matching breaks. Low risk per operator
  confirmation (RVABREP only emits the first page row).
- **TIPIDN defaults to `""` until 035**: production runs
  before 035 ships will have empty TIPIDN in their rows. The
  Java competitor needs to tolerate this. Documented.
- **Java competitor schema drift**: if Java assumes columns
  we don't write (or vice versa), behavior diverges. The
  doctor check validates schema explicitly.

---

## 7. Dependencies

- **Hard**: `As400ConnectionConfig` already exists (014).
  pyodbc thread-local pattern from `As400DataSource` is
  reused.
- **Soft**: 035 (CSV split + CMISType column) populates
  TIPIDN with real values. Until then, `TIPIDN = ''`.

---

## 8. Estimate

~12–15 hours across six phases (see `plan.md`).

# How to: AS400 NIARVILOG distributed idempotency

> Available since change **034** (2026-05-11). POST-MVP §4 —
> coordinate cross-batch idempotency with the bank's centralized
> ``RVILIB.NIARVILOG`` table while keeping SQLite as the
> per-batch state machine.

---

## When to enable this

Turn it ON when **at least one** of these applies:

* The bank requires migration tracking centralized in AS400
  (compliance / audit).
* CMCourier and a parallel implementation (e.g. a competing
  Java migrator) are evaluated in alternating windows on the
  same scope — distributed claim prevents double upload.
* Operators run CMCourier from multiple workstations and the
  per-workstation SQLite is not enough.

Turn it OFF (the default) when:

* You're running locally for dev / staging / dry-run.
* The bank confirmed SQLite local tracking is sufficient.

---

## TL;DR config

```yaml
tracking:
  db_path: /var/lib/cmcourier/tracking.db   # SQLite stays as-is
  as400_sync:
    enabled: true                            # ← the toggle
    connection:
      host: as400.bank.example
      port: 446
      database: RVILIB
      driver: "iSeries Access ODBC Driver"
    library: RVILIB                          # default
    table: NIARVILOG                         # default
    columns:                                 # 049 — per-environment names
      # omit entirely → canonical names; override only what differs
      status_column: ESTADO
      txn_num_column: NUMTRX
    stale_in_progress_minutes: 30            # cleanup STSCOD='I' rows
    retry_attempts: 3                        # transient OperationalError
    retry_base_delay_s: 5.0                  # exponential backoff
```

Credentials live in env vars (same as the AS400 trigger):
``AS400_USERNAME``, ``AS400_PASSWORD``.

When ``enabled: true``, ``cmcourier doctor`` validates the
connection + the existence of ``RVILIB.NIARVILOG``. Run it
before any pipeline run:

```bash
cmcourier doctor --config prod.yaml --check as400_sync
```

---

## Field mapping (locked)

CMCourier writes each NIARVILOG column from the following
source. Pre-conditions are enforced by the bank's schema
constraints — make sure your fixtures match:

| AS400 column | ← | CMCourier source | Notes |
|---|---|---|---|
| ``SISCOD CHAR(1)`` | ← | ``trigger.system_id`` | 1 char exact |
| ``TRNNUM CHAR(7)`` | ← | ``document.txn_num`` | = RVABREP ``ABAANB``; 7 chars exact |
| ``DOCFRM CHAR(30)`` | ← | ``document.index7`` | = RVABREP ``ABAHCD`` (tipo RVI, ej ``CC03``) |
| ``IMGARC CHAR(12)`` | ← | ``document.file_name`` | First-page source file, ej ``DAAAH9X4.001`` |
| ``IMGTIP CHAR(1)`` | ← | ``document.image_type`` | ej ``B`` (TIFF), ``O`` (PDF) |
| ``CTECIF VARCHAR(30)`` | ← | ``trigger.shortname`` | The bank's "shortname" field |
| ``CTENUM DECIMAL(9,0)`` | ← | ``int(trigger.cif or 0)`` | CIF as numeric |
| ``STSCOD CHAR(1)`` | ← | derived | ``N`` / ``I`` / ``O`` / ``F`` |
| ``IDNBAC VARCHAR(10)`` | ← | ``mapping.id_corto`` | ID de CM, ej ``CN01`` |
| ``TIPIDN VARCHAR(128)`` | ← | ``mapping.cmis_type`` | From ``MapeoRVI_CM.CMISType`` in split mode (035); ``""`` in consolidated mode if absent |
| ``OBJIDN VARCHAR(128)`` | ← | ``record.cm_object_id`` (post-S5) | The CMIS object id |
| ``NUMREI INTEGER`` | ← | ``record.retry_count`` | Retry counter |
| ``PMRREI TIMESTAMP`` | ← | claim time | ``CURRENT_TIMESTAMP`` on INSERT |
| ``FINREI TIMESTAMP`` | ← | DB2 auto-update | Implicit via ``ROW CHANGE TIMESTAMP`` |
| ``EERRMSG VARCHAR(1024)`` | ← | ``record.error_message`` | Truncated to 1024 |

### Per-environment column names (049)

The table above lists the **canonical** physical column names. The
bank runs CMCourier against several AS400 environments whose
NIARVILOG table has the same 15 columns under **different physical
names**. Map them with ``tracking.as400_sync.columns`` — one logical
key per column, defaulting to the canonical name:

| `columns.*` key | canonical default | logical meaning |
|---|---|---|
| ``system_id_column`` | ``SISCOD`` | trigger system id |
| ``txn_num_column`` | ``TRNNUM`` | RVABREP txn number |
| ``doc_format_column`` | ``DOCFRM`` | RVI doc type |
| ``image_archive_column`` | ``IMGARC`` | first-page file name |
| ``image_type_column`` | ``IMGTIP`` | image type |
| ``client_cif_column`` | ``CTECIF`` | client shortname |
| ``client_num_column`` | ``CTENUM`` | CIF as numeric |
| ``status_column`` | ``STSCOD`` | N / I / O / F state |
| ``idcm_column`` | ``IDNBAC`` | CM short id |
| ``cm_type_column`` | ``TIPIDN`` | CMIS type |
| ``cm_object_id_column`` | ``OBJIDN`` | CMIS object id |
| ``retry_count_column`` | ``NUMREI`` | retry counter |
| ``started_at_column`` | ``PMRREI`` | claim timestamp |
| ``finished_at_column`` | ``FINREI`` | DB2 row-change timestamp |
| ``error_message_column`` | ``EERRMSG`` | last error |

Omit the ``columns`` block entirely and every name stays canonical —
the emitted SQL is byte-identical to pre-049. Override only the keys
that differ in your environment.

**Identifier validation.** These names — plus ``library`` and
``table`` — are interpolated directly into SQL (a SQL identifier can
never be a ``?`` bind-param). Every one is validated at config-load
time against the DB2-for-i ordinary identifier grammar
(``letter / @ / # / $`` then ``letters / digits / _ / @ / # / $``,
128 chars max). A name with a space, quote, semicolon, leading
digit, or over-length raises a ``ConfigurationError`` before any
connection is opened.

### Status transitions

```
        (no row yet)
              │
              ▼  try_claim → INSERT (rowcount=1)
            ┌─────┐
            │  I  │ ← in progress (we own it)
            └──┬──┘
        upload ok                 upload failed
              │                          │
              ▼                          ▼
            ┌─────┐                  ┌─────┐
            │  O  │ ← done           │  F  │ ← failed
            └─────┘                  └─────┘
                                        │
                                        ▼  cleanup_stale (after 30 min)
                                      ┌─────┐
                                      │  N  │ ← reclaimable
                                      └─────┘
```

The ``cleanup_stale_in_progress`` pre-flight resets rows stuck
in ``I`` for longer than ``stale_in_progress_minutes`` back to
``N`` — recovers from any process that crashed mid-claim.

---

## Concurrency model

When ``enabled: true``, the pipeline's S5 stage does this for
each doc:

1. ``UPDATE NIARVILOG SET STSCOD='I' WHERE …PK… AND STSCOD='N'``.
2. If ``rowcount == 1`` → we won the claim; proceed.
3. If ``rowcount == 0`` → the row is missing **or** in
   ``I/O/F``. Try ``INSERT`` with ``STSCOD='I'``.
4. ``IntegrityError`` on INSERT → someone else inserted first
   (race lost) → skip this doc and log ``as400_claim_lost``.

This is **DB2-level atomicity**: two processes hitting the same
row see deterministic exclusive ownership. The bank's parallel
Java migrator can use the same protocol without changes.

After the upload:

* Success → SQLite ``S5_DONE`` + ``UPDATE STSCOD='O', OBJIDN=?``.
* Failure → SQLite ``S5_FAILED`` + ``UPDATE STSCOD='F', EERRMSG=?, NUMREI=NUMREI+1``.

SQLite is written **first** (it's the in-process resume
anchor), AS400 second.

---

## Pre-flight reconciliation

When the pipeline starts and the toggle is on, the
``IdempotencyCoordinator`` does:

1. ``cleanup_stale_in_progress`` — reset old ``I`` rows.
2. For each txn in the batch scope:
   * ``read_state_by_txn(trnnum)`` returns the NIARVILOG row.
   * Compare with SQLite's ``is_uploaded(txn)``.
   * Three outcomes:
     * **Imported**: AS400 says ``O``, SQLite has no row →
       record it (the operator can re-run the pipeline; the
       in-process resume sees AS400 ``O`` and skips).
     * **Conflict**: AS400 says ``N/I/F``, SQLite says
       uploaded → operator-driven resolution (next section).
     * **Consistent**: no action.

If conflicts are non-empty, the pipeline aborts with exit 2.

---

## Conflict resolution playbook

Conflicts surface only when the two stores disagree on a
"is this doc done?" terminal state. Resolve with the new
``cmcourier sync`` subcommand.

### Inspection

```bash
cmcourier sync status --config prod.yaml
# sync status: stale_cleaned=2
```

Read-only: runs the cleanup + tells you how many ``I`` rows
were reset.

### Prefer AS400 (most common)

When AS400 has the authoritative ``O`` state but local SQLite
doesn't know:

```bash
cmcourier sync resolve 0001234 --prefer-as400 --config prod.yaml
# resolved 0001234: imported AS400 state — STSCOD='O', OBJIDN='cm-abc-xyz'
```

This **prints** the AS400 state but doesn't write SQLite
directly. Operator then re-runs the pipeline with
``--resume`` — the in-process logic sees AS400 ``O`` and
skips the doc cleanly. This avoids extending the SQLite
``ITrackingStore`` API just for the resolve flow.

### Prefer local (rare)

When SQLite uploaded the doc but AS400 missed the update
(e.g. AS400 was down during S5):

```bash
cmcourier sync resolve 0001234 \
  --prefer-local \
  --cm-object-id cm-abc-xyz \
  --config prod.yaml
# resolved 0001234: pushed local cm_object_id='cm-abc-xyz' to AS400.
```

The ``--cm-object-id`` is **required** — get it from
``cmcourier batch show <batch_id>``. The UPDATE only fires if
the row already exists in NIARVILOG; if it doesn't, re-run
the pipeline so ``try_claim`` inserts it.

---

## Retry / backoff

Transient ``pyodbc.OperationalError`` (network drops, deadlocks,
"server temporarily unavailable") triggers automatic retry:

* Attempts: ``retry_attempts`` from the YAML (default 3).
* Delay: ``retry_base_delay_s * 2^(attempt-1)`` capped at
  5 minutes. Default sequence: 5s, 10s, 20s.
* Between attempts, the cached connection is reset (most
  transient errors leave the connection in an unusable state).
* After the final attempt fails → ``As400UnreachableError``
  raised; the pipeline aborts with exit 2.

``IntegrityError`` is **never** retried — it's the
race-detection signal for ``try_claim``. Other ``pyodbc.Error``
subclasses (schema mismatches, syntax errors) are propagated
as ``As400CoordinationError`` immediately.

---

## Operational knobs reference

| YAML field | Default | Description |
|---|---|---|
| ``enabled`` | ``false`` | Master toggle. ``true`` activates everything below. |
| ``connection`` | required when enabled | AS400 ODBC params (host, port, database, driver). |
| ``library`` | ``RVILIB`` | DB2 schema name. Validated as a DB2 identifier. |
| ``table`` | ``NIARVILOG`` | Table name. Override if the bank renamed it. Validated as a DB2 identifier. |
| ``columns`` | canonical names | Per-environment physical column-name map — see [Per-environment column names](#per-environment-column-names-049). Each value validated as a DB2 identifier. |
| ``stale_in_progress_minutes`` | ``30`` | How long an ``I`` row can sit before pre-flight resets it. |
| ``retry_attempts`` | ``3`` | Total attempts per write (incl. the first). Range: 1..10. |
| ``retry_base_delay_s`` | ``5.0`` | Base for exponential backoff. Must be > 0. |

---

## Known limitations (intentional)

* **One row per txn**: per the bank's operational convention,
  NIARVILOG has at most one row per ``TRNNUM`` (the first
  page's ``IMGARC``). Multi-page docs share a single row.
  Confirmed with the operator in spec 034.
* **``sync resolve --prefer-as400`` doesn't write SQLite
  directly** in 034 — operator re-runs the pipeline with
  ``--resume``. Direct write can be added in a future change
  if the workflow proves cumbersome.
* **``sync resolve --prefer-local`` requires
  ``--cm-object-id`` explicit**. The operator gets it from
  ``cmcourier batch show`` — avoids extending
  ``ITrackingStore`` with a ``find_record_by_txn`` surface
  that's only used here.

---

## Cross-references

* POST-MVP roadmap entry: ``docs/roadmap/POST-MVP.md`` §4.
* Spec: ``specs/034-as400-niarvilog-sync/``.
* Mapping CSV split: change 035 (``MapeoRVI_CM.csv`` +
  ``MetadatosCM.csv`` + ``CMISType`` column —
  see ``specs/035-mapping-csv-split/`` and ``MappingConfig``
  in ``docs/configuration-guide.md``).
* Related: change 014 (AS400 trigger source — same pyodbc
  pattern), change 028 (multi-batch — claim happens
  inside ``_upload_one``).

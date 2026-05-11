# How-to: Staging dry-run

A staging dry-run validates the combination **code + config + real data**
against a non-production CMIS repository **before** the first production
migration. It surfaces the bugs that no synthetic test can catch:
encoding quirks, CMIS connectivity, mapping coverage, performance
characteristics on actual link bandwidth, AS400 schema drift.

This runbook is **generic** — it applies to any staging environment
(bank-provided CMIS staging, our own Alfresco simulation, a future
multi-tenant test instance). For the specific local Alfresco-on-Docker
setup, see `docs/how-to/local-staging-simulation.md`.

---

## Prerequisites

1. **Staging CMIS URL + credentials** in env vars `CMIS_USERNAME` /
   `CMIS_PASSWORD`.
2. **Sample of RVABREP rows** — CSV exported from production AS400 or
   an ODBC replica. 100-1000 rows minimum to exercise lanes (036) +
   multi-batch (028).
3. **Sample of source files** — TIFFs / PDFs reachable via the
   configured `assembly.source_root` path.
4. **Production mapping CSVs** — `MapeoRVI_CM.csv` + `MetadatosCM.csv`
   from the bank, OR our synthetic dataset for simulation.
5. **An empty SQLite tracking DB** under `tracking.db_path` — drops
   on every run keeps batches isolated.

## The seven steps

The dry-run runs as a **gated cascade**. Each step has a **stop
condition**: if it fails, fix and retry before advancing. Don't skip
ahead — a step-3 failure on top of a step-2 failure can mask root
causes.

### Step 0 — `cmcourier doctor`

```bash
cmcourier doctor -c config-staging.yaml
```

The six pre-flight checks (REBIRTH §10.5):

1. `log_dir_writable` — ./logs is writable.
2. `cmis_connectivity` — staging CMIS responds.
3. `tracking_openable` — SQLite opens with WAL mode.
4. `mapping_completeness` — Modelo Documental has ≥1 row.
5. `metadata_sources` — every CSV alias source loads ≥1 row.
6. `cm_type_alignment` — every distinct `cm_object_type` derived from
   the mapping resolves via CMIS `getTypeDefinition`. **The most
   discriminating check** — failure here means types are missing on
   staging, or you need the `cmis_type` override (039) to map them to
   a generic type.
7. `sample_dry_run` — S1→S4 walk on the first trigger's first doc.

**Stop condition**: any FAIL except a SKIPped `sample_dry_run` (which
happens when the trigger has no docs, OK on dataset issues we know
about). Fix the failing check; rerun.

### Step 1 — One doc end-to-end

```bash
cmcourier rvabrep-pipeline run -c config-staging.yaml --total 1
```

The pipeline runs S0→S5 for **exactly one doc**. The first true upload.

**Validate post-run**:
- The doc appears in CMIS staging under the expected folder path.
- Its `cmis:objectTypeId` matches what we set (the override target if
  used, the derived value otherwise).
- Its properties contain the resolved metadata.
- `tracking.db` has one row at `S5_DONE` with the CMIS object id.
- If `metadata.cache.enabled = true`, `document_cache` has the entry.

**Stop condition**: anything wrong. **One doc is your alignment
opportunity** — at scale these problems compound.

### Step 2 — 100 docs with TUI

```bash
cmcourier rvabrep-pipeline run -c config-staging.yaml --total 100 --tui
```

The TUI shows live throughput, p95 latency, AIMD decisions, bandwidth
usage, slow ops.

**What to watch**:
- **PREP tab**: any S0-S4 stage that takes meaningfully more time
  than its theoretical lower bound is a bug or a bad config.
- **UPLOAD tab**: p95 should be < `cmis.auto_tune.target_p95_ms`
  (default 5 s). If AIMD keeps shrinking workers, the CMIS staging
  link or your config is the bottleneck.
- **Bandwidth chart**: current vs ceiling. If always at ceiling, the
  bandwidth cap is the bottleneck — bump `cmis.max_bandwidth_mbps`
  or accept the SLA.
- **Cache hit rate** (if enabled): structured `document_cache_hit /
  miss` events in `logs/pipeline-<date>.jsonl`.

**Stop condition**: failures > 0, memory monotonically increasing
beyond the staged-batch size, AIMD oscillates without converging.

### Step 3 — Analyze

```bash
cmcourier analyze batch <batch_id> -c config-staging.yaml
```

Per-stage p50/p95/p99, slow ops by kind (`cmis_upload`,
`s4_assembly`), lane rebalances (if dual mode is on), cache hits.

**Decisions data**:
- `cmis.workers` — if AIMD converged on a value, use that as the
  static default in production.
- `cmis.max_bandwidth_mbps` — bench-tested with `--total 100`,
  document the headroom.
- `heavy_threshold_bytes` (036) — pick the inflection point of the
  observed size distribution.
- `metadata.cache.ttl_minutes` (037) — match observed re-use pattern.

### Step 4 — 1000 docs (or full sample)

```bash
cmcourier rvabrep-pipeline run -c config-staging.yaml --total 1000
```

Scale validation. The numbers from Step 3 should hold linearly. If
throughput drops past N=500, hunt the bottleneck:

- CMIS server saturated → ask staging admin
- Local disk IO → check `iostat`
- SQLite tracking contention → look at the writer queue depth
- Bandwidth limiter holding things back → check current vs ceiling

### Step 5 — Multi-batch (optional, if shipping 028)

```bash
cmcourier rvabrep-pipeline run -c config-staging.yaml --batch-size 250 --total 1000 --tui
```

Triggers 4 batches × 250 docs with the multi-batch orchestrator (N=2
overlap). Validates `CHUNKS` tab + cross-batch coordination.

### Step 6 — Failure injection (optional)

Manually stop staging CMIS mid-run. Verify:
- Retries fire (`cmis_upload_retry` events in network log).
- After staging recovers, no doc is double-uploaded (cross-batch
  idempotency via `tracking.is_uploaded`).
- `cmcourier batch retry-failed <batch_id>` resumes cleanly.

### Step 7 — Sign-off

Document the run:

```bash
cmcourier batch show <batch_id> -c config-staging.yaml > runs/$(date -I)-batch-show.txt
cmcourier analyze batch <batch_id> -c config-staging.yaml --format json > runs/$(date -I)-analyze.json
```

Tag the commit hash of the build that ran. Decide: **green-light for
production migration, or schedule a fix sprint**.

---

## Common findings (catalogue)

After enough dry-runs you start seeing patterns:

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Doctor `cm_type_alignment` fails on all types | Staging doesn't have the bank's IBM CM types (or you're against Alfresco) | Use `cmis_type` override (039) — set `CMISType=cmis:document` on the mapping rows for staging only |
| S3 latency >> expected | A field source (AS400 query or large CSV) re-runs per doc | Enable `metadata.cache.enabled` (037) or fix the field-source's lookup path |
| Upload 400 "property not declared" | Alfresco staging without a Content Model that declares custom properties | Deploy `scripts/staging/cmcourier-model.xml` (see local-staging-simulation.md) OR set staging to use only `cmis:document` and strip custom properties |
| TUI shows AIMD oscillating workers between min/max | `target_p95_ms` is set lower than what the staging link can deliver | Raise `cmis.auto_tune.target_p95_ms` |
| Multi-batch (028) hangs after 1 batch | Tracking writer queue drained but batch coordination stuck | Check `tracking.flush` is being called between batches |
| Random `Connection pool is full` warnings | `cmis.workers > pool_size` (pre-038) | Update to 0.39.0+; `pool_size` is auto-sized to `auto_tune.max_threads` |

---

## Cross-references

- Specific Alfresco simulation: `docs/how-to/local-staging-simulation.md`.
- Doctor command: REBIRTH §10.5, `src/cmcourier/cli/doctor.py`.
- Cache observability: `docs/how-to/document-cache.md`.
- Multi-batch observability: `docs/how-to/multi-batch.md`.
- Log analysis: `docs/how-to/log-analysis.md`.

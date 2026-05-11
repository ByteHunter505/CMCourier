# How-to: Cross-batch metadata cache (037, POST-MVP §9)

Skip S3 (Metadata Resolution) on a re-run of the same document when
the resolved properties have not gone stale. Default is OFF —
single-batch behavior is byte-identical to pre-037.

## When to turn this on

Enable when:

- You re-run pipelines often against overlapping batches
  (e.g., resume after a partial S5 failure, or migrate a long
  backlog by chunks).
- S3 latency dominates a run because field sources are expensive
  (AS400 queries, large CSV scans).
- Your metadata sources are **stable** within the TTL window.

Leave off when:

- Field sources change unpredictably (CSV imports rolling in every
  minute). Stale-but-served metadata could land on CMIS.
- Your only run is the first migration ever — there is nothing to
  re-use.

## What it caches

After every successful S3 the resolved properties + the (possibly
healed) trigger CIF are upserted into a SQLite table
`document_cache` keyed by:

- `txn_num` — the RVABREP transaction.
- `fields_hash` — SHA-256 of the sorted `required_metadata_fields`
  list for this document's mapping. If the mapping changes the
  required fields, the hash changes, and the cache misses — so
  evolving the mapping never serves an incomplete metadata set.

Storage lives in the same database file as the tracking log
(`tracking.db_path`). One file to back up, one connection pool.

## Configuration

```yaml
metadata:
  cache:
    enabled: true              # default: false
    ttl_minutes: 60            # default: 60 ; range: 1..43200 (30 days)
  # ... field_sources, sources, prefetch_enabled ...
```

The TTL is measured from `cached_at` (UTC ISO-8601). A hit whose age
exceeds `ttl_minutes` is treated as a miss and the resolver runs
again.

## Inspecting the cache

```text
$ cmcourier cache stats -c config.yaml
document_cache rows : 2143
oldest cached_at    : 2026-05-10T09:12:43+00:00
newest cached_at    : 2026-05-11T17:54:01+00:00
```

JSON form for piping to `jq`:

```text
$ cmcourier cache stats -c config.yaml --format json
{
  "total_rows": 2143,
  "oldest_cached_at": "2026-05-10T09:12:43+00:00",
  "newest_cached_at": "2026-05-11T17:54:01+00:00"
}
```

In-process hit / miss counters are surfaced in the pipeline JSONL
log via the `document_cache_hit` and `document_cache_miss` events:

```json
{"event": "document_cache_hit",  "txn_num": "1234567", "age_s": 312.4, "fields_hash": "abc..."}
{"event": "document_cache_miss", "txn_num": "1234568", "reason": "absent", "fields_hash": "abc..."}
{"event": "document_cache_miss", "txn_num": "1234567", "reason": "expired", "age_s": 3700.1, ...}
```

`cmcourier analyze batch <id>` aggregates these for offline review.

## Clearing the cache

```bash
# Invalidate one document (e.g., after manually correcting metadata).
cmcourier cache clear -c config.yaml --txn 1234567

# Wipe the entire cache (e.g., after a mapping schema change you do
# not want to wait for TTL on).
cmcourier cache clear -c config.yaml --all

# Periodic housekeeping: drop entries older than 24 hours.
cmcourier cache clear -c config.yaml --older-than 1440
```

`--all`, `--txn`, and `--older-than` are mutually exclusive; the CLI
errors out (exit code 2) if you pass none or more than one.

## Backwards compatibility

When `metadata.cache.enabled` is `false` (the default), the cache
reference is `None`, S3 always invokes `MetadataService.resolve`,
and the `document_cache` table stays empty. The schema migration
runs unconditionally (cheap + idempotent), so toggling the flag
later does not require a separate setup step.

## Limitations (deferred)

- **AS400-backed cache**: 037 ships SQLite only. The AS400 NIARVILOG
  coordination from 034 covers cross-process **idempotency**; for
  per-document metadata cache, single-host SQLite is enough until
  multi-host deployments prove a need.
- **Partial-overlap reuse**: cache key is the full sorted field
  set. If today's mapping requires `{A, B, C}` and tomorrow's
  requires `{A, B}`, the cache misses on the subset even though A
  and B are already resolved. All-or-nothing keeps the correctness
  story simple.
- **Auto-vacuum / compaction**: rely on `cache clear --older-than`
  for housekeeping. SQLite's `auto_vacuum=INCREMENTAL` mode is
  available for very large caches but not wired up by default.

## Cross-references

- Spec: `specs/037-document-cache/`.
- POST-MVP entry: `docs/roadmap/POST-MVP.md §9`.
- Related: change 034 (AS400 NIARVILOG cross-process idempotency —
  different layer; the cache layers on top), change 027 (`cmcourier
  analyze` aggregates the structured cache log events).

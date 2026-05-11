# 037 — Cross-batch document_cache table (POST-MVP §9)

## Why

S3 (Metadata Resolution) is the most external-IO-heavy stage: every
field source query touches a CSV adapter, an AS400 cursor, or the
trigger/RVABREP row. Re-running the same doc in a different mode
(e.g., resume after partial S5 failure, or migrating a backlog by
chunks) pays that cost again — even when the resolved properties
are byte-identical to the last successful resolve.

POST-MVP §9 introduces a **cross-batch metadata cache** keyed by
`txn_num` + required-fields signature. After a successful S3, the
resolved metadata + healed trigger CIF are upserted into a
`document_cache` SQLite table. Before S3 begins, the cache is
consulted; on hit (and TTL valid + fields match), S3 short-circuits.

## What

### Configuration

New `MetadataCacheConfig` block under `MetadataConfigModel.cache`:

```python
class MetadataCacheConfig(BaseModel):
    enabled: bool = False
    ttl_minutes: int = Field(default=60, gt=0)
```

Default `enabled = False` — opt-in. Single-batch behavior unchanged
when off.

### Schema (SQLite)

Same DB as `migration_log` (single `tracking.db_path`):

```sql
CREATE TABLE IF NOT EXISTS document_cache (
    txn_num         TEXT NOT NULL,
    fields_hash     TEXT NOT NULL,
    trigger_cif     TEXT,
    properties_json TEXT NOT NULL,
    cached_at       TEXT NOT NULL,  -- ISO-8601 UTC
    PRIMARY KEY (txn_num, fields_hash)
);

CREATE INDEX IF NOT EXISTS idx_document_cache_cached_at
ON document_cache (cached_at);
```

`fields_hash` is a SHA-256 hex digest of
`",".join(sorted(required_metadata_fields))` — short, deterministic,
mapping-evolution-safe.

### Port + adapter

* `cmcourier.domain.ports.IDocumentCache` — `get`, `put`, `clear`,
  `stats`.
* `cmcourier.adapters.tracking.SqliteDocumentCache` — concrete
  implementation reusing the existing connection pool of
  `SQLiteTrackingStore`. New `_CREATE_DOCUMENT_CACHE` DDL added to
  the migration list.

### Service

`DocumentCacheService` wraps the port and adds:

- Clock injection for deterministic TTL tests.
- Hit/miss in-memory counters surfaced via `stats()` (so the CLI
  `cache stats` command works without reading the table again).
- A single `try_get_or_resolve(*, txn, fields, resolver_fn)` helper
  the pipeline calls.

### Pipeline integration

`StagedPipeline._stage_s3` consults the cache before invoking
`MetadataService.resolve`:

```python
key = CacheKey(txn=document.txn_num, fields=mapping.required_metadata_fields)
entry = cache.get(key) if cache else None
if entry is not None and not entry.expired(now, ttl):
    resolution = MetadataResolution.from_cache(entry)
    counter.hits += 1
else:
    counter.misses += 1
    resolution = metadata_service.resolve(trigger, document, mapping)
    if cache: cache.put(key, resolution, now)
```

When `metadata.cache.enabled = False`, the cache reference is
`None`, the consult / write paths are skipped, and behavior is
byte-identical to pre-037.

### CLI

New `cmcourier cache` command group:

- `cmcourier cache stats [--config <path>]`: rows total, oldest,
  newest, hits / misses since last process start (in-memory).
- `cmcourier cache clear --txn <num> [--config <path>]`: delete by
  txn.
- `cmcourier cache clear --all [--config <path>]`: truncate table.
- `cmcourier cache clear --older-than <minutes> [--config <path>]`:
  delete entries older than N minutes.

### Metrics + observability

Each S3 dispatch emits one of:

```json
{"event": "document_cache_hit",  "txn_num": "...", "age_s": 12.4, "fields_hash": "abc..."}
{"event": "document_cache_miss", "txn_num": "...", "reason": "absent|expired"}
```

A `cache.hits` / `cache.misses` counter feeds the existing
`MetricsRecorder` so the JSONL pipeline log surfaces totals at the
end of each batch.

## Backwards compatibility

`metadata.cache.enabled = False` (the default) → cache reference is
`None` everywhere → S3 path is byte-identical to pre-037. All 950
existing tests keep passing. The new `document_cache` table is
created in the SQLite migration list but stays empty unless the
operator opts in.

## Out of scope (deferred)

- AS400-backed cache for §4 environments. The cross-process
  coordination via NIARVILOG (034) handles idempotency cross-process
  already; for the cache, single-host SQLite is enough until
  multi-host deployments prove a need.
- Per-field caching (cache hit on partial field overlap). All-or-
  nothing on `fields_hash` keeps the correctness story simple.
- Compaction / vacuum strategy. `cmcourier cache clear --older-than`
  is the operator-driven cleanup; auto-vacuum is a future watchlist
  item.

# 037 — Plan

Four phases, ~6-7h total. RED→GREEN per phase, commit per phase, FF
on the last commit.

## Phase 1 — Schema + port + SQLite adapter (~2h)

### Files

- `src/cmcourier/config/schema.py`
  - `MetadataCacheConfig` (frozen, `enabled: bool=False`,
    `ttl_minutes: int=Field(default=60, gt=0)`).
  - `MetadataConfigModel.cache: MetadataCacheConfig = Field(
    default_factory=MetadataCacheConfig)`.
- `src/cmcourier/domain/ports.py`
  - `IDocumentCache` Protocol — `get`, `put`, `clear_txn`,
    `clear_all`, `clear_older_than`, `stats`.
  - `CacheKey`, `CacheEntry`, `CacheStats` frozen dataclasses.
- `src/cmcourier/adapters/tracking/sqlite.py`
  - New `_CREATE_DOCUMENT_CACHE` DDL + `_CREATE_IDX_CACHE_AGE`
    added to the migration list. Table is created at every
    `SQLiteTrackingStore` open whether cache is enabled or not
    (cheap; idempotent).
- `src/cmcourier/adapters/tracking/sqlite_document_cache.py` (new)
  - `SqliteDocumentCache(db_path: Path)` opening the same database
    via a thin shared-connection wrapper. Methods map 1:1 to
    `IDocumentCache`.

### Tests

- `tests/unit/config/test_schema.py::TestMetadataCacheConfig`
  - Defaults; TTL bounds; `metadata.cache` round-trips through
    `PipelineConfig`.
- `tests/integration/adapters/test_sqlite_document_cache.py` (new)
  - `put` then `get` returns the entry.
  - `get` miss when key absent.
  - `put` upsert (same key replaces).
  - `clear_txn` removes only that txn (different `fields_hash` for
    same txn are independent rows; both go).
  - `clear_all` truncates.
  - `clear_older_than` deletes rows past the threshold.
  - `stats()` returns total + oldest + newest.

### Commit

```
feat(config,tracking): MetadataCacheConfig + document_cache schema + SqliteDocumentCache (037 Phase 1)
```

## Phase 2 — DocumentCacheService + S3 short-circuit (~2h)

### Files

- `src/cmcourier/services/document_cache.py` (new)
  - `DocumentCacheService(cache: IDocumentCache, ttl_minutes: int,
    clock: Callable[[], datetime])`.
  - `try_get(*, txn, fields) -> CacheEntry | None`: cache.get +
    TTL check.
  - `put(*, txn, fields, resolution)`.
  - `clear_txn`, `clear_all`, `clear_older_than` (pass-throughs).
  - In-memory `_hits`, `_misses` counters.
  - `stats_in_memory()` returns hits / misses since process start.
- `src/cmcourier/orchestrators/staged.py`
  - `StagedPipeline.__init__` gains optional
    `document_cache: DocumentCacheService | None = None`.
  - `_stage_s3` calls `document_cache.try_get(...)` before
    `metadata_service.resolve`. On hit, builds a
    `MetadataResolution` from the entry. On miss, runs the resolver
    and writes the cache after success.
- `src/cmcourier/config/wiring.py`
  - Build `DocumentCacheService` iff
    `config.metadata.cache.enabled`. Pass to `StagedPipeline`.

### Tests

- `tests/unit/services/test_document_cache.py`
  - Hit returns cached entry.
  - Miss when absent.
  - Miss when expired (synthetic clock).
  - Put + get round-trip preserves properties + healed CIF.
  - `fields_hash` collision is impossible across distinct field sets.
- `tests/integration/pipeline/test_s3_cache.py` (new)
  - StagedPipeline with `document_cache` set: second run for the
    same `txn_num` skips `MetadataService.resolve` (counted via a
    mock).
  - Same pipeline without cache: both runs hit S3 (regression).
  - TTL expiry → second run hits S3 again.

### Commit

```
feat(services,pipeline): DocumentCacheService + S3 cache short-circuit (037 Phase 2)
```

## Phase 3 — CLI commands (~1h)

### Files

- `src/cmcourier/cli/commands/cache.py` (new)
  - `@click.group("cache")`.
  - `cache stats [--config <path>] [--format text|json]`.
  - `cache clear --txn <num> [--config <path>]`.
  - `cache clear --all [--config <path>]`.
  - `cache clear --older-than <minutes> [--config <path>]`.
- `src/cmcourier/cli/app.py`: register the group.

### Tests

- `tests/integration/cli/test_cache_cli.py` (new)
  - `cache stats` text + json formats.
  - `cache clear --txn` removes one entry.
  - `cache clear --all` empties the table.
  - `cache clear --older-than` deletes only old rows (synthetic
    `cached_at` via direct INSERT).

### Commit

```
feat(cli): cmcourier cache stats|clear subcommands (037 Phase 3)
```

## Phase 4 — Metrics + docs + CHANGELOG + FF (~1.5h)

### Files

- `src/cmcourier/services/document_cache.py`
  - On hit / miss, emit a structured INFO log line with
    `event=document_cache_hit` / `_miss`.
- `tests/unit/services/test_document_cache.py`
  - Assert log records contain the right fields.
- `docs/how-to/document-cache.md` (new)
  - When to enable, TTL trade-offs, how to read `cache stats`,
    backup implications.
- `CHANGELOG.md` `[0.38.0]`, README tick, POST-MVP §9 marked
  SHIPPED.

### FF merge

```
git checkout main
git merge --ff-only feat/037-document-cache
git branch -d feat/037-document-cache
```

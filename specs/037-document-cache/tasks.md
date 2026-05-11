# 037 — Tasks

## Phase 1: schema + port + SQLite adapter

- [ ] 1.1 `MetadataCacheConfig` pydantic model + nested
      `MetadataConfigModel.cache` field with default-factory.
- [ ] 1.2 `IDocumentCache` port + `CacheKey` / `CacheEntry` /
      `CacheStats` dataclasses in `cmcourier.domain.ports`.
- [ ] 1.3 `_CREATE_DOCUMENT_CACHE` DDL + index in `sqlite.py`
      migration list.
- [ ] 1.4 `SqliteDocumentCache` adapter file with `get` / `put` /
      `clear_*` / `stats`.
- [ ] 1.5 Tests: schema (4 cases) + adapter (7 cases). RED → GREEN.
- [ ] 1.6 Full suite + mypy + ruff clean.
- [ ] 1.7 Commit `feat(config,tracking): MetadataCacheConfig + document_cache schema + SqliteDocumentCache (037 Phase 1)`.

## Phase 2: DocumentCacheService + S3 short-circuit

- [ ] 2.1 `services/document_cache.py`: `DocumentCacheService` with
      clock injection, TTL logic, in-memory counters.
- [ ] 2.2 `StagedPipeline.__init__` adds optional
      `document_cache` arg; `_stage_s3` consults + writes.
- [ ] 2.3 `config/wiring.py`: build service iff
      `metadata.cache.enabled`.
- [ ] 2.4 Unit tests: hit / miss / expired / round-trip / fields
      collision.
- [ ] 2.5 Integration tests: pipeline cache-vs-no-cache S3 call
      counts; TTL expiry triggers re-resolution.
- [ ] 2.6 Commit `feat(services,pipeline): DocumentCacheService + S3 cache short-circuit (037 Phase 2)`.

## Phase 3: CLI commands

- [ ] 3.1 `cli/commands/cache.py` with `stats` and `clear`
      subcommands (`--txn|--all|--older-than`).
- [ ] 3.2 Register group in `cli/app.py`.
- [ ] 3.3 Integration tests via `CliRunner`.
- [ ] 3.4 Commit `feat(cli): cmcourier cache stats|clear subcommands (037 Phase 3)`.

## Phase 4: metrics + docs + CHANGELOG + FF

- [ ] 4.1 Structured `document_cache_hit` / `_miss` log events from
      service.
- [ ] 4.2 `docs/how-to/document-cache.md` operator guide.
- [ ] 4.3 `CHANGELOG.md [0.38.0]`, POST-MVP §9 SHIPPED, README
      tick.
- [ ] 4.4 Full suite green; mypy + ruff clean.
- [ ] 4.5 Commit `docs(037): document-cache how-to + CHANGELOG 0.38.0 + POST-MVP §9 SHIPPED (037 Phase 4)`.
- [ ] 4.6 FF merge + branch delete.

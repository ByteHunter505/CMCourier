# 037 — Plan

Cuatro fases, ~6-7h en total. RED→GREEN por fase, commit por fase,
FF en el último commit.

## Fase 1 — Esquema + puerto + adaptador SQLite (~2h)

### Archivos

- `src/cmcourier/config/schema.py`
  - `MetadataCacheConfig` (frozen, `enabled: bool=False`,
    `ttl_minutes: int=Field(default=60, gt=0)`).
  - `MetadataConfigModel.cache: MetadataCacheConfig = Field(
    default_factory=MetadataCacheConfig)`.
- `src/cmcourier/domain/ports.py`
  - Protocol `IDocumentCache` — `get`, `put`, `clear_txn`,
    `clear_all`, `clear_older_than`, `stats`.
  - Dataclasses frozen `CacheKey`, `CacheEntry`, `CacheStats`.
- `src/cmcourier/adapters/tracking/sqlite.py`
  - Nuevo DDL `_CREATE_DOCUMENT_CACHE` + `_CREATE_IDX_CACHE_AGE`
    agregados a la lista de migraciones. La tabla se crea en cada
    apertura de `SQLiteTrackingStore` sin importar si el caché está
    habilitado o no (es barato; idempotente).
- `src/cmcourier/adapters/tracking/sqlite_document_cache.py` (nuevo)
  - `SqliteDocumentCache(db_path: Path)` abriendo la misma base
    vía un envoltorio fino de `connection` compartida. Los métodos
    mapean 1:1 a `IDocumentCache`.

### Tests

- `tests/unit/config/test_schema.py::TestMetadataCacheConfig`
  - Valores por defecto; bordes de TTL; `metadata.cache` hace
    `round-trip` a través de `PipelineConfig`.
- `tests/integration/adapters/test_sqlite_document_cache.py` (nuevo)
  - `put` y luego `get` devuelve la entrada.
  - `get` miss cuando la `key` no existe.
  - `put` `upsert` (misma `key` reemplaza).
  - `clear_txn` elimina solo ese `txn` (distintos `fields_hash`
    para el mismo `txn` son filas independientes; se van ambas).
  - `clear_all` truncea.
  - `clear_older_than` borra filas más viejas que el umbral.
  - `stats()` devuelve total + más antigua + más nueva.

### Commit

```
feat(config,tracking): MetadataCacheConfig + document_cache schema + SqliteDocumentCache (037 Phase 1)
```

## Fase 2 — DocumentCacheService + cortocircuito en S3 (~2h)

### Archivos

- `src/cmcourier/services/document_cache.py` (nuevo)
  - `DocumentCacheService(cache: IDocumentCache, ttl_minutes: int,
    clock: Callable[[], datetime])`.
  - `try_get(*, txn, fields) -> CacheEntry | None`: cache.get +
    chequeo de TTL.
  - `put(*, txn, fields, resolution)`.
  - `clear_txn`, `clear_all`, `clear_older_than` (pass-throughs).
  - Contadores en memoria `_hits`, `_misses`.
  - `stats_in_memory()` devuelve hits / misses desde el inicio del
    proceso.
- `src/cmcourier/orchestrators/staged.py`
  - `StagedPipeline.__init__` gana
    `document_cache: DocumentCacheService | None = None` opcional.
  - `_stage_s3` llama a `document_cache.try_get(...)` antes que
    `metadata_service.resolve`. En hit, construye un
    `MetadataResolution` a partir de la entrada. En miss, corre el
    `resolver` y escribe en el caché tras éxito.
- `src/cmcourier/config/wiring.py`
  - Construir `DocumentCacheService` solo si
    `config.metadata.cache.enabled`. Pasarlo a `StagedPipeline`.

### Tests

- `tests/unit/services/test_document_cache.py`
  - Hit devuelve la entrada cacheada.
  - Miss cuando no existe.
  - Miss cuando expiró (clock sintético).
  - `Put` + `get` `round-trip` preserva propiedades + CIF sanado.
  - Las colisiones de `fields_hash` son imposibles entre sets de
    campos distintos.
- `tests/integration/pipeline/test_s3_cache.py` (nuevo)
  - `StagedPipeline` con `document_cache` definido: la segunda
    corrida para el mismo `txn_num` se saltea
    `MetadataService.resolve` (contado vía un `mock`).
  - El mismo `pipeline` sin caché: ambas corridas pegan en S3
    (regresión).
  - Expiración de TTL → la segunda corrida vuelve a pegar en S3.

### Commit

```
feat(services,pipeline): DocumentCacheService + S3 cache short-circuit (037 Phase 2)
```

## Fase 3 — Comandos CLI (~1h)

### Archivos

- `src/cmcourier/cli/commands/cache.py` (nuevo)
  - `@click.group("cache")`.
  - `cache stats [--config <path>] [--format text|json]`.
  - `cache clear --txn <num> [--config <path>]`.
  - `cache clear --all [--config <path>]`.
  - `cache clear --older-than <minutes> [--config <path>]`.
- `src/cmcourier/cli/app.py`: registrar el grupo.

### Tests

- `tests/integration/cli/test_cache_cli.py` (nuevo)
  - `cache stats` formato texto + json.
  - `cache clear --txn` elimina una entrada.
  - `cache clear --all` vacía la tabla.
  - `cache clear --older-than` borra solo filas viejas (`cached_at`
    sintético vía INSERT directo).

### Commit

```
feat(cli): cmcourier cache stats|clear subcommands (037 Phase 3)
```

## Fase 4 — Métricas + docs + CHANGELOG + FF (~1.5h)

### Archivos

- `src/cmcourier/services/document_cache.py`
  - En hit / miss, emitir una línea de log INFO estructurada con
    `event=document_cache_hit` / `_miss`.
- `tests/unit/services/test_document_cache.py`
  - Verificar que los registros de log contienen los campos
    correctos.
- `docs/how-to/document-cache.md` (nuevo)
  - Cuándo habilitar, `trade-offs` del TTL, cómo leer
    `cache stats`, implicaciones para `backup`s.
- `CHANGELOG.md` `[0.38.0]`, tilde del README, POST-MVP §9 marcado
  como SHIPPED.

### Merge FF

```
git checkout main
git merge --ff-only feat/037-document-cache
git branch -d feat/037-document-cache
```

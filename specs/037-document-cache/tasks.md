# 037 — Tareas

## Fase 1: esquema + puerto + adaptador SQLite

- [ ] 1.1 Modelo pydantic `MetadataCacheConfig` + campo anidado
      `MetadataConfigModel.cache` con `default-factory`.
- [ ] 1.2 Puerto `IDocumentCache` + dataclasses `CacheKey` /
      `CacheEntry` / `CacheStats` en `cmcourier.domain.ports`.
- [ ] 1.3 DDL `_CREATE_DOCUMENT_CACHE` + índice en la lista de
      migraciones de `sqlite.py`.
- [ ] 1.4 Archivo del adaptador `SqliteDocumentCache` con `get` /
      `put` / `clear_*` / `stats`.
- [ ] 1.5 Tests: esquema (4 casos) + adaptador (7 casos). RED →
      GREEN.
- [ ] 1.6 Suite completa + `mypy` + `ruff` limpios.
- [ ] 1.7 Commit `feat(config,tracking): MetadataCacheConfig + document_cache schema + SqliteDocumentCache (037 Phase 1)`.

## Fase 2: DocumentCacheService + cortocircuito en S3

- [ ] 2.1 `services/document_cache.py`: `DocumentCacheService` con
      inyección de `clock`, lógica de TTL, contadores en memoria.
- [ ] 2.2 `StagedPipeline.__init__` agrega `document_cache` como
      argumento opcional; `_stage_s3` consulta + escribe.
- [ ] 2.3 `config/wiring.py`: construir el servicio solo si
      `metadata.cache.enabled`.
- [ ] 2.4 Tests unitarios: hit / miss / expirado / `round-trip` /
      colisión de `fields`.
- [ ] 2.5 Tests de integración: conteos de llamadas a S3
      `cache-vs-no-cache` en el `pipeline`; la expiración de TTL
      dispara re-resolución.
- [ ] 2.6 Commit `feat(services,pipeline): DocumentCacheService + S3 cache short-circuit (037 Phase 2)`.

## Fase 3: comandos CLI

- [ ] 3.1 `cli/commands/cache.py` con subcomandos `stats` y
      `clear` (`--txn|--all|--older-than`).
- [ ] 3.2 Registrar el grupo en `cli/app.py`.
- [ ] 3.3 Tests de integración vía `CliRunner`.
- [ ] 3.4 Commit `feat(cli): cmcourier cache stats|clear subcommands (037 Phase 3)`.

## Fase 4: métricas + docs + CHANGELOG + FF

- [ ] 4.1 Eventos estructurados de log `document_cache_hit` /
      `_miss` desde el servicio.
- [ ] 4.2 Guía del operador `docs/how-to/document-cache.md`.
- [ ] 4.3 `CHANGELOG.md [0.38.0]`, POST-MVP §9 SHIPPED, tilde del
      README.
- [ ] 4.4 Suite completa en verde; `mypy` + `ruff` limpios.
- [ ] 4.5 Commit `docs(037): document-cache how-to + CHANGELOG 0.38.0 + POST-MVP §9 SHIPPED (037 Phase 4)`.
- [ ] 4.6 Merge FF + eliminar la rama.

# 037 — Tabla `document_cache` cross-batch (POST-MVP §9)

## Por qué

S3 (Resolución de metadata) es la etapa con más I/O externo: cada
consulta de fuente de campo toca un adaptador CSV, un cursor AS400,
o la fila trigger/RVABREP. Re-correr el mismo documento en un modo
distinto (por ejemplo, retomar tras una falla parcial de S5, o
migrar un backlog por chunks) paga ese costo otra vez — incluso
cuando las propiedades resueltas son byte-idénticas al último
resolve exitoso.

POST-MVP §9 introduce un **caché de metadata cross-batch** keado por
`txn_num` + firma de campos requeridos. Tras un S3 exitoso, la
metadata resuelta + el CIF del trigger sanado se `upsertean` en una
tabla SQLite `document_cache`. Antes de que S3 comience, se consulta
el caché; con hit (y TTL válido + match de campos), S3 se
cortocircuita.

## Qué

### Configuración

Nuevo bloque `MetadataCacheConfig` bajo `MetadataConfigModel.cache`:

```python
class MetadataCacheConfig(BaseModel):
    enabled: bool = False
    ttl_minutes: int = Field(default=60, gt=0)
```

`enabled = False` por defecto — opt-in. El comportamiento de
`batch` único no cambia cuando está apagado.

### Esquema (SQLite)

Misma DB que `migration_log` (único `tracking.db_path`):

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

`fields_hash` es un digest hex SHA-256 de
`",".join(sorted(required_metadata_fields))` — corto, determinista,
seguro frente a evolución del mapeo.

### Puerto + adaptador

* `cmcourier.domain.ports.IDocumentCache` — `get`, `put`, `clear`,
  `stats`.
* `cmcourier.adapters.tracking.SqliteDocumentCache` —
  implementación concreta que reutiliza el `connection pool`
  existente de `SQLiteTrackingStore`. Se agrega el nuevo DDL
  `_CREATE_DOCUMENT_CACHE` a la lista de migraciones.

### Servicio

`DocumentCacheService` envuelve el puerto y agrega:

- Inyección de `clock` para tests deterministas de TTL.
- Contadores en memoria de hits/misses expuestos vía `stats()` (para
  que el comando CLI `cache stats` funcione sin volver a leer la
  tabla).
- Un único helper `try_get_or_resolve(*, txn, fields, resolver_fn)`
  que llama el `pipeline`.

### Integración con el pipeline

`StagedPipeline._stage_s3` consulta el caché antes de invocar a
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

Cuando `metadata.cache.enabled = False`, la referencia del caché es
`None`, los caminos de consulta/escritura se saltean, y el
comportamiento es byte-idéntico a pre-037.

### CLI

Nuevo grupo de comandos `cmcourier cache`:

- `cmcourier cache stats [--config <path>]`: total de filas, más
  antigua, más nueva, hits / misses desde el último inicio de
  proceso (en memoria).
- `cmcourier cache clear --txn <num> [--config <path>]`: borrar por
  `txn`.
- `cmcourier cache clear --all [--config <path>]`: truncar la tabla.
- `cmcourier cache clear --older-than <minutes> [--config <path>]`:
  borrar entradas más viejas que N minutos.

### Métricas + observabilidad

Cada despacho de S3 emite uno de:

```json
{"event": "document_cache_hit",  "txn_num": "...", "age_s": 12.4, "fields_hash": "abc..."}
{"event": "document_cache_miss", "txn_num": "...", "reason": "absent|expired"}
```

Un contador `cache.hits` / `cache.misses` alimenta el
`MetricsRecorder` existente para que el log JSONL del `pipeline`
exponga los totales al cierre de cada `batch`.

## Compatibilidad hacia atrás

`metadata.cache.enabled = False` (el valor por defecto) → la
referencia del caché es `None` en todas partes → el camino S3 es
byte-idéntico a pre-037. Las 950 pruebas existentes siguen pasando.
La nueva tabla `document_cache` se crea en la lista de migraciones
SQLite pero queda vacía a menos que el operador opte por activarla.

## Fuera de alcance (diferido)

- Caché respaldado por AS400 para entornos §4. La coordinación
  cross-process vía NIARVILOG (034) ya maneja la idempotencia
  cross-process; para el caché, SQLite single-host alcanza hasta
  que los despliegues multi-host demuestren la necesidad.
- Caché por campo (hit con solapamiento parcial). Todo-o-nada sobre
  `fields_hash` mantiene la historia de corrección simple.
- Estrategia de compactación / vacuum. `cmcourier cache clear
  --older-than` es la limpieza dirigida por el operador; el
  `auto-vacuum` es un ítem futuro de watchlist.

# How-to: Cache cross-batch de metadatos (037, POST-MVP §9)

Saltea S3 (Resolución de Metadatos) en una re-corrida del mismo documento
cuando las propiedades resueltas no están vencidas. Default OFF —
el comportamiento single-batch es byte-idéntico a pre-037.

## Cuándo activar esto

Habilitalo cuando:

- Re-corrés pipelines frecuentemente contra batches superpuestos
  (ej., resume tras un fallo parcial de S5, o migrar un backlog largo
  por chunks).
- La latencia de S3 domina una corrida porque las fuentes de campos son
  caras (queries AS400, scans CSV grandes).
- Tus fuentes de metadatos son **estables** dentro de la ventana TTL.

Dejá apagado cuando:

- Las fuentes de campos cambian impredeciblemente (importaciones CSV
  entrando cada minuto). Metadatos servidos pero vencidos podrían aterrizar
  en CMIS.
- Tu única corrida es la primera migración — no hay nada para re-usar.

## Qué cachea

Tras cada S3 exitoso las propiedades resueltas + el CIF del trigger
(posiblemente curado) se upsertean en una tabla SQLite
`document_cache` indexada por:

- `txn_num` — la transacción RVABREP.
- `fields_hash` — SHA-256 de la lista ordenada de
  `required_metadata_fields` para el mapping de este documento. Si el
  mapping cambia los campos requeridos, el hash cambia, y el cache no
  pega — así que evolucionar el mapping nunca sirve un set de metadatos
  incompleto.

El almacenamiento vive en el mismo archivo de base de datos que el log
de tracking (`tracking.db_path`). Un archivo para backupear, un pool
de conexiones.

## Configuración

```yaml
metadata:
  cache:
    enabled: true              # default: false
    ttl_minutes: 60            # default: 60 ; rango: 1..43200 (30 días)
  # ... field_sources, sources, prefetch_enabled ...
```

El TTL se mide desde `cached_at` (UTC ISO-8601). Un hit cuya edad
excede `ttl_minutes` se trata como miss y el resolver corre de nuevo.

## Inspeccionar el cache

```text
$ cmcourier cache stats -c config.yaml
document_cache rows : 2143
oldest cached_at    : 2026-05-10T09:12:43+00:00
newest cached_at    : 2026-05-11T17:54:01+00:00
```

Forma JSON para pipear a `jq`:

```text
$ cmcourier cache stats -c config.yaml --format json
{
  "total_rows": 2143,
  "oldest_cached_at": "2026-05-10T09:12:43+00:00",
  "newest_cached_at": "2026-05-11T17:54:01+00:00"
}
```

Los contadores de hit / miss en-proceso se exponen en el log JSONL del
pipeline vía los eventos `document_cache_hit` y `document_cache_miss`:

```json
{"event": "document_cache_hit",  "txn_num": "1234567", "age_s": 312.4, "fields_hash": "abc..."}
{"event": "document_cache_miss", "txn_num": "1234568", "reason": "absent", "fields_hash": "abc..."}
{"event": "document_cache_miss", "txn_num": "1234567", "reason": "expired", "age_s": 3700.1, ...}
```

`cmcourier analyze batch <id>` los agrega para revisión offline.

## Limpiar el cache

```bash
# Invalidar un documento (ej., después de corregir metadatos manualmente).
cmcourier cache clear -c config.yaml --txn 1234567

# Wipear el cache entero (ej., tras un cambio de schema de mapping
# que no querés esperar a TTL).
cmcourier cache clear -c config.yaml --all

# Housekeeping periódico: dropear entradas más viejas a 24 horas.
cmcourier cache clear -c config.yaml --older-than 1440
```

`--all`, `--txn`, y `--older-than` son mutuamente exclusivas; la CLI
sale con error (exit code 2) si pasás ninguna o más de una.

## Compatibilidad hacia atrás

Cuando `metadata.cache.enabled` es `false` (el default), la referencia
del cache es `None`, S3 siempre invoca `MetadataService.resolve`,
y la tabla `document_cache` queda vacía. La migración del schema
corre incondicionalmente (barata + idempotente), así que togglear el
flag más tarde no requiere un paso de setup separado.

## Limitaciones (diferidas)

- **Cache respaldado en AS400**: 037 shippea solo SQLite. La
  coordinación NIARVILOG AS400 de 034 cubre **idempotencia** entre
  procesos; para cache de metadatos por documento, SQLite single-host
  alcanza hasta que despliegues multi-host prueben una necesidad.
- **Reutilización por overlap parcial**: la clave del cache es el set
  completo de campos ordenado. Si el mapping de hoy requiere
  `{A, B, C}` y el de mañana requiere `{A, B}`, el cache no pega en
  el subset aunque A y B ya estén resueltos. Todo-o-nada mantiene la
  historia de corrección simple.
- **Auto-vacuum / compactación**: dependé de
  `cache clear --older-than` para housekeeping. El modo
  `auto_vacuum=INCREMENTAL` de SQLite está disponible para caches muy
  grandes pero no está cableado por default.

## Cross-references

- Spec: `specs/037-document-cache/`.
- Entrada POST-MVP: `docs/roadmap/POST-MVP.md §9`.
- Relacionados: cambio 034 (idempotencia cross-proceso AS400 NIARVILOG —
  capa diferente; el cache se monta encima), cambio 027 (`cmcourier
  analyze` agrega los eventos estructurados de log del cache).

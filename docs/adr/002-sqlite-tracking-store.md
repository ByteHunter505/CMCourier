> [← Volver al índice](../INDEX.md) · [ADRs](README.md)

# ADR-002: SQLite como tracking store local

- **Estado**: Aceptado y vigente
- **Fecha**: 2026-05-10
- **Spec(s) relacionadas**: 007 (store inicial), 034 (sync distribuido con AS400 NIARVILOG), 037 (document cache), 044 (resume robusto), 045 (409 idempotente), 047 (persistir `cm_object_id`), 062 (persistir filtrados y skipeados)
- **Versión donde se shipping**: 0.9.0 (store inicial); evolucionó hasta 0.73.0

## Contexto

CMCourier corre **embebido en el servidor del banco**, dentro de la red corporativa, detrás de firewalls que no podemos asumir cooperativos con servicios externos. Las restricciones operativas que esto impone son concretas:

1. **No podemos asumir una DB externa disponible.** Postgres, MySQL, DynamoDB requieren provisioning, credenciales y permisos que el banco no nos va a otorgar para una herramienta de migración. Cero infraestructura adicional es un requisito, no una preferencia.
2. **Necesitamos audit trail durable.** El Principio VIII de la Constitución exige preservar el trail de auditoría — qué se migró, cuándo, con qué resultado — por el período regulatorio que el banco especifique.
3. **Idempotencia cross-batch es sagrada (Principio II).** El identificador `rvabrep_txn_num` tiene que estar bajo `UNIQUE` constraint a nivel de persistencia. Si una corrida de 200.000 documentos se interrumpe a la mitad, la siguiente no puede re-uploadear nada.
4. **Queryable a posteriori.** Operador y auditoría necesitan filtrar por status, batch, txn_num desde un terminal sin levantar el orquestador completo.
5. **AS400 nativo (DB2/400) no servía como tracking primario.** El banco no permite que escribamos arbitrariamente en sus tablas. Hay una tabla compartida (`RVILIB.NIARVILOG`) para idempotencia distribuida — pero eso es una capa adicional, no la primaria.

El antecesor `RVIMigration` tenía un híbrido: estado parcial en memoria, parcial en archivos JSON, parcial en AS400. Resultado: imposible reconciliar después de un kill -9.

## Decisión

Adoptamos **SQLite local** como tracking store primario y obligatorio, con la siguiente forma:

- **Un archivo `.db`** apuntado por `tracking.db_path` en YAML. Cero dependencias externas: viene con stdlib de Python.
- **WAL mode** (`PRAGMA journal_mode=WAL`) — reader y writer concurrent sin bloqueo mutuo.
- **Writer thread daemon dedicado.** El reader corre en el thread principal (lecturas síncronas + `start_batch` síncrono porque el caller necesita el UUID4 inmediatamente). El writer es un único thread daemon consumiendo de un `queue.Queue`, con batched commits cada ~500 ítems o 1 segundo.
- **Idempotencia codificada en el schema, no en Python**:
  - `UNIQUE (rvabrep_txn_num, batch_id)` permite `INSERT OR IGNORE` como cuerpo entero de `mark_stage_pending`.
  - `INDEX ON (rvabrep_txn_num) WHERE status='S5_DONE'` hace que `is_uploaded()` sea O(1) sin importar cuántos batches corrieron antes.
- **Pragmas perf-oriented**: `synchronous=OFF` (toleramos crash porque las operaciones son idempotentes), `cache_size=-64000` (64 MiB), `temp_store=MEMORY`.
- **State machine explícita**: `S0_PENDING → S0_DONE → S1_PENDING → S1_DONE / S1_SKIPPED / S1_FILTERED → … → S5_DONE / S5_FAILED`. Cada transición está en un método del puerto, sin atajos.

Para idempotencia distribuida cuando hay múltiples workstations corriendo en paralelo, spec 034 sumó `As400NiarvilogStore` como capa opcional encima, vía `IdempotencyCoordinator`. SQLite sigue siendo siempre el anchor de resume in-process; AS400 es la verdad cross-host cuando el toggle está activo.

## Consecuencias

### Positivas

- **Deploy con cero dependencias de infraestructura.** Copiás el binario / venv, apuntás un YAML, y corre. No hay "esperá que provisionen la DB".
- **Backup trivial.** Un único archivo. `cp tracking.db tracking.db.bak` y listo. WAL files se chequean también pero son recreables.
- **Performance excelente para la carga real.** ~500 writes/segundo batched, lecturas O(1) sobre los índices parciales. La migración nunca está bottleneckeada por tracking — el bottleneck siempre es la red CMIS.
- **Inspección con sqlite3 CLI.** Cualquier operador con un terminal puede correr `sqlite3 tracking.db "SELECT count(*), status FROM migration_log GROUP BY status;"` sin levantar Python. Esa accesibilidad es operativamente importante.
- **Idempotencia estructural.** Re-correr un batch interrumpido respeta automáticamente los `S5_DONE` previos. El operador no tiene que "limpiar" nada — el `INSERT OR IGNORE` se encarga.

### Negativas / Tradeoffs

- **No distribuido out-of-the-box.** Un único proceso por archivo `.db`. Si el banco quiere correr múltiples workstations en paralelo, SQLite local de cada una no se entera de las otras. Mitigamos esto con spec 034 (sync distribuido via AS400 `NIARVILOG`), pero es opt-in: requiere conectividad AS400 estable.
- **WAL files visibles.** El operador a veces se confunde con `tracking.db-wal` y `tracking.db-shm` aparentando "archivos sueltos". Documentado en el runbook de tracking.
- **`synchronous=OFF` es agresivo.** En un crash duro (corte de luz, kernel panic) podrías perder los últimos ~1s de commits. Aceptable porque toda operación es idempotente (Principio II): la próxima corrida re-escribe lo perdido. No es aceptable para sistemas transaccionales clásicos, pero ese no es nuestro caso.
- **Single-writer.** Múltiples procesos contra el mismo `.db` no funcionan bien aún con WAL. Por diseño, un archivo `.db` = un proceso CMCourier.

### Neutras

- **`document_cache` (spec 037) y `migration_batch` viven en el mismo archivo.** No fragmentamos por feature: el archivo es el contenedor.

## Alternativas consideradas

- **Postgres.** Descartado por el constraint operativo: requiere provisioning del banco, credenciales, networking. Para una herramienta de migración temporal, agregar Postgres es agregar una superficie de configuración + un punto de falla. No suma valor.
- **DynamoDB / managed NoSQL.** Mismo problema, peor: dependencia de cloud que el banco probablemente no permita.
- **AS400 nativo (DB2/400) como store primario.** Descartado: el banco no nos permite crear tablas arbitrarias en su AS400 productivo. La integración existente es `NIARVILOG` (compartida con el migrador Java paralelo) y es de propósito específico (idempotencia cross-host), no general.
- **Archivos JSON / JSONL planos.** Es lo que tenía `RVIMigration` y es exactamente lo que estamos huyendo. Sin índices, sin atomicidad, sin queries. Reconciliación manual.
- **LiteFS / rqlite (SQLite distribuido).** Demasiado nuevo para usar en un contexto bancario regulatorio sin justificación fuerte. La spec 034 (sync vía `NIARVILOG`) resuelve el caso de uso real (idempotencia entre 2-3 workstations) sin necesidad de orquestación cluster.

## Ver también

- [Spec 007 — SQLite tracking store](../../specs/007-sqlite-tracking-store/)
- [Spec 034 — sync distribuido con AS400 NIARVILOG](../../specs/034-as400-niarvilog-sync/)
- [Spec 037 — document cache](../../specs/037-document-cache/)
- [Spec 044 — resume robusto](../../specs/044-robust-resume/)
- [Spec 047 — persistir cm_object_id en S5_DONE](../../specs/047-persist-cm-object-id/)
- [Spec 062 — persistir filtrados y skipeados](../../specs/062-persist-filtered-skipped/)
- [Constitution — Principio II (idempotencia)](../../.specify/memory/constitution.md)
- [Explanation: arquitectura](../explanation/architecture-overview.md)

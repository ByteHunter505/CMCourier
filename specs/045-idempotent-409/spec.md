# 045 — Subida de documento idempotente en S5 ante conflicto 409

## Por qué

La verificación en vivo §H.1 de 0.47.0 cerró el gap de detección de
resume, pero expuso un issue residual de la misma `race condition`
del kill: 4 docs aterrizaron en Alfresco desde el run 1 exitosamente
(200 OK desde CMIS) pero ``kill -9`` interrumpió el pipeline ANTES
de que el commit ``mark_stage_done(txn, batch_id, S5_DONE)`` de
SQLite pudiera persistir. En el resume, esos 4 docs lucen "todavía
pending S5" al migration log; el orchestrator reintenta la subida;
la constraint de unicidad de ``cmis:name`` de Alfresco rechaza con
HTTP 409 → esos 4 reintentos aterrizan como ``S5_FAILED`` en el
migration log aunque los docs ya están en CMIS.

El camino de creación de folder en ``CmisUploader`` ya implementa
este patrón idempotente-409 (la spec / el docstring en la línea
11): si un POST de folder devuelve 409 porque el folder ya existe,
el uploader procede con el id cacheado en vez de fallar. El camino
del POST de documento no tiene tal manejo — 045 lo lleva a paridad
con folders.

## Qué

### 1. ``CmisUploader._lookup_existing_object_id(folder_url, name)``

Nuevo helper privado. Lista los hijos del folder vía
``cmisselector=children`` y devuelve el ``cmis:objectId`` del hijo
cuyo ``cmis:name`` matchea ``name``. Devuelve ``None`` si no se
encuentra. Honra el mismo camino de retry / timeout / métricas que
los helpers GET existentes en el uploader.

Usamos el children-walk (no ``cmisselector=query``) porque la
indexación Solr de Alfresco tiene un lag de segundos-a-minutos y es
poco confiable como oráculo de freshness (esto lo observamos durante
las verificaciones de 040 / 041 — los uploads frescos eran invisibles
a queries SQL durante los primeros ~30 s). El endpoint de hijos
refleja el estado canónico del folder inmediatamente.

### 2. ``upload(...)`` atrapa el 409 e intenta recuperación

Después de que el POST multipart levante ``CMISClientError`` con
``status_code == 409``, el camino de upload:

1. Loguea un evento estructurado ``s5_upload_409_recovery_attempt``
   así el operador puede auditar las decisiones de recuperación en
   metrics.jsonl.
2. Llama a ``_lookup_existing_object_id(folder_url, document_name)``.
3. Si el lookup devuelve un ``cmis:objectId`` no-None:
   - Emitir ``s5_upload_409_recovered`` (éxito, recuperado).
   - Devolver ese objectId desde ``upload(...)`` como si la subida
     hubiera tenido éxito — el orchestrator marcará S5_DONE
     normalmente.
4. Si el lookup devuelve ``None`` (409 verdadero — no un duplicado
   por la `race condition` del kill, p. ej. constraint de permisos
   con una colisión distinta de ``cmis:name``):
   - Emitir ``s5_upload_409_recovery_failed``.
   - Re-raisear el ``CMISClientError`` original así el camino de
     falla continúa sin cambios.

### 3. Nueva distinción de StageOutcome (diferida)

El enum de outcomes del lado upload actualmente es ``"done" |
"failed" | "skipped"``. Consideramos agregar ``"recovered"`` así el
tab CHUNKS puede mostrar recovery distinto de un upload fresco —
pero cada métrica/contador downstream trata "done" idénticamente a
un éxito normal y el costo de bookkeeping de un nuevo outcome
empequeñece el valor de visibilidad a esta escala. Los uploads
recuperados cuentan como ``done`` en el tally; el evento
estructurado ``s5_upload_409_recovered`` provee auditabilidad
por-doc.

## Fuera de alcance

- Retry de 409 en creación de folder. Ese camino ya era idempotente
  pre-045.
- Verificar que el content/properties del doc recuperado matchea lo
  que pretendíamos subir. El contrato de unicidad es ``cmis:name``;
  si un doc distinto legítimamente comparte ese nombre (p. ej. el
  operador subió afuera del pipeline), la recuperación devuelve su
  id y el migration log lo marca S5_DONE para nuestro txn. Este es
  el contrato "confiar en el esquema de unicidad de cmis:name" —
  documentado en el runbook del operador.
- Reconciliación bulk asincrónica. Un job periódico que escanea el
  migration_log para filas "no S5_DONE" y chequea los contenidos
  del folder de CMIS podría cerrar toda la clase de pérdidas de
  commit a mitad de vuelo — fuera de alcance para 045 pero un
  follow-up razonable si aparecen más escenarios de `race condition`
  del kill.

## Criterios de aceptación

- Test unitario: ``upload(...)`` con una respuesta 409 mockeada del
  POST Y un lookup mockeado exitoso devuelve el objectId existente
  (sin excepción).
- Test unitario: ``upload(...)`` con una respuesta 409 Y un lookup
  que devuelve ``None`` re-raisea ``CMISClientError`` con el
  status_code original.
- Test unitario: ``upload(...)`` con una respuesta 200 en el primer
  intento nunca llama al helper de lookup (sin cambios de
  comportamiento en el happy path).
- Re-verify en vivo del escenario de staging §H.1 (kill mid-S5 +
  resume): final ``s5_failed == 0`` y conteo de docs de Alfresco ==
  txns distintos en el batch.
- Entrada ``CHANGELOG.md [0.48.0]``.
- mypy + ruff limpios.

## Notas sobre estrategia de tests

Los tests unitarios stubean el ``requests.Session`` vía la library
``responses`` (mismo enfoque que los tests existentes del CMIS
uploader) así podemos assertear mappings específicos de URL →
status determinísticamente. El helper de lookup se ejercita
directamente con su propio caso unitario para las ramas
"encontrado" / "no encontrado" / "error de transporte".

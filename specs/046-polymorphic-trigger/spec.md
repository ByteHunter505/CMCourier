# 046 — Modelo de Trigger polimórfico

## Por qué

El ``TriggerRecord`` actual es una 3-tupla fija ``(shortname, cif,
system_id)`` que cada estrategia S0 está forzada a producir. Cada
pase de S1 después re-quereya RVABREP por ``(shortname, system_id)``
para expandir el trigger a una lista de documentos. Ese modelo es el
ajuste natural para **solo una** clase de pipeline (csv-trigger,
donde el CSV literalmente es una lista de clientes). Para cada otro
pipeline es la granularidad equivocada y crea bugs semánticos
reales:

### local-scan: set de upload equivocado

Flujo de hoy (``services/triggers/local_scan.py``):

1. ``iterdir(scan_path)`` encuentra 1 archivo: ``foo.001``.
2. ``rvabrep.get_by_fields({file_name: 'foo.001'})`` devuelve la
   fila RVABREP que matchea — **la fila completa**, con txn_num,
   file_name, page_count, todo.
3. La estrategia tira todo eso a la basura y rinde
   ``TriggerRecord(shortname=X, cif=Y, system_id=Z)``.
4. S1 ``find_documents(trigger)`` re-quereya RVABREP por
   ``(X, Z)`` y devuelve **cada doc del cliente X**.
5. El pipeline sube todos los docs del cliente X a CMIS, no solo
   ``foo.001``.

Esto es lo que la §E.4 del checklist de validación destapó: un pool
de 100 archivos de scan produjo 1860 docs subidos. Lo
mis-diagnostiqué como un "bug de dedup faltante" en el análisis
predecesor de 046. El issue real es **la forma del trigger no
matchea lo que local-scan significa semánticamente**. Un operador
que deposita un archivo en un directorio de scan espera que ese
único archivo sea migrado, no todos los documentos pertenecientes al
cliente dueño del archivo.

### rvabrep-direct: doble trabajo + dedup demasiado amplio

Flujo de hoy (``services/triggers/direct_rvabrep.py:44-89``):

1. Escanear la fuente RVABREP (CSV o AS400).
2. **Dedup por ``(shortname, system_id)``** — colapsar N filas de un
   cliente en un trigger.
3. Rendir ``TriggerRecord(shortname, cif, system_id)``.
4. S1 re-quereya la misma fuente RVABREP por el mismo
   ``(shortname, system_id)`` para re-expandir a esas mismas N filas.

El round-trip completo de dedup-then-re-expand es trabajo
desperdiciado. Peor: cuando un operador quiere migrar una porción
específica de RVABREP (p. ej. por filtro de document_type), el
modelo actual primero colapsa, después re-expande sin el contexto
del filtro.

### Mismatch conceptual

Un trigger es **lo que dispara un doc a través del pipeline**. Su
forma natural depende de lo que el disparador ES:

| Pipeline | Trigger natural | Significado semántico |
|---|---|---|
| csv-trigger | fila del CSV trigger | "procesar cada doc de este cliente" |
| rvabrep-direct | fila de RVABREP | "procesar ESTE doc" |
| local-scan | un archivo en disco | "procesar el doc que respalda este archivo" |
| as400-trigger | fila del SQL del operador (típicamente NIARVILOG) | "procesar ESTE work-item" |
| single-doc | args de la CLI | "procesar docs que matchean este (sn, sys[, cif])" |

El trabajo de S1 es **enriquecimiento**, no re-expansión universal.
El enriquecimiento que necesita un trigger depende de lo que el
trigger ya lleva.

## Qué

### 1. Nueva jerarquía ``Trigger``

``domain/models.py`` introduce una base abstracta ``Trigger`` + cuatro
subtipos concretos:

```python
class Trigger:
    """ABC para todo lo que puede disparar uno o más docs."""
    def audit_row(self) -> dict[str, str | None]: ...  # para migration_log

@dataclass(frozen=True, slots=True)
class ClientTrigger(Trigger):
    """csv-trigger + single-doc: una tupla de cliente expandida por S1."""
    shortname: str
    cif: str | None
    system_id: str

@dataclass(frozen=True, slots=True)
class RvabrepRowTrigger(Trigger):
    """rvabrep-direct + as400-trigger: una fila RVABREP es un doc.
    Lleva la fila completa así S1 saltea la re-query.
    """
    row: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class LocalScanTrigger(Trigger):
    """local-scan: un archivo en disco + la fila RVABREP que lo
    describe. S1 produce exactamente un RVABREPDocument para este archivo.
    """
    file_path: Path
    row: Mapping[str, Any]
```

``TriggerRecord`` pasa a ser un alias backward-compat para
``ClientTrigger`` así el código existente (csv-trigger, single-doc,
tests) sigue compilando.

### 2. ``IndexingService`` (S1) pasa a ser polimórfico

El nuevo contrato: S1 **enriquece** un trigger en una lista de
instancias ``RVABREPDocument``. Dispatch por tipo de trigger:

```python
def enrich(self, trigger: Trigger) -> list[RVABREPDocument]:
    match trigger:
        case ClientTrigger():
            return self._expand_client(trigger)          # find_documents de hoy
        case RvabrepRowTrigger(row=row):
            return [self._row_to_document(row)]          # un doc, sin query
        case LocalScanTrigger(row=row):
            return [self._row_to_document(row)]          # un doc, sin query
```

``find_documents`` y ``find_documents_batch`` se quedan para el
camino de ``ClientTrigger`` (csv-trigger usa la query batched
IN-list para amortizar 50 lookups). Los otros subtipos no necesitan
batching porque su fila ya se conoce.

### 3. Las estrategias S0 emiten el subtipo correcto

- ``CsvTriggerStrategy`` → ``ClientTrigger`` (sin cambios de forma).
- ``DirectRvabrepTriggerStrategy`` → ``RvabrepRowTrigger`` por
  cada fila matcheada. **Se descarta el dedup por ``(shortname,
  system_id)``**. Los operadores que quieran un trigger por cliente
  deberían usar csv-trigger; rvabrep-direct ahora significa literal
  "un trigger por fila RVABREP".
- ``LocalScanTriggerStrategy`` → ``LocalScanTrigger`` por archivo
  escaneado. Cuando el archivo matchea múltiples filas RVABREP (raro
  — colisión de filename entre sistemas), emitir un
  ``LocalScanTrigger`` por cada fila matcheada.
- ``As400TriggerStrategy`` → ``ClientTrigger`` (sin cambios). El SQL
  definido por el operador puede proyectar desde cualquier tabla con
  cualquier alias de columna (típicamente NIARVILOG con semántica
  SHORTNAME/CIF/SYSTEMID), así que la fila ES una tupla de cliente
  por convención. Una spec futura podría introducir un modo
  per-doc para as400 si el upstream de producción lo pide.
- ``SingleDocTriggerStrategy`` → ``ClientTrigger`` (sin cambios).

### 4. Código downstream

- **S2 (mapping)**, **S3 (metadata)**, **S4 (assembly)**: leen
  campos de ``RVABREPDocument`` exclusivamente, NO campos del
  trigger — con una excepción (self-healing de CIF en S3).
- **Self-healing de CIF en S3**: hoy lee ``trigger.cif`` para
  cortocircuitar cuando el CSV tiene un CIF en blanco. El nuevo
  código lee CIF desde el trigger que lo surface:
  - ``ClientTrigger.cif`` (existente).
  - ``RvabrepRowTrigger.row[col_cif]``.
  - ``LocalScanTrigger.row[col_cif]``.

  Un helper ``_trigger_cif(trigger) -> str | None`` centraliza este
  lookup así el resolver no crece una sentencia match.
- **``_build_record``** en el orchestrator (que construye un
  ``MigrationRecord`` para tracking) llama a
  ``trigger.audit_row()`` para llenar ``trigger_shortname /
  trigger_cif / trigger_system_id``. Cada subtipo produce valores
  best-effort de lo que sea que lleve; las filas que no tienen los
  tres dejan el campo faltante en None.

### 5. Schema de migration_log

**Sin cambios de schema**. Las columnas existentes
(``trigger_shortname``, ``trigger_cif``, ``trigger_system_id``)
quedan como nullable text — igual que hoy, solo que pobladas a
través del accessor ``audit_row()``. La identidad canónica por-doc
sigue siendo ``rvabrep_txn_num`` (sin cambios). El audit trail
mantiene la misma forma; solo la fuente de esas tres columnas se
corre de "siempre los campos literales del trigger" a "proyección
best-effort de lo que sea que el trigger lleve".

## Fuera de alcance

- Renombrar o restructurar las tablas SQLite de migration_log.
- Agregar flags nuevas de CLI (p. ej. ``single-doc --txn-num``).
  Spec futura — single-doc se queda como ``ClientTrigger`` por ahora.
- Cambiar la semántica de csv-trigger. El modelo CSV-row → cliente →
  N docs es intencional y sin cambios.
- Remover el batching IN-list de ``find_documents_batch``. Sigue
  importando para csv-trigger y single-doc.
- Refactorizar S2/S3/S4 para que sean trigger-agnostic. Ya lo son
  en su mayoría; solo el self-healing de CIF de S3 lee del trigger
  y ese único camino gana una abstracción chica.
- Verificación de staging end-to-end de as400-trigger — no tenemos
  un AS400 alcanzable; los tests unitarios cubren el cambio de forma
  de la estrategia.

## Criterios de aceptación

- Los tests existentes de csv-trigger pasan sin cambios (alias
  ``TriggerRecord == ClientTrigger`` preservado).
- Nuevo test unitario: ``RvabrepRowTrigger`` fluye a través de S1
  sin pegarle a ``IDataSource`` (assertion vía un mock que falla el
  test si se hace una query).
- Nuevo test unitario: ``LocalScanTrigger`` fluye a través de S1
  produciendo exactamente un ``RVABREPDocument`` por trigger, incluso
  cuando el cliente subyacente tiene 50+ docs.
- Re-verify en vivo de §E.4 contra staging:
  - Mismo pool de 100 archivos en ``sample/local-scan-pool``.
  - Pre-046 vimos 1860 docs subidos (expansión demasiado amplia).
  - Post-046 debe subir **exactamente 100 docs** (uno por archivo).
- Las filas de ``migration_log`` de un run de rvabrep-direct todavía
  tienen ``trigger_shortname / trigger_cif / trigger_system_id``
  poblado (best-effort desde la fila).
- Entrada ``CHANGELOG.md [0.49.0]``.
- mypy + ruff limpios. Suite completa de unit + integration verde.

## Notas sobre estrategia de tests

El dispatch polimórfico necesita tres superficies de test:

1. **Tests unitarios por-subtipo** al nivel de ``IndexingService`` —
   verificar que el camino de código correcto se dispara para cada
   subtipo. Los casos de ``RvabrepRowTrigger`` y
   ``LocalScanTrigger`` pasan un ``MagicMock`` IDataSource que
   levanta si se llama a ``get_*``.
2. **Tests end-to-end del staged-pipeline** con cada estrategia
   enchufada. Los fixtures de test existentes ya cubren el camino
   csv; agregamos dos fixtures nuevos para rvabrep-direct (una fila
   seleccionada → exactamente ese doc subido) y local-scan (un
   archivo en el pool → exactamente ese doc subido).
3. **Re-run en vivo de §E.4** contra el Alfresco de staging como el
   gate de aceptación de integración.

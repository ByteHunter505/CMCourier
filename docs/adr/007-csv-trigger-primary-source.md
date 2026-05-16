> [← Volver al índice](../INDEX.md) · [ADRs](README.md)

# ADR-007: CSV externo como fuente primaria de triggers

- **Estado**: Aceptado y vigente
- **Fecha**: 2026-05-10
- **Spec(s) relacionadas**: 011 (csv-trigger-pipeline, primera pipeline de producción), 003 (tabular data source adapter), 014 (pipelines AS400 paralelas), 015 (AS400 metadata source)
- **Versión donde se shipping**: 0.13.0 (pipeline MVP de punta a punta)

## Contexto

Una "lista de triggers" es la entrada cero de la migración: el conjunto `(shortname, system_id, CIF opcional)` que indica qué documentos buscar en RVABREP y migrar a CM. Cada corrida del pipeline necesita esa lista para arrancar.

La opción ortodoxa habría sido **leer triggers directamente de AS400 vía pyodbc en cada corrida** — `RVABREP` (la tabla de indexing) vive en AS400, así que es natural pensar que los triggers también viven ahí. Pero el contexto operativo del banco hace que esa opción tenga problemas reales:

1. **AS400 + red corporativa + firewalls = baja confiabilidad.** El ODBC driver de iSeries Access no es robusto contra interrupciones de red. Una query que toma 30 segundos puede fallar si un proxy intermedio recicla la conexión. El operador no debería tener que pelearse con eso al inicio de cada corrida.
2. **Necesitamos corridas reproducibles.** Si dos corridas a 2 horas de distancia leen "triggers" desde AS400 directamente, pueden ver subconjuntos diferentes (nuevos triggers agregados, viejos modificados). Para debugging y para confianza operativa, queremos que "rerun the same input" sea trivial.
3. **El banco ya tiene un proceso nocturno que dumpea triggers a CSV.** Existe un pipeline interno del banco que produce un `TriggerList.csv` consolidado cada noche, en una ubicación de red conocida. Aprovechar ese artefacto es más barato y más confiable que duplicar la query AS400.
4. **Dependencia de AS400 uptime impacta operativamente.** Si AS400 está en mantenimiento o tiene problemas, queremos seguir pudiendo correr migraciones (los docs ya están en archivos; el CSV ya está volcado). Acoplar el arranque al estado de AS400 corta esa independencia.
5. **Debugging es 10× más fácil con un archivo plano.** El operador puede `bat triggers.csv | head -20`, editar manualmente para crear un mini-set de prueba, hacer `cp` para reproducir un caso. Con AS400 directo, todo eso requiere una herramienta separada.

## Decisión

La fuente primaria de triggers es un **CSV externo** generado por proceso nocturno del banco y leído por `CsvTriggerStrategy` via el puerto `S0Strategy`. La pipeline `csv-trigger-pipeline` es la default operativa.

- **`CsvTriggerStrategy`** valida columnas requeridas (`ShortName`, `SystemID`, `CIF` opcional), trata `CIF` blanco como `None` (CIF self-healing lo cubre en S3), skip-ea filas con `shortname`/`system_id` vacíos con un INFO log.
- **Lazy iteration**: el CSV se streamea, no se carga entero. Principio IV de la Constitución.
- **Columnas configurables** (`csv_trigger.shortname_column = "ShortName"`, `cif_column = "CIF"`, `system_id_column = "SystemID"`) para no romperse si el banco renombra columnas en su dump.

**Importante: AS400 no desaparece como source.** AS400 sigue siendo:

- La fuente de **RVABREP** (la tabla de indexing) — spec 014 + 015 mantienen el `As400DataSource` adapter para queries de indexing.
- Una fuente alternativa de triggers vía `rvabrep-pipeline` (spec 014) y `as400-trigger` para casos donde el banco no provee un CSV.
- La fuente opcional de idempotencia distribuida (spec 034) via `NIARVILOG`.

La decisión es de **default operativo**, no de exclusión. CSV es lo que recomendamos y lo que documentamos primero; AS400 directo está disponible para casos donde el operador lo necesita.

## Consecuencias

### Positivas

- **Corridas reproducibles trivialmente.** Mismo CSV de input → mismo input lógico de pipeline. Re-correr una corrida que falló es `cmcourier csv-trigger-pipeline run --config X --triggers triggers-2026-05-15.csv`.
- **Debugging operativo barato.** Operador puede hacer un mini-CSV de 5 triggers para reproducir un bug. Con AS400 directo necesitaría una herramienta separada para construir el mini-set.
- **Independencia del uptime de AS400 al arranque.** Si AS400 está caído, no podés indexar (S1 sigue necesitando AS400 si la config lo indica), pero al menos podés validar la config, correr `doctor`, hacer dry-runs.
- **Onboarding más simple.** Nuevos usuarios empiezan con `csv-trigger-pipeline` y un CSV de ejemplo (`reference-data/csv/TriggerExample.csv`). No necesitan setup de pyodbc + ODBC driver de iSeries para tocar la herramienta.
- **Source uniforme con tests.** El mismo `TabularDataSource` (spec 003) sirve para tests con fixtures CSV y para producción con triggers CSV. Cero divergencia entre lo que testeamos y lo que corremos.

### Negativas / Tradeoffs

- **Doble fuente de verdad si el proceso nocturno se desincroniza.** Si AS400 cambió pero el dump CSV no se regeneró, vamos a procesar datos viejos. Mitigamos esto con metadata en el header del CSV (timestamp del dump) que `doctor` y los logs registran, pero la responsabilidad del refresh es del operador del banco.
- **Latencia de propagación.** Cambios en AS400 que ocurren a las 9am no se ven hasta el dump nocturno. Aceptable para migración batch; no aceptable para sistemas tiempo-real (que no somos).
- **Dependencia de un volumen compartido.** El CSV vive en una ruta de red. Si ese share se cae, no podemos arrancar. Mitigado por el doctor check `log_dir_writable` extendido implícitamente — si el CSV no se puede abrir, la pipeline falla rápido con un error claro.
- **Por-cada-pipeline tenemos un strategy.** El paneo de `S0Strategy` (csv / rvabrep / local-scan / single-doc) implica que cada pipeline nueva implica un strategy nuevo o reusar uno existente. Es deuda de diseño pequeña, pero existe.

### Neutras

- **El strategy CSV es el más simple del set.** Un loop sobre `IDataSource.query_stream`. El test unitario es trivial. La complejidad real de S0 vive en `DirectRvabrepTriggerStrategy` (filtros + dedup), no acá.

## Alternativas consideradas

- **Query AS400 directa en cada corrida (la "ortodoxia").** Los problemas operativos listados en Contexto. Está disponible vía `as400-trigger-pipeline` para quien lo quiera, pero no es el default.
- **Cache local de la query AS400.** Habríamos tenido que diseñar invalidación, TTL, refresh manual. El CSV nocturno ya es justamente ese mecanismo, manejado por el banco con su propio scheduling. No vale la pena reinventar.
- **API REST del banco.** No existe.
- **Webhook / push desde AS400 a CMCourier.** Infra que no podemos construir (requiere cambios del lado del banco). El pull-del-CSV es lo que el banco ya soporta sin pedirles nada nuevo.
- **Excel como source primaria.** Probamos en specs tempranas. Pandas + openpyxl funciona pero es ~10× más lento que CSV y deja warnings sobre estilos. CSV es el formato de transferencia natural.

## Ver también

- [Spec 011 — csv-trigger-pipeline](../../specs/011-csv-trigger-pipeline/)
- [Spec 003 — tabular data source adapter](../../specs/003-tabular-data-source-adapter/)
- [Spec 014 — pipelines AS400](../../specs/014-as400-pipelines/)
- [Spec 015 — AS400 metadata source](../../specs/015-as400-metadata-source/)
- [Spec 046 — modelo Trigger polimórfico](../../specs/046-polymorphic-trigger/)
- [ADR-001: arquitectura hexagonal](001-hexagonal-architecture.md)

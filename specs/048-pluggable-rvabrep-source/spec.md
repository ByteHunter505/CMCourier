# 048 — Fuente RVABREP pluggable (CSV ↔ AS400)

## Por qué

El usuario corrigió una confusión cocinada en el modelo de trigger:
el pipeline ``rvabrep`` y el pipeline ``as400`` son **el mismo
pipeline**. Lo único que difiere es dónde vive la tabla RVABREP:

- **csv** — un archivo CSV simulando la tabla RVABREP (testing,
  dry-runs de staging, bancos chicos que exportan RVABREP a un
  archivo).
- **as400** — la tabla RVABREP en vivo en DB2/AS400, alcanzada por
  un ``SELECT`` que devuelve un result set con forma RVABREP. El
  SQL del operador puede llevar JOINs / filtros, pero las
  **columnas de output tienen forma RVABREP** — mismo contrato
  cualquiera de las dos vías.

La arquitectura actual (pre-048) se equivoca en esto en dos lugares:

1. ``IndexingSourceConfig`` (``schema.py:173``) hard-wirea la
   fuente RVABREP a un CSV: ``csv_path: FilePath`` es la única
   opción. ``wiring.py:78`` siempre construye
   ``TabularDataSource(config.indexing.csv_path)``. No hay manera
   de apuntar S0 (rvabrep-direct) o S1 (indexing) a AS400.
2. ``As400TriggerConfig`` contrabandeó el camino AS400 como un
   ``trigger.kind: as400`` SEPARADO llevando un ``query: str``
   arbitrario, manejado por un ``As400TriggerStrategy`` SEPARADO.
   Esa es una confusión strategy-vs-source: "dónde vive la data"
   quedó modelado como "cómo se descubren los triggers".

``DirectRvabrepTriggerStrategy`` ya acepta cualquier ``IDataSource``
— nunca necesitó un CSV específicamente. Y ``As400DataSource`` ya
soporta un modo ``query`` que envuelve el SQL como ``(query) AS T``
y expone el contrato completo de ``IDataSource``
(``get_all`` / ``get_by_fields`` / ``get_by_fields_in``). Las
piezas para componer esto limpiamente ya existen; 048 las wirea
juntas.

## Qué

### 1. La fuente RVABREP pasa a ser un union discriminado

Una nueva ``RvabrepSourceUnion`` discriminada por ``kind``:

```python
class CsvRvabrepSource(BaseModel):
    kind: Literal["csv"]
    csv_path: FilePath

class As400RvabrepSource(BaseModel):
    kind: Literal["as400"]
    connection: As400ConnectionConfig
    query: str   # SELECT devolviendo columnas con forma RVABREP; JOINs/filtros OK
```

``IndexingSourceConfig`` se renombra a ``IndexingConfig`` y su
campo ``csv_path`` se reemplaza por ``source: RvabrepSourceUnion``:

```yaml
indexing:
  source:
    kind: csv
    csv_path: sample/rvabrep-50k.csv
  columns: {...}
  batch_size: 50
```

```yaml
indexing:
  source:
    kind: as400
    connection: {host, port, database, driver}
    query: "SELECT ... FROM RVILIB.RVABREP r WHERE r.ABAACD = '3'"
  columns: {...}
  batch_size: 50
```

El bloque ``columns`` sigue funcionando para los dos — para la
variante AS400 el operador aliasea el output de su SELECT a los
nombres físicos de columnas de RVABREP (o sobrescribe ``columns``
para que matchee sus aliases).

### 2. El wiring construye la fuente una vez, alimenta S0 + S1

``wiring.py`` gana ``_build_rvabrep_source(indexing_cfg, secrets)
-> IDataSource``:

- ``CsvRvabrepSource`` → ``TabularDataSource(csv_path)``.
- ``As400RvabrepSource`` → ``As400DataSource(connection..., query=...)``
  — las credenciales vienen de ``secrets`` (env vars
  ``AS400_USERNAME`` / ``AS400_PASSWORD``), igual que el camino
  pre-048 del trigger ``as400``.

El ``IDataSource`` resultante es el único ``rvabrep_src`` pasado
a AMBOS:
- ``IndexingService`` (S1 — lookup de docs para csv-trigger +
  single-doc).
- ``DirectRvabrepTriggerStrategy`` (S0 — descubrimiento de
  triggers para rvabrep-direct).

Bonus: los pipelines csv-trigger y local-scan también ganan la
fuente RVABREP AS400 gratis — una lista de triggers CSV ahora
puede impulsar los lookups de S1 contra la tabla AS400 en vivo.

### 3. ``trigger.kind: as400`` se remueve

- ``As400TriggerConfig`` se borra de ``TriggerConfigUnion``.
- ``As400TriggerStrategy`` (``services/triggers/as400.py``) se
  borra — era redundante. El caso de uso "operador SQL con
  JOINs/filtros" queda cubierto por completo por
  ``As400RvabrepSource.query``:
  ``DirectRvabrepTriggerStrategy`` sobre un ``As400DataSource``
  construido desde esa query hace exactamente el mismo trabajo, y
  ahora el enrichment de S1 corre contra la misma fuente en vez
  de re-quereyar un CSV.
- Para correr "el pipeline rvabrep contra AS400" post-048:
  ``trigger.kind: rvabrep`` + ``indexing.source.kind: as400``.

Después de 048 los kinds de trigger son: ``csv``, ``rvabrep``,
``local_scan``, ``single_doc``. Cuatro, no cinco.

### 4. NIARVILOG queda intacto

``As400NiarvilogStore`` (spec 034) es el **tracking store de
idempotencia distribuida** a nivel AS400 — una preocupación
completamente separada de la fuente de datos RVABREP. 048 no lo
toca. ``As400ConnectionConfig`` se queda como tipo de config
compartido (usado por ``As400RvabrepSource`` y la config de sync
NIARVILOG).

## Fuera de alcance

- Un shim de migración del formato de config. El proyecto es
  pre-producción — cada config vive en-repo (``sample/*.yaml`` +
  fixtures de test). 048 los migra todos en la Fase 2; no hay
  configs de campo que preservar. Corte limpio, consistente con
  040-047.
- Empujar ``RvabrepFilters`` (systems / document_types) hacia
  abajo en la cláusula ``WHERE`` del AS400. Los filtros se siguen
  aplicando en Python por ``DirectRvabrepTriggerStrategy`` como
  hoy — el operador que quiera filtrado server-side lo cocina en
  su ``query``.
- Soporte de AS400 en ``metadata.sources`` — ese camino ya existe
  (``wiring.py`` ya construye ``As400DataSource`` para aliases de
  fuente de metadata). 048 solo toca la fuente RVABREP.
- Pool de conexiones / tuning de retry para la fuente RVABREP de
  AS400. ``As400DataSource`` ya tiene su comportamiento de retry;
  048 lo reusa sin cambios.

## Criterios de aceptación

- ``indexing.source.kind: csv`` construye un ``TabularDataSource``
  y los pipelines rvabrep + csv-trigger se comportan byte-idénticos
  a pre-048 (mismo output del smoke de staging).
- ``indexing.source.kind: as400`` construye un ``As400DataSource``
  en modo query; un test unit/integration confirma que
  ``DirectRvabrepTriggerStrategy`` e ``IndexingService`` ambos
  reciben esa fuente.
- ``trigger.kind: as400`` se rechaza por el config loader con un
  error claro apuntando a ``indexing.source.kind: as400``.
- ``services/triggers/as400.py`` se borra; ningún import de
  ``As400TriggerStrategy`` sobrevive en ningún lado.
- Los 6 configs ``sample/config-staging*.yaml`` migrados a
  ``indexing.source``.
- Todos los fixtures de test / YAML inline migrados; suite
  completa unit + integration verde.
- Re-verify en vivo: un run de staging con la
  ``config-staging-rvabrep.yaml`` migrada (``--total 5``) produce
  el mismo resultado que pre-048.
- Entrada ``CHANGELOG.md [0.51.0]``.
- mypy + ruff limpios.

## Notas sobre estrategia de tests

La fuente RVABREP de AS400 no se puede ejercitar contra un AS400
en vivo en CI (Constitución VI — AS400 nunca mockeado, pero el
cursor ``pyodbc`` SÍ se fakea a nivel driver, espejando el enfoque
de tests existente de ``As400DataSource``). La Fase 2 agrega:

- Un test unitario de wiring asserteando que
  ``_build_rvabrep_source`` devuelve un ``As400DataSource`` para
  la variante ``as400`` y un ``TabularDataSource`` para ``csv``.
- Un test del config loader asserteando que el discriminador
  ``RvabrepSourceUnion`` funciona y que ``trigger.kind: as400`` se
  rechaza.
- El fake a nivel driver existente de ``test_as400.py`` cubre el
  contrato del modo query de ``As400DataSource`` — no hacen falta
  tests nuevos de plomería de AS400.

El re-verify en vivo usa la variante CSV (la variante AS400 no
tiene servidor alcanzable); el camino CSV es el gate de
regresión.

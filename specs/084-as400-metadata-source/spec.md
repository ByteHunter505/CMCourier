# 084 — `as400:<alias>` metadata source + `lookup_value_source` configurable

## Por qué

Descubierto en producción enriqueciendo metadata desde AS400. Pre-084:

1. **`source_type: "as400:<alias>"` tiraba `NotImplementedError`** —
   `MetadataService._fetch_from_source` (metadata.py:371-376) decía:

   ```python
   raise NotImplementedError(
       "as400:<alias> source type is not yet supported."
   )
   ```

   El esqueleto de schema y validación existía
   (`As400MetadataSourceConfig`), y `wiring.py` ya registraba el
   adapter `As400DataSource` en el registry de metadata sources.
   Solo faltaba el `fetch`.

2. **Lookups CSV indexaban hardcoded por CIF del trigger** (línea 438).
   No había manera de buscar contra una tabla por otra clave —
   ej. "buscar descripción en operaciones por `rvabrep.txn_num`",
   "buscar región por `trigger.shortname`".

## Qué

### Cambios

1. **`SourceConfig` (dataclass)**: agregar
   `lookup_value_source: str = "trigger.cif"` para preservar
   backward-compat.

2. **`FieldSourceItem` (schema)**: mismo field + validator que
   exige formato `<scope>.<attr>` con scope `trigger` o `rvabrep`.

3. **`MetadataService._fetch_lookup`** (nuevo, unificado):
   reemplaza `_fetch_csv`. Maneja prefijos `csv:` y `as400:`
   indistintamente — el contrato `IDataSource` (port) ya los
   unifica.

4. **`MetadataService._resolve_lookup_value`** (nuevo helper):
   parsea `lookup_value_source` y devuelve el valor:
   - `"trigger.cif"` → honra `cif_override` (self-healing pre-046)
   - `"trigger.<attr>"` → atributo o `audit_row()` del trigger
   - `"rvabrep.<col>"` → atributo del `RVABREPDocument`

5. **`MetadataService._prefetch_csv_sources`** (extendido):
   ahora itera tanto CSV como AS400. El nombre se conserva por
   backward-compat de imports — internamente cubre ambos.

6. **`MetadataService._fetch_from_source`**: quita el
   `NotImplementedError` para `as400:` prefix.

### Uso

```yaml
metadata:
  sources:
    clientes_as400:
      kind: as400
      as400_connection:
        host: as400.banco.com
        port: 446
        database: PRODLIB
      query: "SELECT CIF, NOMBRE, REGION FROM PRODLIB.CLIENTES WHERE ABACST <> 'D'"

  field_sources:
    # Lookup AS400 por CIF (default lookup_value_source)
    BAC_Nombre_Cliente:
      sources:
        - source_type: "as400:clientes_as400"
          lookup_key_column: "CIF"
          lookup_value_column: "NOMBRE"

    # Lookup AS400 por columna del RVABREP
    BAC_Descripcion_Operacion:
      sources:
        - source_type: "as400:operaciones"
          lookup_key_column: "TXN"
          lookup_value_column: "DESC"
          lookup_value_source: "rvabrep.txn_num"

    # Lookup CSV por trigger.shortname (también nuevo)
    BAC_Region:
      sources:
        - source_type: "csv:regiones"
          lookup_key_column: "SHORT"
          lookup_value_column: "REGION"
          lookup_value_source: "trigger.shortname"
```

### Carga: prefetch al arranque

El AS400 metadata source corre `SELECT * FROM <table_or_query>` UNA
vez al construir `MetadataService` y cachea todas las filas indexadas
en memoria por `(alias, key_column, key_value, value_column)`.
Lookup runtime O(1). Tradeoff: el dataset debe caber en memoria.

Para datasets gigantes, el operador puede:
- Filtrar el `query` para traer solo lo necesario
  (`WHERE ABACST <> 'D' AND CREATION_DATE > ...`).
- Eventualmente, una spec futura puede agregar lookup on-demand con
  cache LRU.

### Tests

* `tests/unit/config/test_field_source_lookup_value_source.py`
  (default, scopes aceptados, scopes rechazados).
* `tests/unit/services/test_metadata_as400_lookup.py`
  (AS400 path, lookup_value_source por rvabrep, por trigger.shortname,
  errors).

## Criterios de aceptación

1. `source_type: "as400:foo"` con `foo` registrado en
   `sources_registry` resuelve sin `NotImplementedError`.
2. `lookup_value_source: "rvabrep.txn_num"` indexa contra el campo
   `txn_num` del `RVABREPDocument`, no contra el CIF del trigger.
3. `lookup_value_source: "trigger.shortname"` indexa contra
   `shortname` del trigger.
4. `lookup_value_source` default es `"trigger.cif"` — comportamiento
   pre-084 idéntico para configs existentes.
5. `pytest -m unit` pasa.

## Riesgos

* **Backward-compat de configs**: el default `"trigger.cif"`
  preserva 100% el comportamiento pre-084 de los lookups CSV. Configs
  pre-084 cargan idénticamente.
* **Carga de memoria AS400**: el prefetch lee TODA la tabla. Para
  tablas con millones de filas el operador debe usar `query` con
  `WHERE` para acotar. Documentado en el spec.
* **Adapter mismatch silencioso**: si un alias está registrado como
  CSV y el `source_type` dice `as400:` (o viceversa), el motor lo
  acepta porque el contrato `IDataSource` es el mismo. Confunde al
  lector pero no afecta corrección — la query se ejecuta contra el
  adapter registrado. Si en el futuro queremos endurecer, se puede
  agregar un check de `isinstance(adapter, expected_class)`.

## Notas

Pareja con spec 083 (`field_sources` solo con `default_value`). 083
cubre constantes; 084 cubre lookups dinámicos. Las dos juntas
eliminan los workarounds de "source dummy garantizado a fallar".

Próximo posible: lookup AS400 on-demand con cache LRU para datasets
que no caben en memoria; control de TTL para refrescar cache durante
runs largos.

# 074 — Strip whitespace de strings que vuelven del AS400

## Por qué

Los campos `CHAR(N)` en DB2 / iSeries vuelven **padded a longitud fija
con espacios**. Es el comportamiento canónico de COBOL/DB2 desde
siempre: un `CHAR(1)` con valor lógico vacío llega a Python como `" "`,
un `CHAR(8)` con valor `"SHORT1"` llega como `"SHORT1  "`.

Pre-074, CMCourier asumía que strings de pyodbc venían `rstrip`-eados
o `""` cuando vacíos. La asunción se quebró contra el RVABREP real
del banco:

* El check de "deleted" — `if _str(row.get("ABACST")):` — interpreta
  un `" "` (CHAR(1) padded) como **truthy** y tira
  `RVABREPDeletedError`. Resultado: todos los docs aparecen como
  "deleted" aunque ninguno lo esté en el origen.
* El matching de triggers contra RVABREP (`shortname` y `system_id`)
  puede fallar silenciosamente cuando el RVABREP devuelve
  `"SHORT1  "` y el CSV de triggers tiene `"SHORT1"`.
* El `txn_num` que termina en SQLite + CMIS como `cmis:name` queda
  con espacios al final — `migration_log.rvabrep_txn_num` y el
  filename del PDF subido a CM quedan con trailing whitespace,
  rompiendo la unicidad real de la idempotency key.
* Mismo problema para metadata sources AS400 — un lookup por
  `BRANCH_ID = "001     "` falla al matchear contra `"001"`.

**Estos no son bugs separados — es un único hueco en la frontera
adapter-domain**: el adapter AS400 leak-ea el detalle de
representación CHAR de DB2 al resto del sistema, y cada consumer
tiene que defenderse a mano (o fallar). La frontera correcta para
strippear es el adapter mismo.

## Qué

### Alcance

Un único punto de intervención: `As400DataSource` strippea trailing
whitespace de todos los valores `str` al materializar rows de pyodbc.

* `src/cmcourier/adapters/sources/as400.py:95` (`query`) y línea 137
  (`query_stream`): reemplazar la materialización inline
  `dict(zip(columns, row, strict=False))` por un helper
  `_normalize_row(columns, row)` que aplica `.strip()` a valores
  `str` y deja los demás tipos sin tocar (`int`, `float`, `Decimal`,
  `date`/`datetime`, `bool`, `None`, `bytes`).

* Helper `_normalize_row` privado al módulo `as400.py` — no se
  exporta. Función pura, sin side effects, fácil de testear
  unitariamente.

### Fuera de alcance

* **No se toca `TabularDataSource`** (CSV via pandas). Los CSVs no
  tienen el problema de padding fixed-width; si vienen con
  espacios, son intencionales. Strippearlos sería un cambio de
  semántica para tests existentes.
* **No se cambia el filtrado de deleted en sí** (la línea
  `if _str(row.get(delete_code_column)):` en
  `services/indexing.py:153`). Con 074, esa línea recibe valores
  ya stripped del adapter, así que sigue funcionando — pero ahora
  correctamente.
* **No se hace `.lstrip()`** — solo trailing whitespace (`.rstrip()`
  estricto). Espacios al inicio en un campo CHAR son data real,
  no padding. Decisión: usamos `.strip()` completo para simetría
  con cómo el código actual trata strings (más seguro porque
  ningún campo del RVABREP debería empezar con espacio
  legítimamente, y los matchings de igualdad son sobre tokens sin
  espacios al borde). Si aparece un caso real donde leading
  whitespace es significativo, lo revisamos.
* **No se aplica a binary / `bytes`** — los `bytes` no se touch.

### Criterios de aceptación

1. Una fila pyodbc con `ABACST = " "` (un espacio) se materializa
   como `{"ABACST": ""}` (string vacío trimmed).
2. Una fila pyodbc con `ABABCD = "SHORT1  "` se materializa como
   `{"ABABCD": "SHORT1"}`.
3. Una fila pyodbc con `ABABUN = 5` (int) se materializa como
   `{"ABABUN": 5}` (int sin tocar).
4. Una fila pyodbc con `ABAADT = date(2026, 5, 17)` se materializa
   con el `date` intacto.
5. Una fila pyodbc con `EXTRA_COL = None` se materializa con
   `None` intacto.
6. `query()` y `query_stream()` producen rows **idénticas en
   forma** — ambas pasan por `_normalize_row`.
7. Tests unit nuevos cubren los 5 casos de arriba.
8. Suite completa (`pytest -m unit`) pasa sin regresiones.
9. El check `_enrich_known_row` ya no tira `RVABREPDeletedError`
   contra un RVABREP cuyo `ABACST` vienen padded con espacio
   (verificado con un test integration o stub).

## Riesgos

* **Cambio de comportamiento observable** para operadores que
  hacían queries `as400-query "SELECT ..."` y veían los strings
  con padding. Post-074 los ven trimmed. **Esto es deseable** —
  el padding nunca era información, era ruido de representación.
* **Doble strip en lugares que ya hacen strip explícito** (si los
  hay). No-op; cero costo. No regresión.
* **Tests existentes que mockean As400DataSource con rows
  pre-strippeadas** siguen funcionando — los mocks pasan dicts
  directamente sin pasar por `_normalize_row`.

## No-riesgos (verificado)

* **No afecta CSVs**: el `TabularDataSource` (pandas) no se toca.
* **No afecta los tests existentes del adapter AS400**: los mocks
  de pyodbc en tests pasan rows con strings ya limpios (sin
  padding artificial), así que el strip es no-op para ellos.

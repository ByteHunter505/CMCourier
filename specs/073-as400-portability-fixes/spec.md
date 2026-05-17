# 073 — Portability fixes para AS400 real

## Por qué

Durante la primera preparación productiva de CMCourier contra el AS400
real del banco (cliente Windows, conectividad ODBC, RVABREP en
`RVILIB`), tres bugs salieron a la luz que bloquean cualquier corrida
nueva. Los tres son 1-2 líneas de código + tests; ninguno cambia
arquitectura. Se shippean juntos porque pertenecen al mismo dominio:
"hacer que CMCourier funcione contra un AS400 real desde una compu
Windows que no es la del autor original".

### Bug 1 — doctor `as400_connectivity` envía SQL inválido para DB2

`cli/doctor.py:379` ejecuta:

```python
src.query("SELECT 1", [])
```

`SELECT 1` (sin `FROM`) es legal en MySQL/Postgres/SQL Server pero
**no en DB2/AS400**. DB2 exige una cláusula `FROM`. El check tira
`sqlstate=42000` ("syntax error or access violation") y el doctor
falla — bloquea el flujo aunque la conexión, las credenciales y la
red estén OK.

La pseudo-tabla canónica de DB2 para health checks es
`SYSIBM.SYSDUMMY1` (siempre tiene exactamente una fila con una
columna `IBMREQD`). La query correcta es
`SELECT 1 FROM SYSIBM.SYSDUMMY1`.

### Bug 2 — `mock generate --rvabrep-as400` ignora `source.query` y arma table sin schema

`cli/commands/mock.py:259-267` construye el `As400DataSource` solo
con `table` (no con `query`), y el default es `"RVABREP"` *bare* —
sin prefijo de library:

```python
return As400DataSource(
    ...
    table=conn.table or "RVABREP",
)
```

Dos consecuencias:

1. El `query` con `WHERE` que el operador definió en
   `indexing.source.query` se **ignora completamente** por el mock
   generate. Si el operador quiso acotar la generación con un
   filtro, no funciona — el mock lee la tabla entera.
2. Cuando `connection.table` no está seteado (común — su default
   en el schema es `None`), el adapter ejecuta `SELECT * FROM RVABREP`
   sin schema. Si la library `RVILIB` no está en la library list
   del usuario AS400, falla con `table not found`.

### Bug 3 — `mock generate` planner aborta ante un `ABABST` desconocido

`services/mock/planner.py:215-233` tiene los códigos de `image_type`
hardcoded:

```python
_TIFF_CODE = "B"
_JPEG_CODE = "C"
_PDF_CODE  = "O"
```

Cualquier fila con `ABABST` distinto a `B`/`C`/`O` (vacío, `null`,
un código del banco que no estaba en el RVABREP del banco original
— `T`, `P`, `D`, etc.) tira `ConfigurationError "unknown image_type"`
y aborta toda la generación.

El planner debe ser **permisivo**: ante un código desconocido o
contradictorio (`ABABST=O` con filename no-PDF), emitir un warning
estructurado y skipear esa fila, no abortar. La generación sigue
con el resto. El operador después decide si filtrar el origen, fix
el mapeo, o dejar esos docs sin materializar.

## Qué

### Alcance

* **`src/cmcourier/cli/doctor.py`** línea 379: cambiar `"SELECT 1"`
  por `"SELECT 1 FROM SYSIBM.SYSDUMMY1"`.

* **`src/cmcourier/cli/commands/mock.py`** líneas 259-267:
  - Si `source.query` está seteado, pasarlo como `query=...` al
    `As400DataSource`. El adapter ya soporta el modo query
    (`_source_expr = f"({query}) AS T"`).
  - Si NO hay query y `connection.table` no está seteado, el
    fallback debe ser `f"{conn.database}.RVABREP"` (con schema)
    en vez de `"RVABREP"` bare.

* **`src/cmcourier/services/mock/planner.py`** líneas 215-233 y el
  llamador en línea 156:
  - `_dispatch_image_kind` deja de tirar `ConfigurationError`
    para `unknown` y para `ABABST=O en filename no-PDF`. En su
    lugar, devuelve `None` (o sentinel) para indicar "fila a
    skipear".
  - El loop que llama `_dispatch_image_kind` revisa el resultado;
    si es `None`, emite un `_log.warning` estructurado y hace
    `continue` (no `yield` esa fila).

### Fuera de alcance

* No tocamos los códigos hardcoded `_TIFF_CODE`/`_JPEG_CODE`/`_PDF_CODE`.
  Hacer un `image_type_map` configurable en el planner es un cambio
  más grande; queda para una spec futura si aparece la necesidad.
* No tocamos el `assembly.image_type_map` del YAML (que sí existe
  y es configurable — se usa en el assembler real, no en el mock
  planner).
* No reescribimos otros health checks. Si aparecen más queries
  hardcodeadas DB2-incompatibles, se atacan en specs subsiguientes.

## Criterios de aceptación

1. `cmcourier doctor --config X` ejecuta `SELECT 1 FROM SYSIBM.SYSDUMMY1`
   contra el AS400 (verificado con unit test que mockea pyodbc y
   captura el SQL ejecutado).
2. `cmcourier mock generate --rvabrep-as400 --config X --root Y ...`
   con `source.query` seteado en el YAML ejecuta esa query (no
   `SELECT * FROM <table>`).
3. `cmcourier mock generate --rvabrep-as400 --config X --root Y ...`
   con `connection.table` ausente ejecuta `SELECT * FROM RVILIB.RVABREP`
   (con schema), no `SELECT * FROM RVABREP`.
4. `cmcourier mock generate --rvabrep-csv X.csv --root Y ...` donde
   `X.csv` tiene 10 filas con `ABABST` mezclado (5 conocidas, 5
   desconocidas) produce planes para las 5 conocidas y loguea 5
   warnings — no aborta.
5. `pytest -m unit` pasa.
6. Pre-commit (ruff + ruff-format + mypy) pasa.

## Riesgos

* **Comportamiento permisivo del planner cambia un contrato** que
  hoy era strict. Operadores que dependían del fail-fast para
  detectar RVABREP malformado pierden esa señal. Mitigación: el
  warning estructurado es loggeable y filtrable por consola y por
  log analysis. Quien quiera fail-fast puede grep-ear los warnings
  post-run.
* **Schema del query mock generate**: si el operador tiene
  `indexing.source.query` apuntando a una tabla NO-RVABREP
  (alguna join compleja, o una pre-procesada), el mock generate
  ahora la va a usar. Si esa query no devuelve la forma RVABREP
  esperada, el planner falla más adelante con campos faltantes.
  Pero esto es comportamiento correcto — el operador escribió la
  query, el operador asume la responsabilidad.

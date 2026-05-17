# 073 — Plan

## Decisiones técnicas

### Fix 1 — `SELECT 1 FROM SYSIBM.SYSDUMMY1`

Cambio mecánico. `SYSIBM.SYSDUMMY1` es la pseudo-tabla canónica
provista por DB2 / iSeries para health checks. Existe en todos los
sistemas DB2 (LUW, z/OS, i Series). No requiere permisos especiales.

### Fix 2 — mock generate respeta `source.query` y prepende schema

`_build_source` en `cli/commands/mock.py` tiene que distinguir tres
casos cuando es modo `--rvabrep-as400`:

1. **`source.query` seteado** → pasar `query=source.query` al
   `As400DataSource`. El adapter lo wrappea como `(query) AS T`,
   permitiendo cualquier WHERE, JOIN, LIMIT.
2. **`source.query` vacío Y `connection.table` seteado** → pasar
   `table=connection.table` (asumimos que el operador puso schema
   ahí si lo necesita).
3. **Ambos vacíos** → fallback a `table=f"{conn.database}.RVABREP"`,
   que prepende schema. NO `"RVABREP"` bare como hoy.

Caso 1 es nuevo; casos 2-3 cubren backward compat.

Decisión: el código no valida que `source.query` devuelva forma
RVABREP. Eso es responsabilidad del operador (Constitution IX:
"verify before claiming" se aplica al operador también).

### Fix 3 — planner permisivo

Tres cambios coordinados en `services/mock/planner.py`:

1. `_dispatch_image_kind` cambia tipo de retorno de `FileKind` a
   `FileKind | None`. Cuando hoy tira `ConfigurationError`, ahora
   devuelve `None`.
2. El loop en `plan_files` (línea ~155) revisa el resultado: si es
   `None`, emite `_log.warning(...)` con `txn_num`, `image_type`,
   `reason` ("unknown_image_type" o "pdf_code_on_non_pdf_filename")
   y hace `continue`.
3. El warning es **estructurado** (atributo `extra={...}` del
   logger), no print. Las herramientas downstream (`cmcourier analyze`)
   lo pueden agregar.

Decisión: no agregamos un contador en el reporte final ("N filas
saltadas por image_type desconocido"). Si lo querés en el futuro,
es otra spec — hoy solo el log basta. El operador tiene el archivo
de log para grep.

## Tests

### Test 1: doctor envía la query correcta

`tests/unit/cli/test_doctor_as400.py` (nuevo o extender existente):

* Mockear `As400DataSource` para capturar el SQL que se le pasa.
* Llamar `_check_as400_connectivity(config, secrets)`.
* Aseverar que el SQL capturado es `"SELECT 1 FROM SYSIBM.SYSDUMMY1"`.

### Test 2: mock generate respeta query y prepende schema

`tests/unit/cli/commands/test_mock_generate_as400.py` (nuevo):

* Crear un `PipelineConfig` con `indexing.source.kind: as400` y
  `query: "SELECT * FROM RVILIB.RVABREP WHERE ABACST <> 'D'"`.
* Mockear `As400DataSource.__init__` para capturar los kwargs.
* Llamar `_build_source(rvabrep_csv=None, rvabrep_as400=True, config=cfg)`.
* Aseverar que recibió `query="SELECT * FROM RVILIB.RVABREP WHERE ABACST <> 'D'"`.

Segundo test (defaults):

* `PipelineConfig` con `indexing.source.kind: as400` y `query=None`
  (o vacío) y `connection.table=None`.
* Aseverar que recibió `table="RVILIB.RVABREP"` (con schema), no
  `"RVABREP"`.

### Test 3: planner permisivo

`tests/unit/services/mock/test_planner_permissive.py` (nuevo):

* Input: lista de 6 filas RVABREP — 2 con `ABABST="B"`, 2 con
  `ABABST="O"` + filename `.PDF`, 1 con `ABABST="T"`, 1 con
  `ABABST=""`.
* Llamar `plan_files(rows, columns, filters, bounds)`.
* Aseverar: yielda 4 planes (las B y las O válidas), NO tira
  exception.
* Aseverar (con `caplog`): hay 2 records WARNING con
  `image_type="T"` y `image_type=""` respectivamente.

## Phased commits

1. `feat: add 073 spec, plan, tasks`
2. `fix(doctor): use SYSIBM.SYSDUMMY1 for AS400 health-check query`
3. `fix(mock): respect indexing.source.query + prepend schema in fallback table`
4. `fix(mock): warn-and-skip unknown image_type instead of aborting`
5. `test: cover 073 doctor + mock generate + planner permissive`
6. `docs(073): CHANGELOG 0.75.0 + version bump`

Cada commit pasa pre-commit (ruff + mypy) por sí solo. Strict TDD:
red → green → refactor. El operador puede ejecutar `pytest -m unit`
después de cada commit para verificar.

## Verificación post-cambio

```bash
# Tests pasan
pytest -m unit

# Smoke contra AS400 real
cmcourier doctor --config <prod-config>     # as400_connectivity ✓
cmcourier mock generate --rvabrep-as400 --config <prod-config> --root /tmp/mock --dry-run --limit 5
# Lee SELECT * FROM (<query del YAML>) AS T, planea 5 archivos.

# Mock generate con RVABREP de banco heterogéneo
cmcourier mock generate --rvabrep-csv <heterogeneo.csv> --root /tmp/mock
# Genera para los códigos conocidos, loguea warnings para el resto.
```

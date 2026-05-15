# 035 — División del CSV de mapeo + columna CMISType

## Por qué

El mapeo en producción del banco se compone de **dos CSV separados**:

- `MapeoRVI_CM.csv` — `IDSistema, IDRVI, IDCM, IDClaseDocumental` (+ nueva columna `CMISType`)
- `MetadatosCM.csv` — `IDCorto, Metadato, Requerido`

Hoy CMCourier lee un único fixture de prueba **consolidado**
`modelo_documental.csv` con todas las columnas en línea más una celda
`METADATOS` separada por comas. Ese formato no existe en producción.

034 introdujo `CMMapping.cmis_type` y un valor por defecto de `""`. La
columna `TIPIDN` de `NIARVILOG` en el AS400 hoy se escribe vacía hasta
que llegue la columna `CMISType` del CSV de producción. **035
desbloquea ese campo.**

## Qué

1. **Soporte de dos modos en `MappingConfig`**:
   - Modo consolidado (legado, amigable para fixtures de prueba):
     único `csv_path` más los campos de nombre de columna existentes.
   - Modo dividido (producción): `rvi_cm_csv_path` +
     `metadatos_csv_path` con sus propios campos de nombre de columna.
   - El `model_validator` fuerza exactamente uno: o se define
     `csv_path`, o se definen ambas rutas divididas. Nunca ambas,
     nunca ninguna.

2. **Cargador de modo dividido en `MappingService`**:
   - Argumento opcional adicional de constructor `IDataSource`
     (`metadata_source`). Cuando está presente, el servicio une las
     dos fuentes por `IDCorto ↔ IDCM` y construye el caché en
     memoria.
   - En modo dividido, `CMMapping.clase_name` toma por defecto el
     valor de `clase_id` (el CSV de producción no tiene una columna
     con nombre legible — confirmado por el banco).
   - `MetadatosCM.Requerido` se parsea sin sensibilidad de mayúsculas;
     `Yes` / `Sí` / `True` / `1` significan requerido. Cualquier otra
     cosa se descarta de `required_metadata_fields`.

3. **Expansión de `MappingColumnsConfig`**:
   - Agrega los nombres de columna del modo dividido (los valores por
     defecto coinciden con los encabezados reales del CSV: `IDRVI`,
     `IDCM`, `IDClaseDocumental`, `CMISType`, `IDCorto`, `Metadato`,
     `Requerido`).
   - Agrega `col_required_marker` con valor por defecto `"Yes"` (la
     convención del banco — coincide con
     `docs/samples/csv/MetadatosCM.csv`).

4. **`cmis_type_column` expuesta en `MappingConfig`** (brecha de 034):
   El esquema pydantic previamente no la propagaba. Después de 035 el
   modo consolidado también soporta una sobreescritura explícita de
   `cmis_type_column`.

5. **Helper de cableado `build_mapping_service(MappingConfig) -> MappingService`**:
   Una única fábrica que consumen los cuatro puntos de llamada
   (`config/wiring.py`, `cli/doctor.py` ×2,
   `cli/commands/inspect.py` ×2). El despacho por modo vive en un
   solo lugar.

6. **Actualización del CSV de muestra**:
   - `docs/samples/csv/MapeoRVI_CM.csv` gana una columna `CMISType`
     con valores placeholder vacíos (el banco los completa al momento
     del despliegue).

7. **Docs**:
   - Se remueve la entrada de limitaciones conocidas en
     `docs/how-to/as400-sync.md` que apunta a 035 (TIPIDN ya no está
     vacía en modo dividido).
   - Ejemplo en la guía de configuración mostrando ambos modos.

## Compatibilidad hacia atrás

- Las 857 pruebas existentes usan el fixture de prueba consolidado
  `modelo_documental.csv`. **Ninguna se rompe.** El modo consolidado
  es el predeterminado cuando solo se define `csv_path`.
- Se preserva el patrón de lectura de `MapeoRVI_CM.csv` del migrador
  paralelo Java — solo se **agrega** la columna `CMISType`; los
  lectores existentes ignoran columnas finales desconocidas.

## Fuera de alcance

- Leer el `MapeoRVI_CM.csv` de producción **con valores de CMISType
  completados**: ese archivo es propiedad del banco. Solo entregamos
  la infraestructura para que el archivo funcione cuando nos lo
  pasen.
- Migrar los fixtures de prueba al formato dividido. Se mantienen
  consolidados — eso ejercita el modo legado.
- Cambiar la representación de `clase_name` en cualquier salida
  (logs, inspect). Los operadores ven `clase_id` en modo dividido;
  ese es el `trade-off` documentado.

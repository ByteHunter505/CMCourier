# 039 — Generador de CSV RVABREP mock

## Por qué

Los dry-runs de staging y los tests de estrés necesitan un CSV
RVABREP a escala realista (decenas de miles de filas). El
`cmcourier mock generate` (031) existente materializa **archivos
en disco** desde un CSV RVABREP pero no genera el CSV en sí — el
operador tiene que traer el suyo. Hoy el fixture más grande del
repo tiene ~10 filas (`tests/fixtures/pipeline/rvabrep.csv`),
curado a mano para tests unitarios, no representativo de un `batch`
real.

Sin un generador, el operador queda con:
- Armar CSVs a mano (lento, propenso a errores, sin determinismo), o
- Tomar `snapshots` de datos del banco (no permitido por razones de
  PII, además de contaminación cruzada de entornos), o
- Escribir scripts Python descartables que desaparecen tras el test
  (sin reproducibilidad, sin semánticas de distribución
  compartidas).

039 cierra esa brecha con una pequeña superficie CLI aditiva:
`cmcourier mock rvabrep` escribe un CSV honrando la forma de
columnas documentada en `la spec`, con distribuciones deterministas
por semilla que coinciden con patrones observados del banco.

## Qué

### CLI

Nuevo subcomando bajo el grupo `mock` existente:

```
cmcourier mock rvabrep \
  --rows 50000 \
  --output sample/rvabrep-50k.csv \
  --seed 50000 \
  [--idrvi-source <csv_path>] \
  [--idrvi-top 20] \
  [--image-mix tiff:60,pdf:20,jpeg:20] \
  [--date-from 2024-01-01] [--date-to 2025-12-31] \
  [--clients 5000] \
  [--delete-rate 0.05] \
  [--cif-rate 0.95]
```

Todos los flags tienen valores por defecto; `--rows` y `--output`
son las únicas posiciones requeridas (output como posicional
también es aceptable).

### Forma de salida

Encabezado (nombres amigables — coincide con los valores por
defecto de `IndexingService.IndexingColumnsConfig` y con lo que el
subcomando `mock generate` existente lee):

```
shortname,system_id,txn_num,delete_code,index2,index3,index4,index5,index6,index7,image_type,image_path,file_name,creation_date,last_view_date,total_pages
```

### Reglas de generación por columna

| Columna | Regla |
| --- | --- |
| `shortname` | Uno de `--clients` (por defecto 5000) identificadores distintos, formato `<NAME><NN>` donde NAME son 6-10 letras ASCII mayúsculas de un léxico pequeño (`JUAN`, `MARIA`, `PEDRO`, `EMPRESA`, …) y NN son 2 dígitos. Sorteo uniforme entre clientes — promedio ≈ `--rows / --clients` documentos por cliente. |
| `system_id` | 70% `"1"`, 15% `"5"`, 10% `"2"`, 5% `"3"`. Coincide con la mezcla observada en `RVILIB_RVABREP.xlsx`. Configurable en un cambio futuro si hace falta. |
| `txn_num` | Globalmente único. 7 caracteres base32 (`A-Z` + `2-7`) deterministas a partir del índice de fila + semilla, prefijados con `T`. Formato: `T<6 base32 chars>` → 32^6 = 1 073 741 824 valores distintos (margen para `batches` de hasta ~1G filas). |
| `delete_code` | `"D"` con probabilidad `--delete-rate` (por defecto 0.05), `""` de lo contrario. |
| `index2` (CIF) | `""` con probabilidad `1 - --cif-rate` (por defecto 0.95). De lo contrario, un numérico de 6 dígitos. Un CIF por cliente (cada cliente tiene un CIF estable elegido al momento de creación del cliente, luego reusado para cada documento de ese cliente). |
| `index3` / `index4` / `index5` / `index6` | Siempre `""` (coincide con todas las muestras que tenemos). |
| `index7` (ID RVI) | Sorteado de un set pequeño (`--idrvi-top`, por defecto 20) muestreado desde `--idrvi-source` (por defecto `docs/samples/csv/MapeoRVI_CM.csv`, columna IDRVI). La distribución sigue Zipf — el IDRVI más popular captura ~30% de filas, el segundo ~15%, etc. (Pareto 80/20 con α=1.07). |
| `image_type` | Sorteado desde `--image-mix`. Por defecto `tiff:60,pdf:20,jpeg:20`. Mapea a `B` / `O` / `C` respectivamente. |
| `image_path` | `PROD/<YYYY>/<MM>/<DD>` derivado del `creation_date` de la fila. |
| `file_name` | Letra de prefijo alineada con `image_type` (`D`/`M` para B/TIFF, `C` para JPEG, `0` para PDF). Cuerpo: 7 caracteres alfanuméricos random. Extensión: `.001` para paginado (TIFF/JPEG), `.PDF` para PDF. |
| `creation_date` | Formato CYYMMDD. Sorteo uniforme en el rango `[--date-from, --date-to]`. Rango por defecto 2024-01-01 a 2025-12-31. |
| `last_view_date` | `"0"` con probabilidad 0.9. De lo contrario CYYMMDD entre `creation_date` y `--date-to`. |
| `total_pages` | `1` para filas PDF. Filas paginadas: 70% en `[1, 5]`, 25% en `[6, 50]`, 5% en `[51, 540]`. |

### Determinismo

Una única instancia `random.Random(seed)` dirige cada elección. La
misma `--seed` produce siempre salida byte-idéntica (módulo el
manejo de saltos de línea del OS). Coincide con el comportamiento
existente de `mock generate` y es requerido por la Constitución §VII
(Spec Antes de Código — las specs solo se verifican
end-to-end si el generador es reproducible).

### Invariantes de validación

El generador verifica antes de escribir:
- Todos los valores `txn_num` son únicos.
- Todos los valores `shortname` aparecen en al menos una fila.
- Todos los valores `index7` son miembros del set
  `--idrvi-source`.
- `image_type` / extensión de `file_name` son consistentes
  (`O` → `.PDF`, `B`/`C` → extensión numérica).
- `total_pages == 1` para filas PDF.
- Los strings de fecha son CYYMMDD válidos (parseables por
  `domain.models.parse_cymmdd`).

Cualquier falla de invariante lanza `ConfigurationError` con el
índice de fila en `context`. El generador sale con código no-cero
antes de escribir un CSV parcial.

## Fuera de alcance

- Generar archivos físicos en disco — ya está cubierto por
  `cmcourier mock generate`. Los operadores encadenan los dos:
  `mock rvabrep` produce el CSV, luego `mock generate
  --rvabrep-csv <path>` materializa los archivos.
- Generación de CSV de trigger. Los triggers pueden derivarse de la
  salida de RVABREP si hace falta; diferido a una spec futura.
- Sembrado del AS400 NIARVILOG. El RVABREP mock es
  filesystem-only.
- OCR / contenido realistas. Los archivos materializados por
  `mock generate` siguen siendo `fillers` de páginas en blanco —
  fuera de alcance según 031.
- El pre-flight `cm-targets` del doctor contra el set de IDRVI
  generado. Si el operador apunta el doctor al Alfresco de staging
  con 20 IDRVIs pero solo un tipo CMIS registrado, el doctor va a
  FAIL para 19 de ellos. Es responsabilidad del operador
  configurarlo (registrar más tipos o sobrescribir `--idrvi-top 1`).

## Criterios de aceptación

- `cmcourier mock rvabrep --rows 50000 --output /tmp/r.csv --seed 50000`
  corre en < 5 segundos en una laptop y produce un CSV de 50000
  filas.
- El CSV generado pasa `cmcourier inspect rvabrep
  --config <stub.yaml>` para cada fila.
- Re-correr con la misma semilla produce un archivo byte-idéntico
  (módulo `\r\n` en Windows).
- Re-correr con una semilla distinta produce un archivo distinto.
- El CSV generado puede alimentarse al `cmcourier mock generate
  --rvabrep-csv <path>` existente y materializan 50000 archivos
  físicos sin error.
- `parse_cymmdd` acepta cada valor de `creation_date` y
  `last_view_date != "0"` en la salida.
- Los tests unitarios cubren cada función del generador en
  aislamiento.
- Un test de integración corre el CLI completo con `--rows 100` y
  verifica que el CSV pase la resolución de `MappingService`
  end-to-end (uniéndose contra `docs/samples/csv/MapeoRVI_CM.csv`).
- `mypy --strict` limpio sobre el nuevo módulo de servicio.
- `ruff` limpio.
- Entrada `[0.42.0]` del CHANGELOG.

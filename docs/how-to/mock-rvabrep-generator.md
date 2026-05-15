# How-to: Generar un CSV RVABREP sintético (039)

> Estado: `[0.42.0]` y posterior. Runbook de operador para el subcomando
> `cmcourier mock rvabrep`.

La superficie de testing del pipeline necesitaba algo entre los fixtures
de 10 filas curados a mano que shippea el repo y los exports RVABREP
reales del banco (que están cargados de PII y fuera de límites para
trabajo externo). `cmcourier mock rvabrep` llena el hueco: produce un
CSV determinista por semilla a cualquier escala — 100, 50 000, 1 000 000 —
que el `cmcourier mock generate` (031) existente consume directamente para
materializar el árbol de archivos en disco.

## TL;DR

```bash
# 1. Generar 50k filas en <5s
cmcourier mock rvabrep \
  --rows 50000 \
  --output sample/rvabrep-50k.csv \
  --seed 50000

# 2. Materializar 50k archivos físicos desde ese CSV
cmcourier mock generate \
  --rvabrep-csv sample/rvabrep-50k.csv \
  --root sample/files \
  --pdf-min 100kb --pdf-max 2mb \
  --img-min 20kb --img-max 200kb \
  --seed 1
```

El header del CSV usa **códigos ABA** (`ABABCD`, `ABAANB`, `ABAHCD`, ...)
— los mismos nombres de columna a los que `IndexingColumnsModel` apunta
por default. No se necesita override de config en ningún stage downstream
(mock generate, los runners de pipeline, `doctor`).

## §1 — Qué se genera

Según la forma de columnas de la spec:

| código ABA | Significado amigable | Regla de generación |
| --- | --- | --- |
| `ABABCD` | shortname | Pool de `--clients` (default 5000) identificadores distintos de un pequeño lexicon bancario + sufijo de 2 dígitos |
| `ABAACD` | system_id | 70% `"1"` / 15% `"5"` / 10% `"2"` / 5% `"3"` |
| `ABAANB` | txn_num | `T` + 6 chars base32 determinista del índice de fila — globalmente único |
| `ABACST` | delete_code | `"D"` con probabilidad `--delete-rate` (default 5%), `""` si no |
| `ABACCD` | index2 / CIF | Un CIF estable de 6 dígitos por cliente; presente con probabilidad `--cif-rate` (default 95%) |
| `ABADCD`..`ABAGCD` | index3..6 | Siempre en blanco (matchea cada sample observado) |
| `ABAHCD` | index7 / IDRVI | Sorteo ponderado Zipf desde los top `--idrvi-top` (default 20) IDRVIs en `--idrvi-source` (default `docs/samples/csv/MapeoRVI_CM.csv`). El IDRVI más popular recibe ~30% del volumen, el segundo ~15%, etc. |
| `ABABST` | image_type | `--image-mix` (default `tiff:60,pdf:20,jpeg:20`) → `B` / `O` / `C` |
| `ABAICD` | image_path | `PROD/YYYY/MM/DD` derivado de creation_date |
| `ABAJCD` | file_name | Letra de prefijo alineada con image_type (`D`/`M` para B, `C` para C, `0` para O) + body random de 7 chars + extensión correcta (`.001` para paged, `.PDF` para nativo) |
| `ABAADT` | creation_date | CYYMMDD uniforme en `[--date-from, --date-to]` (default 2024-01-01..2025-12-31) |
| `ABABDT` | last_view_date | `"0"` con probabilidad 0.9, si no CYYMMDD ≥ creation_date |
| `ABABUN` | total_pages | `1` para filas PDF; para paged: 70% en `[1,5]`, 25% en `[6,50]`, 5% en `[51,540]` |

Cada fila se valida antes de escribir (extensión correcta, `ABABUN`
entero, CYYMMDD parseable, etc.). Cualquier fallo de invariante levanta
`ConfigurationError` con el índice de fila — el generador nunca escribe
un CSV parcial.

## §2 — Reproducibilidad

Una sola `--seed` maneja cada elección. Misma semilla = output
byte-idéntico, cada vez, en cada host. Esto se mantiene a través de:

- Invocaciones múltiples en la misma máquina.
- Hosts distintos (modulo política de fin de línea — el writer usa
  los defaults de `csv.writer`, así que `\r\n` en Windows y `\n` en POSIX).
- Versiones menores distintas de Python (3.11, 3.12).

La semilla para `mock rvabrep` es **independiente** de la semilla para
`mock generate` — la primera determina la distribución de filas, la
segunda determina el contenido de los archivos dentro de esas filas.

## §3 — Escalas

| Escala | Wall clock | Tamaño output |
| --- | --- | --- |
| 100 filas | < 0.5 s | ~12 KB |
| 1 000 filas | < 0.5 s | ~120 KB |
| 50 000 filas | ~3 s | ~6 MB |
| 1 000 000 filas | ~50 s | ~120 MB |

La memoria se mantiene acotada — el generador streamea fila por fila
vía `csv.writer`, nunca acumulando el dataset completo.

## §4 — Encadenado en `mock generate`

```bash
cmcourier mock rvabrep --rows 50000 --output /tmp/r.csv --seed 50000
cmcourier mock generate --rvabrep-csv /tmp/r.csv --root /tmp/files \
  --pdf-min 100kb --pdf-max 2mb \
  --img-min 20kb --img-max 200kb \
  --seed 1
```

Las dos semillas son **independientes**:
- `--seed 50000` (rvabrep): controla qué fila obtiene qué shortname,
  txn_num, file_name, etc.
- `--seed 1` (generate): controla los bytes dentro de cada archivo
  (PDFs/TIFFs/JPEGs de página en blanco como filler, dimensionados
  entre los límites configurados).

Regenerar con la misma semilla RVABREP pero distinta semilla de
contenido de archivo te da el **mismo** CSV con **distintos** bytes —
útil para estresar el assembler con contenido nuevo mientras
mantenés la forma del trigger / RVABREP estable.

## §5 — Caveats de `--idrvi-source`

La fuente default es `docs/samples/csv/MapeoRVI_CM.csv` — la tabla de
mapping del banco shippeada con el repo, 282 IDRVIs distintos.
El generador elige los top `--idrvi-top` por **orden lexicográfico**
(determinista y agnóstico a la fuente). Default `20`.

Si apuntás `--idrvi-source` a un CSV con menos de `--idrvi-top` IDRVIs
distintos, el generador levanta un `ConfigurationError` — no hay fallback
silencioso. O bajás `--idrvi-top` o expandís la fuente.

### Alineando con el destino CMIS

Si planeás correr el batch generado de punta a punta contra un destino
CMIS (staging Alfresco, el CM staging del banco), tené en cuenta que
**cada IDRVI distinto en la salida va a demandar un registro de tipo
CMIS coincidente**. Con `--idrvi-top 20` tenés 20 IDRVIs distintos en
el batch — el pre-flight `doctor --check cm-targets` va a emitir 20
requests `getTypeDefinition`. Asegurate de que el destino tenga esos
tipos registrados, o:
- Bajá a `--idrvi-top 1` para una corrida smoke de un solo tipo.
- Overrideá `CMISType` por cada IDRVI en tu MapeoRVI_CM para apuntar
  a un único tipo de staging (ej. `D:cmcourier:bacDoc`) así los
  20 IDRVIs comparten un solo tipo CMIS.

## §6 — Cuándo NO usar esto

- **Corridas productivas.** El generador emite datos sintéticos con
  CIFs y shortnames sin sentido. La migración real usa el export RVABREP
  real del banco.
- **Reproducir un bug a partir de datos reales.** Si una fila real
  específica está disparando un fallo, querés la fila real, no una
  aproximación sintética.
- **Validación por tipo de documento.** La distribución Zipf sesga
  hacia unos pocos IDRVIs. Si necesitás testear un tipo de cola larga,
  fijá `--idrvi-top 1` con un `--idrvi-source` curado conteniendo solo
  ese tipo.

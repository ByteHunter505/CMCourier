> [← Volver al índice](../INDEX.md) · [Tutoriales](README.md)

# 02 — Pipelines y Cuándo Usarlas

CMCourier no tiene **un** comando de migración — tiene cuatro pipelines, cada una para un escenario distinto. Esto es a propósito: la spec de dominio insiste en que las pipelines son composiciones nombradas de stages, no un flag de config. Si lo que querés es diferente, el comando que disparás es diferente.

En este tutorial recorrés las cuatro: cuándo usar cada una, cómo se configura el `trigger`, el comando concreto, qué espera de entrada y qué saca como salida.

| Pipeline | Trigger kind | Para qué |
|----------|--------------|----------|
| `csv-trigger-pipeline` | `csv` | Tenés una lista externa (banco te pasa un Excel) |
| `rvabrep-pipeline` | `rvabrep` | Querés todo lo que matchea filtros sobre RVABREP |
| `local-scan-pipeline` | `local_scan` | Los archivos ya están extraídos a un directorio |
| `single-doc` | `single_doc` | Diagnóstico — un solo documento puntual |

Las tres primeras son productivas. La cuarta es para diagnosticar.

---

## `csv-trigger-pipeline`

### Cuándo usarla

Es el caso clásico de migración por lotes: el banco te entrega un Excel/CSV con la lista de documentos a migrar (shortname + CIF + system_id por fila). Vos enriquecés cada fila contra RVABREP, mapeás, ensamblás, subís.

### Configuración del trigger

```yaml
trigger:
  kind: csv
  csv_path: /data/lote-marzo.csv
  shortname_column: ShortName               # default
  cif_column: CIF                           # default
  system_id_column: SystemID                # default
```

Si las columnas tienen los nombres canónicos podés omitir los tres `*_column`.

### Comando

```bash
cmcourier csv-trigger-pipeline run \
  --config /etc/cmcourier/config.yaml \
  --batch-id lote-marzo-2026 \
  --total 5000                                  # opcional: tope para smoke runs
```

Flags más usadas:

| Flag | Para qué |
|------|----------|
| `--config` (Path, **required**) | Tu YAML |
| `--batch-id` (str) | ID del batch — si lo omitís se genera uno con timestamp |
| `--from-stage` (int 1–5, default 1) | Resume desde una stage específica |
| `--batch-size` (int) | Override del `batch_size` del YAML |
| `--triggers` (Path) | **Solo csv-trigger** — override del `csv_path` del YAML |
| `--skip-doctor` | Bypassea pre-flight (no recomendado) |
| `--resume` | Auto-detecta from-stage del estado del batch |
| `--tui / --no-tui` | TUI live (default `--tui`); apagala en CI |
| `--batches-in-flight` (1–2) | Override de overlap (solo batched) |
| `--total` (int) | Procesar a lo sumo N triggers |
| `--log-level` | DEBUG / INFO / WARNING / ERROR |

### Input / output

- **Input**: el CSV de triggers + las fuentes referenciadas por el config (RVABREP, mapping, fuentes de metadata).
- **Output**: filas en `migration_log` (SQLite), archivos en CMIS, métricas en `logs/`.

### Exit codes

| Código | Significado |
|--------|-------------|
| 0 | Run completo, todos los docs `S5_DONE` (o `S1_SKIPPED` / `S1_FILTERED` por trazabilidad) |
| 1 | Run completó pero con `S5_FAILED` — chequeá el tracking DB |
| 2 | Error de config — el YAML no carga |
| 3 | Excepción no manejada — bug |

---

## `rvabrep-pipeline`

### Cuándo usarla

No tenés lista externa — querés barrer la tabla RVABREP entera (o un subconjunto filtrado por sistema o tipo de documento) y subir todo lo que matchee. Caso típico: migración de cierre, donde el banco te dice "todo lo de los sistemas 1 y 3 desde 2020".

### Configuración del trigger

```yaml
trigger:
  kind: rvabrep
  filters:
    systems: ["1", "3"]                     # default [] = todos
    document_types: ["CC03", "FF17"]        # default [] = todos
```

Y como esta pipeline pega contra RVABREP en serio (es la única fuente), querés que `indexing.source` apunte al RVABREP real:

```yaml
indexing:
  source:
    kind: as400
    connection: { host: as400.banco.example }
    query: "SELECT * FROM RVILIB.RVABREP"
```

> RVABREP es **enorme** en producción (~20M filas). Desde 050, S0 streamea por chunks de `batch_size` para no hacer OOM. No materializa el SELECT entero en memoria.

### Comando

```bash
cmcourier rvabrep-pipeline run \
  --config /etc/cmcourier/config.yaml \
  --batch-id cierre-2026-q1
```

Los flags son los mismos que `csv-trigger-pipeline` **excepto `--triggers`** (no aplica — el trigger source es RVABREP, no un CSV externo).

### Input / output

- **Input**: la tabla RVABREP (CSV o AS400 vivo) filtrada por `filters.systems` y `filters.document_types`.
- **Output**: igual que csv-trigger.

---

## `local-scan-pipeline`

### Cuándo usarla

Los archivos ya están en disco — alguien hizo el extract del archivo original a una carpeta. Vos cruzás cada archivo contra RVABREP por nombre para sacar metadatos, y subís.

Pre-046, esta pipeline tenía un bug grosso (sobre-expansión: un archivo en el pool disparaba la subida de TODOS los docs del cliente). Desde 046 la corrige `LocalScanTrigger` polimórfico.

### Configuración del trigger

```yaml
trigger:
  kind: local_scan
  scan_path: /mnt/extracted-docs
```

El `scan_path` se valida como `DirectoryPath` — tiene que existir al cargar el config.

### Comando

```bash
cmcourier local-scan-pipeline run \
  --config /etc/cmcourier/config.yaml \
  --batch-id reextract-feb-2026
```

Mismos flags que `rvabrep-pipeline` (no hay `--triggers` acá tampoco).

### Input / output

- **Input**: cada archivo en `scan_path` se trata como un trigger. CMCourier resuelve el RVABREP por shortname.
- **Output**: igual.

---

## `single-doc`

### Cuándo usarla

Algo no funciona y querés correr UN documento de punta a punta para diagnosticar. No es para producción — es para reproducir un bug, validar que el config de metadata resuelve bien una propiedad puntual, ver qué pasa con un PDF roto.

### Configuración del trigger

```yaml
trigger:
  kind: single_doc                          # sin campos extra acá
```

Los datos del documento vienen por CLI, no por YAML.

### Comando

```bash
cmcourier single-doc run \
  --config /etc/cmcourier/config.yaml \
  --shortname JUAN_PEREZ \
  --system 1 \
  --cif 20123456789                         # opcional, se auto-resuelve si lo omitís
```

Flags adicionales sobre los de pipeline:

| Flag | Para qué |
|------|----------|
| `--shortname` (str, **required**) | Identificador corto del cliente/cuenta |
| `--system` (str, **required**) | System ID en RVI |
| `--cif` (str, opcional) | CIF; si lo omitís el indexing lo resuelve |

### Input / output

- **Input**: los tres parámetros + el config (que define dónde leer RVABREP, dónde subir, etc.).
- **Output**: una fila en `migration_log` + el objeto en CMIS. Salida verbose por consola (más allá del TUI).

### Cuándo NO usarla

No la uses como reemplazo de csv-trigger para "subir N docs uno por uno". Tenés overhead de carga de config por cada disparo. Si tenés N triggers, hacé un CSV de N filas y usá csv-trigger.

---

## Comparación rápida — diferencia entre csv-trigger y rvabrep

Las dos pipelines productivas más comunes se confunden. Esta es la diferencia.

| Pregunta | `csv-trigger-pipeline` | `rvabrep-pipeline` |
|----------|------------------------|---------------------|
| ¿Quién decide qué se sube? | Una lista externa (CSV de triggers) | Filtros sobre la tabla maestra |
| ¿Necesitás un CSV de triggers? | **Sí** (`trigger.csv_path`) | No |
| ¿Volumen típico? | Cientos a decenas de miles | Decenas de miles a millones |
| ¿Idempotencia importa? | Sí, pero el operador controla qué entra | Sí, **crítica** — re-correr "todo RVABREP" sin idempotencia te duplica |
| ¿Filtros por sistema/tipo? | Hacelos en el CSV antes de pasarlo | En `trigger.filters` |

> Si te dan un Excel y vas a hacer una migración chica → `csv-trigger`. Si te dicen "migrá todo lo que matchee X" → `rvabrep`.

---

## Patrones comunes

### Smoke run sobre los primeros 100 docs

```bash
cmcourier csv-trigger-pipeline run \
  --config staging.yaml \
  --total 100 \
  --no-tui \
  --log-level DEBUG
```

`--total 100` corta a los primeros 100 triggers. `--no-tui` te deja la consola limpia para grep. `--log-level DEBUG` te muestra detalles de cada stage.

### Re-correr un batch fallido desde S5

```bash
cmcourier csv-trigger-pipeline run \
  --config prod.yaml \
  --batch-id lote-marzo-2026 \
  --from-stage 5
```

Si los docs ya están `S4_DONE` (ensamblados) y solo falló la subida, `--from-stage 5` evita re-ensamblar. El resume detecta gaps con la lógica de 044.

### Auto-resume

```bash
cmcourier csv-trigger-pipeline run \
  --config prod.yaml \
  --batch-id lote-marzo-2026 \
  --resume
```

`--resume` mira el estado del batch en el tracking DB y deduce `from-stage` solo. Más cómodo que pasarlo a mano.

### Diagnosticar un doc puntual

```bash
cmcourier single-doc run \
  --config prod.yaml \
  --shortname JUAN_PEREZ \
  --system 1 \
  --log-level DEBUG
```

Útil cuando un doc falla en producción y querés ver el por qué exacto.

---

## El YAML define UNA pipeline

Algo importante: el `trigger.kind` del YAML **tiene que matchear** el comando que disparás. Si tu YAML tiene `kind: rvabrep` y lanzás `csv-trigger-pipeline run`, el CLI te tira error de validación (cada comando valida `expected_kind` contra `app.py:_run_pipeline_command`).

Si querés correr el mismo lote bajo dos modos, tenés dos YAMLs. No es restrictivo — es a propósito: el operador siempre sabe qué está corriendo.

---

## Siguientes pasos

- [03 — Batched vs streaming](03-execution-modes-batched-vs-streaming.md): cómo ejecuta el orquestador adentro
- [04 — Tour de todos los comandos](04-all-commands-tour.md): los comandos auxiliares (batch, inspect, analyze)
- [05 — `doctor` en profundidad](05-doctor-deep-dive.md): validar antes de correr
- [07 — Debugging de un batch fallido](07-debugging-a-failed-batch.md): qué hacer cuando algo se rompe
